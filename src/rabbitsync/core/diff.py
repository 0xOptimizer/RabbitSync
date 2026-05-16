"""Working-tree diff between source and copy folders.

Strategy
--------
1. **Scan** both sides into a manifest of ``{rel_path -> FileFact}`` honoring
   the ignore rules. ``FileFact`` carries size + mtime; the content hash is
   filled in lazily.
2. **Cheap classification** by name set:
   - in source only           → **add**
   - in copy only             → **quarantine** (would-be-deleted)
   - in both with same size+mtime → **unchanged** (fast path)
   - in both with different size  → **modify**
   - in both with same size, different mtime → **suspect** (needs hashing)
3. **Hash the suspects** on both sides; equal hashes downgrade to
   ``unchanged``, differing hashes promote to ``modify``.
4. **Integrity sample** of unchanged files (configurable rate, default 1%) is
   hashed on both sides as a corruption canary.

The output is a :class:`DiffPlan` — a frozen dataclass with the four lists
plus per-file metadata. No side effects; safe to call repeatedly.
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass, field
from pathlib import Path

from rabbitsync.core.hashing import xxh64_many
from rabbitsync.core.ignore import IgnoreRules
from rabbitsync.db.connection import ConnectionFactory
from rabbitsync.db.repositories import file_cache_repo
from rabbitsync.db.writer import DbWriter


@dataclass(frozen=True)
class FileFact:
    """Lightweight per-file record from a folder scan."""

    rel_path: str
    abs_path: Path
    size: int
    mtime_ns: int
    is_symlink: bool


@dataclass(frozen=True)
class ChangedFile:
    """One row of the diff plan."""

    rel_path: str
    source_size: int | None
    source_mtime_ns: int | None
    copy_size: int | None
    copy_mtime_ns: int | None


@dataclass(frozen=True)
class DiffPlan:
    """The set of changes a sync would apply to copy."""

    adds: tuple[ChangedFile, ...] = field(default_factory=tuple)
    modifies: tuple[ChangedFile, ...] = field(default_factory=tuple)
    quarantines: tuple[ChangedFile, ...] = field(default_factory=tuple)
    sample_verified: int = 0  # how many "unchanged" files we hash-sampled

    @property
    def is_noop(self) -> bool:
        return not (self.adds or self.modifies or self.quarantines)

    @property
    def total_changes(self) -> int:
        return len(self.adds) + len(self.modifies) + len(self.quarantines)


def scan(folder: Path, rules: IgnoreRules, *, side: str) -> dict[str, FileFact]:
    """Walk ``folder`` and return a manifest of non-excluded files.

    ``side`` is either ``"source"`` or ``"copy"``; the keep allowlist is only
    consulted for the copy side (it protects copy-only files from being
    quarantined). Returns relative paths in POSIX form so source and copy
    manifests compare cleanly.
    """
    out: dict[str, FileFact] = {}
    folder = folder.resolve(strict=True)
    base_len = len(str(folder)) + 1

    for dirpath, dirnames, filenames in os.walk(folder, followlinks=False):
        rel_dir = dirpath[base_len:].replace("\\", "/") if len(dirpath) > base_len else ""
        # Prune excluded subdirectories before descending.
        kept_dirs: list[str] = []
        for d in dirnames:
            rel = f"{rel_dir}/{d}" if rel_dir else d
            if rules.is_excluded(rel + "/") or rules.is_excluded(rel):
                continue
            kept_dirs.append(d)
        dirnames[:] = kept_dirs

        for name in filenames:
            rel = f"{rel_dir}/{name}" if rel_dir else name
            if rules.is_excluded(rel):
                continue
            abs_path = Path(dirpath) / name
            try:
                st = abs_path.lstat()
            except OSError:
                continue
            is_symlink = bool(st.st_mode & 0o170000 == 0o120000)
            # Symlinks are skipped by sync entirely (no follow, no copy);
            # log surface in a future phase.
            if is_symlink:
                continue
            out[rel] = FileFact(
                rel_path=rel,
                abs_path=abs_path,
                size=st.st_size,
                mtime_ns=st.st_mtime_ns,
                is_symlink=False,
            )

    _ = side  # currently no side-specific logic; keep signature for future use
    return out


def _hash_with_cache(
    rel_paths: list[str],
    manifest: dict[str, FileFact],
    cache: dict[str, file_cache_repo.CachedEntry],
    pending_writes: list[tuple[str, int, int, str]],
) -> dict[Path, str]:
    """Hash ``rel_paths`` via ``xxh64_many``, skipping cache hits.

    Files whose ``(size, mtime_ns)`` match the cache and carry a non-NULL
    hash are returned directly from the cache. Cache misses are hashed in a
    single ``xxh64_many`` call and appended to ``pending_writes`` so the
    caller can flush them to ``file_cache`` at the end.
    """
    out: dict[Path, str] = {}
    miss_paths: list[Path] = []
    miss_keys: list[str] = []
    for k in rel_paths:
        fact = manifest[k]
        cached = cache.get(k)
        if cached is not None:
            c_size, c_mtime, c_hash = cached
            if c_hash is not None and c_size == fact.size and c_mtime == fact.mtime_ns:
                out[fact.abs_path] = c_hash
                continue
        miss_paths.append(fact.abs_path)
        miss_keys.append(k)
    if miss_paths:
        new_hashes = xxh64_many(miss_paths)
        for k in miss_keys:
            fact = manifest[k]
            h = new_hashes.get(fact.abs_path)
            if h is not None:
                out[fact.abs_path] = h
                pending_writes.append((k, fact.size, fact.mtime_ns, h))
    return out


def diff(
    *,
    source_folder: Path,
    copy_folder: Path,
    rules: IgnoreRules,
    sample_rate: float = 0.01,
    rng_seed: int | None = None,
    pair_id: str | None = None,
    writer: DbWriter | None = None,
    factory: ConnectionFactory | None = None,
) -> DiffPlan:
    """Compute the :class:`DiffPlan` between source and copy.

    ``sample_rate`` is the fraction of "unchanged" files to hash on both
    sides as a corruption canary. Set to 0 to disable sampling (e.g. for
    fast inner-loop checks).

    When ``pair_id`` and ``factory`` are provided, the ``file_cache`` table
    is consulted to skip re-hashing files whose ``(size, mtime_ns)`` haven't
    changed since the last scan. When ``writer`` is also provided, newly
    computed hashes are persisted back to the cache.
    """
    src_manifest = scan(source_folder, rules, side="source")
    cpy_manifest = scan(copy_folder, rules, side="copy")

    # Load cached (size, mtime_ns, hash) for each side. Empty dicts when no
    # pair context — keeps the rest of the function uniform.
    if pair_id is not None:
        src_cache = file_cache_repo.load_for_side(pair_id, "source", factory=factory)
        cpy_cache = file_cache_repo.load_for_side(pair_id, "copy", factory=factory)
    else:
        src_cache = {}
        cpy_cache = {}
    src_pending: list[tuple[str, int, int, str]] = []
    cpy_pending: list[tuple[str, int, int, str]] = []

    src_keys = set(src_manifest.keys())
    cpy_keys = set(cpy_manifest.keys())

    adds: list[ChangedFile] = []
    quarantines: list[ChangedFile] = []
    modifies: list[ChangedFile] = []

    suspects: list[str] = []  # same size, different mtime -> hash to confirm
    unchanged: list[str] = []

    # in source only -> add
    for k in sorted(src_keys - cpy_keys):
        s = src_manifest[k]
        adds.append(ChangedFile(
            rel_path=k,
            source_size=s.size, source_mtime_ns=s.mtime_ns,
            copy_size=None, copy_mtime_ns=None,
        ))

    # in copy only -> quarantine (unless on copy's keep-list)
    for k in sorted(cpy_keys - src_keys):
        if rules.is_kept(k):
            continue
        c = cpy_manifest[k]
        quarantines.append(ChangedFile(
            rel_path=k,
            source_size=None, source_mtime_ns=None,
            copy_size=c.size, copy_mtime_ns=c.mtime_ns,
        ))

    # in both -> compare
    for k in sorted(src_keys & cpy_keys):
        if rules.is_kept(k):
            continue
        s = src_manifest[k]
        c = cpy_manifest[k]
        if s.size != c.size:
            modifies.append(ChangedFile(
                rel_path=k,
                source_size=s.size, source_mtime_ns=s.mtime_ns,
                copy_size=c.size, copy_mtime_ns=c.mtime_ns,
            ))
        elif s.mtime_ns == c.mtime_ns:
            unchanged.append(k)
        else:
            suspects.append(k)

    # Hash the suspects to disambiguate modify vs unchanged.
    if suspects:
        src_hashes = _hash_with_cache(suspects, src_manifest, src_cache, src_pending)
        cpy_hashes = _hash_with_cache(suspects, cpy_manifest, cpy_cache, cpy_pending)
        for k in suspects:
            sh = src_hashes.get(src_manifest[k].abs_path)
            ch = cpy_hashes.get(cpy_manifest[k].abs_path)
            if sh is not None and ch is not None and sh == ch:
                unchanged.append(k)
            else:
                s = src_manifest[k]
                c = cpy_manifest[k]
                modifies.append(ChangedFile(
                    rel_path=k,
                    source_size=s.size, source_mtime_ns=s.mtime_ns,
                    copy_size=c.size, copy_mtime_ns=c.mtime_ns,
                ))

    # Integrity sample of "unchanged" files.
    sample_count = 0
    if unchanged and sample_rate > 0:
        rng = random.Random(rng_seed)
        n = max(1, int(len(unchanged) * sample_rate))
        sample = rng.sample(unchanged, min(n, len(unchanged)))
        src_h = _hash_with_cache(sample, src_manifest, src_cache, src_pending)
        cpy_h = _hash_with_cache(sample, cpy_manifest, cpy_cache, cpy_pending)
        for k in sample:
            sh = src_h.get(src_manifest[k].abs_path)
            ch = cpy_h.get(cpy_manifest[k].abs_path)
            sample_count += 1
            if sh is not None and ch is not None and sh != ch:
                # Promote the silent-divergence case to a modify so sync
                # corrects it. Better to be loud about corruption than ignore it.
                s = src_manifest[k]
                c = cpy_manifest[k]
                modifies.append(ChangedFile(
                    rel_path=k,
                    source_size=s.size, source_mtime_ns=s.mtime_ns,
                    copy_size=c.size, copy_mtime_ns=c.mtime_ns,
                ))

    # Flush newly-computed hashes back to file_cache so the next scan can
    # skip them. Best-effort: a cache write failure must not break the diff.
    if pair_id is not None and writer is not None:
        try:
            file_cache_repo.upsert_hashes(
                writer, pair_id=pair_id, side="source", entries=src_pending,
            )
            file_cache_repo.upsert_hashes(
                writer, pair_id=pair_id, side="copy", entries=cpy_pending,
            )
        except Exception:  # noqa: BLE001 -- cache is an optimization, not load-bearing
            pass

    # Sort modifies for deterministic output.
    modifies.sort(key=lambda c: c.rel_path)
    return DiffPlan(
        adds=tuple(adds),
        modifies=tuple(modifies),
        quarantines=tuple(quarantines),
        sample_verified=sample_count,
    )


__all__ = ["ChangedFile", "DiffPlan", "FileFact", "diff", "scan"]
