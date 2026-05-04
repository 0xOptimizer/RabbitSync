# RabbitSync

Safe source-to-copy folder synchronization with built-in git management and CI/CD pipelines, for Windows. Built with PySide 6 on Python 3.13+.

## What it does

- Register pairs of folders (a **source** you develop in, and a **copy** that gets the synchronized result, each with their own independent git history and remote).
- One-button working-tree sync from source to copy that respects `.gitignore` and an optional `.rabbitsyncignore`, with full snapshot, soft-delete quarantine, and journaled rollback.
- Per-project git management: status, log graph, branches, remotes, fetch/pull/push, stage, commit, branch operations.
- Per-pair CI/CD pipelines (lint / test / build / deploy) that run as argv subprocesses with hard timeouts and curated environments.
- GitHub repo browsing and one-click clone via a Personal Access Token.

## Safety floor

- Source is read-only to RabbitSync.
- A snapshot of the copy folder is taken before any sync write, into `data/backups/`.
- "Deleted" files in copy are moved into `data/quarantine/<sync-id>/`, never `unlink`-ed.
- Every state change is journaled; crash recovery prompts on next launch.
- Pipelines are argv-only; `shell=True` is forbidden codebase-wide.
- GitHub PAT is stored only in Windows Credential Manager via `keyring`, never in SQLite or plaintext on disk.

## Requirements

- Windows 10 or 11
- Python 3.13 or newer
- Git for Windows (the `git` binary on PATH; check with `git --version`)

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Optionally vendor the Lucide icon set used by the UI (requires internet):

```powershell
python tools\vendor_lucide.py
```

## Run

```powershell
python main.py
```

## Connecting GitHub

RabbitSync uses a GitHub Personal Access Token (PAT) — there is no OAuth flow.

### Option A — Fine-grained token (recommended)

1. Open <https://github.com/settings/personal-access-tokens/new>.
2. **Token name**: `RabbitSync` (or include your machine name, e.g. `RabbitSync — work-laptop`).
3. **Expiration**: 90 days is a sensible default.
4. **Resource owner**: your account (or an org you administer).
5. **Repository access**: `Public Repositories (read-only)` for browsing public repos, `All repositories` for listing/cloning your private repos, or `Only select repositories` to scope it tighter.
6. **Permissions** → **Repository permissions**:
   - **Contents**: **Read** (required for clone and metadata).
   - **Metadata**: **Read** (auto-selected).
   - Bump **Contents** to **Read and write** only if you want RabbitSync to push over HTTPS using this token.
7. Click **Generate token** and copy the value (it starts with `github_pat_`). It is shown once.
8. In RabbitSync, open the burger menu → **Connect GitHub…**, paste the token, click **Verify & Save**. The token is stored in Windows Credential Manager — never in SQLite, never on disk in plaintext.

### Option B — Classic token

1. Open <https://github.com/settings/tokens/new>.
2. **Note**: `RabbitSync`. **Expiration**: 90 days.
3. **Scopes**: tick `repo` (or `public_repo` for read-only public access).
4. Generate, copy the value (starts with `ghp_`), and paste into Connect GitHub as above.

## Storage layout

Everything RabbitSync stores lives under `data/` in the project directory and is gitignored:

```
data/
  rabbitsync.db           SQLite (WAL mode) — pairs, settings, syncs, receipts, etc.
  backups/<pair-id>/      Pre-sync snapshots (.tar.zst) of the copy folder.
  quarantine/<sync-id>/   Soft-deleted files from sync operations.
  pipelines/<pair-id>/    Pipeline run captures (stdout, stderr, result.json).
  logs/                   Rotated structured JSONL log files.
  .lock                   Global app instance lock.
```

See the [plan file](C:/Users/Admin/.claude/plans/hey-this-is-a-frolicking-rain.md) for the full architecture.
