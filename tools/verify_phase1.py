"""Phase 1 smoke verification: confirm the DB schema and log file are healthy."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rabbitsync.db.connection import ConnectionFactory  # noqa: E402
from rabbitsync.paths import db_path, logs_dir  # noqa: E402

EXPECTED_TABLES = {
    "migrations",
    "settings",
    "credential_refs",
    "github_accounts",
    "github_repos",
    "pairs",
    "blobs",
    "syncs",
    "journal_entries",
    "receipts",
    "file_cache",
    "pipelines",
    "pipeline_steps",
    "pipeline_runs",
    "step_runs",
    "step_cache",
}


def main() -> int:
    print(f"DB path: {db_path()}")
    if not db_path().exists():
        print("FAIL: DB file does not exist; run `python main.py` first.")
        return 1

    conn = ConnectionFactory().reader()
    journal = conn.execute("PRAGMA journal_mode;").fetchone()[0]
    fk_enforce = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
        )
    }
    migrations = conn.execute(
        "SELECT version, name, applied_at FROM migrations ORDER BY version;"
    ).fetchall()
    conn.close()

    print(f"journal_mode  : {journal}  (expect 'wal')")
    print(f"foreign_keys  : {fk_enforce}  (expect 1)")
    print(f"tables        : {len(tables)} found")
    print(f"migrations    : {[(m['version'], m['name']) for m in migrations]}")

    missing = EXPECTED_TABLES - tables
    extra = tables - EXPECTED_TABLES
    if missing:
        print(f"FAIL: missing tables: {sorted(missing)}")
    if extra:
        print(f"NOTE: extra tables (ok): {sorted(extra)}")

    log_files = sorted(logs_dir().glob("*.jsonl"))
    print(f"\nlog files: {len(log_files)}")
    for lf in log_files[-2:]:
        events = [json.loads(line) for line in lf.read_text(encoding="utf-8").splitlines() if line.strip()]
        wanted = {"app.start", "app.lock_acquired", "app.db_initialized", "ui.main_window.shown"}
        seen = {e.get("event") for e in events}
        ok = wanted.issubset(seen)
        print(f"  {lf.name}: {len(events)} events; required-events present: {ok}")
        if not ok:
            print(f"    missing: {sorted(wanted - seen)}")

    if journal != "wal":
        return 1
    if fk_enforce != 1:
        return 1
    if missing:
        return 1
    print("\nPHASE 1 SMOKE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
