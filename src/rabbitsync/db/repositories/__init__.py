"""Per-aggregate typed query API on top of SQLite.

Each module here owns one table (or a small cluster of related tables) and
returns pydantic models from :mod:`rabbitsync.models`. Reads use independent
connections from the :class:`db.connection.ConnectionFactory`; writes route
through the :class:`db.writer.DbWriter` thread.
"""

from __future__ import annotations
