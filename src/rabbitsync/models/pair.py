"""Sync-pair domain model."""

from __future__ import annotations

import datetime as _dt
import json

from pydantic import BaseModel, Field, field_validator


class Pair(BaseModel):
    """A registered source/copy pair."""

    id: str
    label: str
    source_path: str
    source_git_root: str | None = None
    source_subpath: str | None = None
    copy_path: str
    copy_git_root: str | None = None
    copy_subpath: str | None = None
    target_branch: str | None = None
    ignore_files: list[str] = Field(default_factory=list)
    commit_message_template: str = "sync: {src_branch}@{src_sha} — {n} files"
    auto_push: bool = False
    commit_on_sync: bool = True
    sync_check_interval_s: int = 30
    secret_scan_enabled: bool = True
    snapshot_before_pipeline: bool = True
    last_diff_adds: int = 0
    last_diff_modifies: int = 0
    last_diff_quarantines: int = 0
    last_diff_at: str | None = None
    created_at: _dt.datetime
    updated_at: _dt.datetime

    @field_validator("ignore_files", mode="before")
    @classmethod
    def _from_json(cls, v: object) -> object:
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                return parsed if isinstance(parsed, list) else []
            except json.JSONDecodeError:
                return []
        return v


__all__ = ["Pair"]
