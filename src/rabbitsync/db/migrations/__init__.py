"""Versioned SQL migrations.

Each migration is a single ``NNNN_name.sql`` file containing one or more SQL
statements. Migrations are applied in numeric order at startup; applied
versions are recorded in the ``migrations`` table. A migration must be a no-op
when its version is already recorded — but in practice we never re-apply.

Schema version backups are written to ``data/backups/_db/<ts>.db.zst`` BEFORE
any migration runs (Phase 4 will wire that up; for now the migrator simply
runs new migrations forward).
"""

from __future__ import annotations
