"""Credential storage — OS keyring wrapper.

The single ``vault`` submodule is the only place in the codebase allowed to
import the ``keyring`` library. A custom AST lint rule flags any other
``import keyring`` site as a build failure.
"""

from __future__ import annotations
