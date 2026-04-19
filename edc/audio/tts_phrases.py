"""
TTS phrase utility for EDHelper.
Provides pick() for random template selection with safe placeholder handling.
"""

import random
import re
from typing import Any


def pick(templates: list, **kwargs: Any) -> str:
    """
    Randomly select a template and format it with provided keyword arguments.
    Any {placeholder} not supplied is stripped cleanly from the output.
    """
    if not templates:
        return ""
    template = random.choice(templates)
    result = template.format_map(_SafeFormat(kwargs))
    result = re.sub(r'\{[^}]+\}', '', result).strip()
    return re.sub(r'  +', ' ', result)


class _SafeFormat(dict):
    """Returns empty string for any missing key instead of raising KeyError."""
    def __missing__(self, key: str) -> str:
        return ''
