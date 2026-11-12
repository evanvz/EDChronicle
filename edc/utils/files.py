# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
# See the LICENSE file in the project root for full terms.

import os
from pathlib import Path


def write_text_atomic(path, text: str, encoding: str = "utf-8") -> None:
    """Writes beside the file, then swaps it in: a crash mid-write leaves the
    old file whole instead of a truncated one (settings.json holds API keys)."""
    tmp = Path(str(path) + ".tmp")
    try:
        tmp.write_text(text, encoding=encoding)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)   # never leave a copy of the keys lying beside the real file
        raise
