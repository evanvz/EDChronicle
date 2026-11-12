# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
# See the LICENSE file in the project root for full terms.

from typing import Any


def norm_text(v: Any) -> str:
    """Journal strings for stable dict keys: inner whitespace collapsed, ends stripped; non-strings give ""."""
    return " ".join(v.split()) if isinstance(v, str) else ""
