"""Vendor the Lucide SVG icons that the UI uses.

Downloads each icon listed in :func:`rabbitsync.ui.icons.catalog` from the
Lucide GitHub repo at a pinned commit, writes it under
``src/rabbitsync/assets/icons/lucide/``, and rewrites ``INDEX.json``.

Run once at project setup:

    python tools/vendor_lucide.py

Re-run after bumping ``LUCIDE_REF`` to update.
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request
from pathlib import Path

# Pin to a specific Lucide release for reproducibility.
LUCIDE_REF = "1.14.0"
BASE_URL = f"https://raw.githubusercontent.com/lucide-icons/lucide/{LUCIDE_REF}/icons"

# Importing the package without PySide6 installed must still work for this
# script — so we add src/ to sys.path and import the catalog directly.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rabbitsync.ui.icons import catalog, write_index  # noqa: E402

OUT_DIR = ROOT / "src" / "rabbitsync" / "assets" / "icons" / "lucide"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    icons = catalog()
    print(f"Vendoring {len(icons)} icons from Lucide {LUCIDE_REF}")
    print(f"-> {OUT_DIR}\n")

    failed: list[tuple[str, str]] = []
    skipped = 0
    fetched = 0
    for name, basename in sorted(icons.items()):
        target = OUT_DIR / f"{basename}.svg"
        if target.is_file():
            print(f"  skip   {basename}.svg (already present)")
            skipped += 1
            continue
        url = f"{BASE_URL}/{basename}.svg"
        try:
            data = _fetch(url)
        except urllib.error.HTTPError as exc:
            failed.append((basename, f"HTTP {exc.code}"))
            print(f"  FAIL   {basename}.svg ({exc.code})")
            continue
        except urllib.error.URLError as exc:
            failed.append((basename, str(exc.reason)))
            print(f"  FAIL   {basename}.svg ({exc.reason})")
            continue
        target.write_bytes(data)
        print(f"  fetch  {basename}.svg ({len(data)} bytes)  [{name}]")
        fetched += 1

    index_path = write_index(OUT_DIR / "INDEX.json")
    print(f"\nWrote {index_path.relative_to(ROOT)}")
    print(f"Summary: fetched={fetched}, skipped={skipped}, failed={len(failed)}")

    if failed:
        print("\nFailed icons:")
        for basename, reason in failed:
            print(f"  - {basename}.svg  ({reason})")
        return 1
    return 0


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "rabbitsync-vendor/0.1"})
    with urllib.request.urlopen(request, timeout=30) as resp:  # noqa: S310 -- pinned URL
        return resp.read()


if __name__ == "__main__":
    raise SystemExit(main())
