-- 0002_pair_ui_state.sql
-- Per-pair UI state that needs to survive restarts.
--
-- Adds `commit_on_sync` to the pairs table so the user's Sync-tab checkbox
-- choice persists per pair (matches `auto_push` already on this table).

ALTER TABLE pairs ADD COLUMN commit_on_sync INTEGER NOT NULL DEFAULT 1;
