"""Lay out a git commit graph into lanes for rendering.

Algorithm
---------
1. Run ``git log --all --topo-order --date-order --format=...`` once.
2. Walk in topological order, maintaining a list of "active lanes" — each
   lane is the SHA we expect to see on its next row.
3. For each commit:
   - Find the lane whose expected SHA matches this commit; if none, claim a
     new lane (this is a branch tip we just discovered).
   - For each parent: either reuse an active lane (merge: parent already
     expected on some lane) or claim a new lane.
4. Emit a :class:`GraphRow` per commit with lane index, edges entering and
   leaving the row, and any ref decorations.

Output is consumed by ``ui/widgets/log_graph_view.py``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from rabbitsync.core.git import GitRunner
from rabbitsync.core.git_resolve import GitContext


@dataclass(frozen=True)
class GraphCommit:
    sha: str
    short_sha: str
    parents: tuple[str, ...]
    author: str
    author_email: str
    author_time: int  # unix seconds
    subject: str
    refs: tuple[str, ...]


@dataclass(frozen=True)
class GraphEdge:
    """An edge between two row-positions in adjacent rows.

    ``from_lane`` and ``to_lane`` are lane indices. ``kind`` distinguishes
    rendering styles: ``straight`` (vertical), ``merge`` (incoming from a
    different lane), ``branch`` (outgoing to a new lane).
    """

    from_lane: int
    to_lane: int
    kind: str  # 'straight' | 'merge' | 'branch'


@dataclass(frozen=True)
class GraphRow:
    """One commit row."""

    commit: GraphCommit
    lane: int
    edges_in: tuple[GraphEdge, ...]
    edges_out: tuple[GraphEdge, ...]
    lane_color: str  # 6-char hex


@dataclass(frozen=True)
class GraphLayout:
    rows: tuple[GraphRow, ...] = field(default_factory=tuple)


# 10 colorblind-safe lane colors (Okabe-Ito + Tol palette mix).
_LANE_PALETTE: tuple[str, ...] = (
    "#0072B2",  # blue
    "#E69F00",  # orange
    "#009E73",  # green
    "#CC79A7",  # pink
    "#56B4E9",  # sky
    "#D55E00",  # vermillion
    "#F0E442",  # yellow
    "#999999",  # gray
    "#882255",  # wine
    "#117733",  # forest
)


def lane_color_for(lineage_sha: str) -> str:
    """Stable color for a lane, derived from the lane's anchor SHA."""
    if not lineage_sha:
        return _LANE_PALETTE[0]
    h = hashlib.md5(lineage_sha.encode("utf-8"), usedforsecurity=False).digest()
    idx = h[0] % len(_LANE_PALETTE)
    return _LANE_PALETTE[idx]


def build(ctx: GitContext, *, limit: int | None = None) -> GraphLayout:
    """Compute the graph layout for ``ctx``'s repository."""
    if not ctx.has_git or ctx.git_root is None:
        return GraphLayout(rows=())

    runner = GitRunner(ctx.git_root)
    fmt = "%H%x00%h%x00%P%x00%an%x00%ae%x00%at%x00%s%x00%D"
    args = ["log", "--all", "--topo-order", "--date-order", "--no-color",
            f"--pretty=format:{fmt}"]
    if limit is not None:
        args.append(f"--max-count={int(limit)}")
    result = runner.run(args, check=False)
    if not result.ok:
        return GraphLayout(rows=())

    commits = list(_parse_commits(result.stdout))
    if not commits:
        return GraphLayout(rows=())

    # Lane assignment.
    rows: list[GraphRow] = []
    active: list[str | None] = []  # each entry is the SHA we expect next on that lane
    lane_anchor: dict[int, str] = {}  # lane index -> anchor sha (for stable color)

    for commit in commits:
        # Find the lane that was waiting for this commit's SHA.
        own_lane: int | None = None
        for i, expected in enumerate(active):
            if expected == commit.sha:
                own_lane = i
                break
        if own_lane is None:
            own_lane = _claim_lane(active)
            lane_anchor.setdefault(own_lane, commit.sha)

        # Edges entering this row from the previous row's "active" set.
        edges_in: list[GraphEdge] = []
        for i, expected in enumerate(active):
            if expected is None:
                continue
            if expected == commit.sha:
                kind = "merge" if i != own_lane else "straight"
                edges_in.append(GraphEdge(from_lane=i, to_lane=own_lane, kind=kind))
            else:
                # Lane keeps its expectation, edge passes through.
                edges_in.append(GraphEdge(from_lane=i, to_lane=i, kind="straight"))

        # After this row, the lanes update: free lanes that just merged in;
        # claim lanes for parents.
        for i in range(len(active)):
            if active[i] == commit.sha and i != own_lane:
                active[i] = None  # this lane merged into own_lane and is now free

        if not commit.parents:
            active[own_lane] = None
        else:
            # First parent stays on own_lane.
            active[own_lane] = commit.parents[0]
            # Subsequent parents are branches/merges from other lanes.
            for parent in commit.parents[1:]:
                # Try to reuse an active lane that is already waiting for this parent.
                reused = False
                for i, expected in enumerate(active):
                    if expected == parent:
                        reused = True
                        break
                if not reused:
                    new_lane = _claim_lane(active)
                    active[new_lane] = parent
                    lane_anchor.setdefault(new_lane, parent)

        # Edges leaving this row to the next row.
        edges_out: list[GraphEdge] = []
        for i, expected in enumerate(active):
            if expected is None:
                continue
            if i == own_lane:
                edges_out.append(GraphEdge(from_lane=own_lane, to_lane=i, kind="straight"))
            elif expected in commit.parents and expected != commit.parents[0]:
                edges_out.append(GraphEdge(from_lane=own_lane, to_lane=i, kind="branch"))
            else:
                edges_out.append(GraphEdge(from_lane=i, to_lane=i, kind="straight"))

        color = lane_color_for(lane_anchor.get(own_lane, commit.sha))
        rows.append(GraphRow(
            commit=commit,
            lane=own_lane,
            edges_in=tuple(edges_in),
            edges_out=tuple(edges_out),
            lane_color=color,
        ))

    return GraphLayout(rows=tuple(rows))


def _claim_lane(active: list[str | None]) -> int:
    """Return the index of a free lane, growing the list if necessary."""
    for i, expected in enumerate(active):
        if expected is None:
            return i
    active.append(None)
    return len(active) - 1


def _parse_commits(text: str):  # noqa: ANN201
    for line in text.splitlines():
        if not line:
            continue
        parts = line.split("\x00")
        if len(parts) < 8:
            continue
        sha, short, parents_str, an, ae, at, subject, decoration = parts[:8]
        try:
            author_time = int(at)
        except ValueError:
            author_time = 0
        refs = tuple(_parse_decoration(decoration))
        yield GraphCommit(
            sha=sha,
            short_sha=short,
            parents=tuple(p for p in parents_str.split() if p),
            author=an,
            author_email=ae,
            author_time=author_time,
            subject=subject,
            refs=refs,
        )


def _parse_decoration(decoration: str):  # noqa: ANN201
    decoration = decoration.strip()
    if decoration.startswith("(") and decoration.endswith(")"):
        decoration = decoration[1:-1]
    for raw in decoration.split(","):
        token = raw.strip()
        if not token:
            continue
        if "->" in token:
            head, _, target = token.partition("->")
            yield head.strip()
            yield target.strip()
        else:
            yield token


__all__ = ["GraphCommit", "GraphEdge", "GraphLayout", "GraphRow", "build", "lane_color_for"]
