"""
TTS phrase utility for EDHelper.
Provides pick() for random template selection with safe placeholder handling.
"""

import random
import re
from typing import Any, Dict

# Last template picked per pool, keyed by the templates list's identity --
# phrase pools are fixed module/class-level list constants, never
# reassigned, so id(templates) is stable across calls for the process
# lifetime. Avoids picking the same line twice in a row: plain
# random.choice() could otherwise repeat a phrase back-to-back, which
# undermines the whole point of having multiple phrasings for variety.
_last_picked: Dict[int, str] = {}


def pick(templates: list, **kwargs: Any) -> str:
    """
    Randomly select a template and format it with provided keyword arguments,
    excluding whichever template this same pool picked last time (when more
    than one option exists). Any {placeholder} not supplied is stripped
    cleanly from the output.
    """
    if not templates:
        return ""
    if len(templates) == 1:
        template = templates[0]
    else:
        pool_id = id(templates)
        last = _last_picked.get(pool_id)
        choices = [t for t in templates if t != last] or templates
        template = random.choice(choices)
    _last_picked[id(templates)] = template
    result = template.format_map(_SafeFormat(kwargs))
    result = re.sub(r'\{[^}]+\}', '', result).strip()
    return re.sub(r'  +', ' ', result)


class _SafeFormat(dict):
    """Returns empty string for any missing key instead of raising KeyError."""
    def __missing__(self, key: str) -> str:
        return ''
