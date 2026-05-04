"""RabbitSync logging package.

The stdlib ``logging`` module is intentionally not shadowed inside this package;
``import logging`` from any module within ``rabbitsync.logging.*`` resolves to
the stdlib because Python 3 uses absolute imports by default. To reach this
package's submodules use the explicit ``rabbitsync.logging.setup`` form.
"""

from __future__ import annotations
