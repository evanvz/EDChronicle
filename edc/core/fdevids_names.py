"""Offline reference tables mapping FDev internal module/ship symbols to
pretty display names — sourced from EDCD/FDevIDs outfitting.csv and
shipyard.csv (Frontier game data, no separate license grant; used
non-commercially under Frontier's community/fan content terms).

EDDN outfitting/1 and shipyard/1 messages carry the raw symbols
(e.g. 'int_shieldgenerator_size3_class3'); these tables give the display
name ('Shield Generator') for UI surfaces. Same vendored-JSON pattern as
rare_commodities.json.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, Optional

log = logging.getLogger("edc.fdevids")


class _SymbolTable:
    """Shared loader for symbol -> {name, ...} JSON files."""

    def __init__(self, settings_dir: Path, filename: str):
        self.path = Path(settings_dir) / filename
        self._symbols: Dict[str, Dict] = {}
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            symbols = data.get("symbols") if isinstance(data, dict) else None
            self._symbols = symbols if isinstance(symbols, dict) else {}
        except Exception:
            log.exception("Failed to load %s", self.path.name)
            self._symbols = {}

    def display_name(self, symbol: Optional[str]) -> Optional[str]:
        """Pretty name for an internal symbol, or None if unknown."""
        if not symbol:
            return None
        entry = self._symbols.get(symbol.strip().lower())
        if entry and entry.get("name"):
            return entry["name"]
        return None

    def symbol_for_display(self, query: str) -> Optional[str]:
        """Reverse lookup: exact (case-insensitive) display name or symbol
        -> internal symbol. For translating a user's typed name into the
        symbol the DB stores."""
        if not query:
            return None
        q = query.strip().lower()
        if q in self._symbols:
            return q
        for sym, entry in self._symbols.items():
            if entry.get("name", "").lower() == q:
                return sym
        return None

    def search_display(self, query: str) -> list[tuple[str, str]]:
        """Substring search over display names AND symbols — returns
        (symbol, display_name) pairs, display-name matches first."""
        if not query:
            return []
        q = query.strip().lower()
        name_hits = []
        symbol_hits = []
        for sym, entry in self._symbols.items():
            disp = entry.get("name", "")
            if q in disp.lower():
                name_hits.append((sym, disp))
            elif q in sym:
                symbol_hits.append((sym, disp))
        return name_hits + symbol_hits


class ModuleNameTable(_SymbolTable):
    def __init__(self, settings_dir: Path):
        super().__init__(settings_dir, "fdevids_modules.json")


class ShipNameTable(_SymbolTable):
    def __init__(self, settings_dir: Path):
        super().__init__(settings_dir, "fdevids_ships.json")
