-- 0003_pair_last_diff.sql
-- Cache the most recent diff result per pair so the UI can show counts
-- instantly on pair selection while the real diff runs in the background.

ALTER TABLE pairs ADD COLUMN last_diff_adds INTEGER NOT NULL DEFAULT 0;
ALTER TABLE pairs ADD COLUMN last_diff_modifies INTEGER NOT NULL DEFAULT 0;
ALTER TABLE pairs ADD COLUMN last_diff_quarantines INTEGER NOT NULL DEFAULT 0;
ALTER TABLE pairs ADD COLUMN last_diff_at TEXT;
