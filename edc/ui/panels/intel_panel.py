import logging
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QScrollArea,
    QFrame,
)
from PyQt6.QtCore import Qt

log = logging.getLogger(__name__)


class IntelPanel(QWidget):
    """
    Owns all widgets and refresh logic for the Intel tab.
    Receives state and farming_locations via refresh().
    Shows:
      1. External POIs for current system
      2. Farming locations matching current system
      3. Full farming guide browsable by category
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Header strip ──────────────────────────────────────────────────
        hdr = QWidget()
        hdr_l = QVBoxLayout(hdr)
        hdr_l.setContentsMargins(8, 6, 8, 4)
        hdr_l.setSpacing(2)
        self.intel_summary = QLabel("")
        self.intel_summary.setWordWrap(True)
        hdr_l.addWidget(self.intel_summary)
        outer.addWidget(hdr, 0)

        # ── Scroll area ───────────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        outer.addWidget(scroll, 1)

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setSpacing(6)
        self._content_layout.setContentsMargins(8, 6, 8, 8)
        self._content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(content)

        # ── POIs card ─────────────────────────────────────────────────────
        poi_frame = QFrame()
        poi_frame.setStyleSheet(
            "QFrame { background: #0d1a2a; border: 1px solid #1e3a5a;"
            "border-radius: 5px; }"
        )
        poi_l = QVBoxLayout(poi_frame)
        poi_l.setContentsMargins(8, 6, 8, 6)
        poi_l.setSpacing(4)
        poi_hdr = QLabel("EXTERNAL POINTS OF INTEREST")
        poi_hdr.setStyleSheet(
            "color: #555555; font-size: 10px; font-weight: bold; "
            "letter-spacing: 1px; background: transparent; border: none;"
        )
        poi_l.addWidget(poi_hdr)
        self.poi_display = QLabel("")
        self.poi_display.setWordWrap(True)
        self.poi_display.setTextFormat(Qt.TextFormat.RichText)
        self.poi_display.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.poi_display.setStyleSheet("background: transparent; border: none;")
        poi_l.addWidget(self.poi_display)
        self._content_layout.addWidget(poi_frame)

        # ── System farming card ───────────────────────────────────────────
        farm_frame = QFrame()
        farm_frame.setStyleSheet(
            "QFrame { background: #1a1400; border: 1px solid #3a2e00;"
            "border-radius: 5px; }"
        )
        farm_l = QVBoxLayout(farm_frame)
        farm_l.setContentsMargins(8, 6, 8, 6)
        farm_l.setSpacing(4)
        farm_hdr = QLabel("FARMING LOCATIONS — THIS SYSTEM")
        farm_hdr.setStyleSheet(
            "color: #555555; font-size: 10px; font-weight: bold; "
            "letter-spacing: 1px; background: transparent; border: none;"
        )
        farm_l.addWidget(farm_hdr)
        self.farming_display = QLabel("")
        self.farming_display.setWordWrap(True)
        self.farming_display.setTextFormat(Qt.TextFormat.RichText)
        self.farming_display.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.farming_display.setStyleSheet("background: transparent; border: none;")
        farm_l.addWidget(self.farming_display)
        self._content_layout.addWidget(farm_frame)

        # ── Full farming guide card ───────────────────────────────────────
        guide_frame = QFrame()
        guide_frame.setStyleSheet(
            "QFrame { background: #0d1a10; border: 1px solid #1e3a20;"
            "border-radius: 5px; }"
        )
        guide_l = QVBoxLayout(guide_frame)
        guide_l.setContentsMargins(8, 6, 8, 6)
        guide_l.setSpacing(4)
        guide_hdr = QLabel("FARMING GUIDE — ALL CATEGORIES")
        guide_hdr.setStyleSheet(
            "color: #555555; font-size: 10px; font-weight: bold; "
            "letter-spacing: 1px; background: transparent; border: none;"
        )
        guide_l.addWidget(guide_hdr)
        self.guide_display = QLabel("")
        self.guide_display.setWordWrap(True)
        self.guide_display.setTextFormat(Qt.TextFormat.RichText)
        self.guide_display.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.guide_display.setStyleSheet("background: transparent; border: none;")
        guide_l.addWidget(self.guide_display)
        self._content_layout.addWidget(guide_frame)

    def _esc(self, t):
        return str(t or "").replace(
            "&", "&amp;"
        ).replace("<", "&lt;").replace(">", "&gt;")

    def _domain_color(self, domain):
        d = str(domain or "").lower()
        colors = {
            "encoded":       ("#4D96FF", "#1a2a3a"),
            "raw":           ("#6BCB77", "#1a2a1a"),
            "manufactured":  ("#FFD93D", "#2a2200"),
            "odyssey_onfoot":("#C77DFF", "#1a1a2a"),
            "guardian":      ("#FF8888", "#2a1a1a"),
            "thargoid":      ("#FF6B6B", "#2a0a0a"),
        }
        return colors.get(d, ("#FFB347", "#2a1a00"))

    def _farm_entry_html(self, loc, highlight=False):
        domain = str(loc.get("domain") or "")
        name   = str(loc.get("name") or loc.get("location") or "")
        body   = str(loc.get("body") or "")
        method = str(loc.get("method") or "")
        note   = str(loc.get("note") or "")
        mats   = (
            loc.get("key_materials")
            or loc.get("materials")
            or loc.get("mats")
            or []
        )
        system = str(loc.get("system") or "")

        fg, bg = self._domain_color(domain)
        dom_badge = (
            f'<span style="background:{bg};color:{fg};'
            f'font-size:10px;font-weight:700;padding:1px 5px;'
            f'border-radius:3px;">{self._esc(domain.upper())}</span>'
        ) if domain else ""

        if highlight:
            line = (
                '<div style="margin-bottom:8px;padding:4px 8px;'
                'background:#1a2a00;border-left:3px solid #6BCB77;'
                'border-radius:4px;">'
                '<span style="color:#6BCB77;font-size:10px;'
                'font-weight:700;">✓ AVAILABLE NOW &nbsp;</span>'
            )
        else:
            line = '<div style="margin-bottom:8px;padding:4px 0;">'
        if dom_badge:
            line += f'{dom_badge} '
        if name:
            line += (
                f'<span style="color:#CCCCCC;font-weight:700;">'
                f'{self._esc(name)}</span>'
            )
        if system:
            line += (
                f' <span style="color:#4D96FF;font-size:10px;">'
                f'— {self._esc(system)}</span>'
            )
        if body:
            line += (
                f' <span style="color:#888888;font-size:10px;">'
                f'/ {self._esc(body)}</span>'
            )
        if method:
            line += (
                f'<br><span style="color:#6BCB77;font-size:10px;">'
                f'&nbsp;&nbsp;⚙ {self._esc(method)}</span>'
            )
        if note:
            line += (
                f'<br><span style="color:#FFD93D;font-size:10px;">'
                f'&nbsp;&nbsp;📌 {self._esc(note)}</span>'
            )
        if mats:
            if isinstance(mats, list):
                mat_txt = ", ".join(str(m) for m in mats[:8])
            else:
                mat_txt = str(mats)
            line += (
                f'<br><span style="color:#FFD93D;font-size:10px;">'
                f'&nbsp;&nbsp;Mats: {self._esc(mat_txt)}</span>'
            )
        # Sites array — multiple system/body locations
        sites = loc.get("sites") or []
        if isinstance(sites, list) and sites:
            line += (
                '<br><span style="color:#555555;font-size:10px;">'
                '&nbsp;&nbsp;Sites:</span>'
            )
            for site in sites[:8]:
                if not isinstance(site, dict):
                    continue
                s_sys  = str(site.get("system") or "")
                s_body = str(site.get("body") or "")
                s_mats = site.get("materials") or []
                s_coords = str(site.get("coords") or "")

                site_line = ""
                if s_sys:
                    site_line += (
                        f'<span style="color:#4D96FF;">'
                        f'{self._esc(s_sys)}</span>'
                    )
                if s_body:
                    site_line += (
                        f' <span style="color:#888888;">'
                        f'/ {self._esc(s_body)}</span>'
                    )
                if s_coords:
                    site_line += (
                        f' <span style="color:#555555;font-size:10px;">'
                        f'({self._esc(s_coords)})</span>'
                    )
                if isinstance(s_mats, list) and s_mats:
                    mat_str = ", ".join(str(m) for m in s_mats[:4])
                    site_line += (
                        f' <span style="color:#FFD93D;font-size:10px;">'
                        f'— {self._esc(mat_str)}</span>'
                    )
                if site_line:
                    line += (
                        f'<br><span style="font-size:10px;">'
                        f'&nbsp;&nbsp;&nbsp;&nbsp;• {site_line}</span>'
                    )

        line += '</div>'
        return line

    def _get_system_opportunities(self, state):
        """
        Returns a set of tags describing what farming
        opportunities exist in the current system.
        """
        tags = set()

        # Allegiance/Government
        govt = str(getattr(state, "system_government", "") or "").lower()
        alleg = str(getattr(state, "system_allegiance", "") or "").lower()
        sec = str(getattr(state, "system_security", "") or "").lower()
        econ = str(getattr(state, "system_economy", "") or "").lower()

        if "anarchy" in govt:
            tags.add("anarchy")
        if "low" in sec:
            tags.add("low_security")
        if "high tech" in econ or "hightech" in econ:
            tags.add("high_tech")
        if "military" in econ:
            tags.add("military")
        if "industrial" in econ:
            tags.add("industrial")

        # Faction active states
        for f in (getattr(state, "factions", None) or []):
            if not isinstance(f, dict):
                continue
            active = f.get("ActiveStates") or []
            faction_state = str(f.get("FactionState") or "").lower()
            all_states = [faction_state]
            for st in active:
                if isinstance(st, dict):
                    all_states.append(
                        str(st.get("State") or "").lower()
                    )
            for s in all_states:
                if "boom" in s:
                    tags.add("boom")
                if "war" in s or "civil war" in s:
                    tags.add("war")
                if "outbreak" in s:
                    tags.add("outbreak")
                if "pirate" in s:
                    tags.add("pirate_attack")
                if "election" in s:
                    tags.add("election")
                if "expansion" in s:
                    tags.add("expansion")

        return tags

    def _entry_matches_system(self, loc, tags):
        """
        Returns True if this farming entry is relevant
        to the current system based on active tags.
        """
        name   = str(loc.get("name") or "").lower()
        method = str(loc.get("method") or "").lower()
        combined = name + " " + method

        if "boom" in tags and any(
            k in combined for k in ["boom", "hge", "high grade"]
        ):
            return True
        if "war" in tags and any(
            k in combined for k in ["war", "conflict", "cz", "combat zone"]
        ):
            return True
        if "outbreak" in tags and "outbreak" in combined:
            return True
        if "anarchy" in tags and any(
            k in combined for k in ["anarchy", "high wake", "wake scan"]
        ):
            return True
        if "low_security" in tags and any(
            k in combined for k in ["low", "anarchy", "pirate"]
        ):
            return True
        if "pirate_attack" in tags and "pirate" in combined:
            return True
        return False

    def refresh(self, state, farming_locations):
        sys_name = getattr(state, "system", None) or ""

        # ── POIs ──────────────────────────────────────────────────────────
        pois = getattr(state, "external_pois", None) or []
        poi_html = []

        for poi in pois:
            if not isinstance(poi, dict):
                continue
            cat    = str(poi.get("category") or "POI")
            title  = str(poi.get("title") or "")
            body   = str(poi.get("body") or "")
            note   = str(poi.get("note") or "")
            source = str(poi.get("source") or "")

            cat_badge = (
                f'<span style="background:#1a2a3a;color:#4D96FF;'
                f'font-size:10px;font-weight:700;padding:1px 5px;'
                f'border-radius:3px;">{self._esc(cat)}</span>'
            )
            line = f'<div style="margin-bottom:6px;">{cat_badge} '
            if title:
                line += (
                    f'<span style="color:#CCCCCC;font-weight:700;">'
                    f'{self._esc(title)}</span>'
                )
            if body:
                line += f' <span style="color:#888888;">— {self._esc(body)}</span>'
            if note:
                line += (
                    f'<br><span style="color:#FFD93D;font-size:10px;">'
                    f'&nbsp;&nbsp;📌 {self._esc(note)}</span>'
                )
            if source:
                line += (
                    f'<br><span style="color:#555555;font-size:10px;">'
                    f'&nbsp;&nbsp;src: {self._esc(source)}</span>'
                )
            line += '</div>'
            poi_html.append(line)

        self.poi_display.setText(
            "".join(poi_html) if poi_html else
            '<span style="color:#444444;font-size:11px;">'
            'No external POIs for this system.<br>'
            'Add POIs to <code>settings/external_pois.json</code> '
            'to see them here.</span>'
        )

        # ── System-specific farming ───────────────────────────────────────
        farm_entries = []
        if farming_locations:
            try:
                all_records = getattr(farming_locations, "_records", []) or []
                opportunities = self._get_system_opportunities(state)
            except Exception:
                farm_entries = []

        farm_html = [self._farm_entry_html(loc) for loc in farm_entries
                     if isinstance(loc, dict)]

        self.farming_display.setText(
            "".join(farm_html) if farm_html else
            '<span style="color:#444444;font-size:11px;">'
            'No specific farming locations for this system.<br>'
            'Browse the full guide below.</span>'
        )

        # ── Full farming guide ────────────────────────────────────────────
        guide_html = []
        if farming_locations:
            try:
                all_records = getattr(farming_locations, "_records", []) or []
                # Group by domain
                domain_order = [
                    "encoded", "raw", "manufactured",
                    "odyssey_onfoot", "guardian", "thargoid"
                ]
                domain_labels = {
                    "encoded":        "ENCODED",
                    "raw":            "RAW",
                    "manufactured":   "MANUFACTURED",
                    "odyssey_onfoot": "ODYSSEY ON-FOOT",
                    "guardian":       "GUARDIAN",
                    "thargoid":       "THARGOID",
                }
                grouped = {}
                for rec in all_records:
                    if not isinstance(rec, dict):
                        continue
                    d = str(rec.get("domain") or "other").lower()
                    grouped.setdefault(d, []).append(rec)

                # Known domains first, then any extras
                all_domains = domain_order + [
                    d for d in grouped if d not in domain_order
                ]

                for domain in all_domains:
                    entries = grouped.get(domain, [])
                    if not entries:
                        continue
                    fg, bg = self._domain_color(domain)
                    label = domain_labels.get(domain, domain.upper())
                    guide_html.append(
                        f'<div style="margin-top:8px;margin-bottom:4px;">'
                        f'<span style="color:{fg};font-weight:700;'
                        f'font-size:11px;letter-spacing:1px;">'
                        f'{self._esc(label)}</span>'
                        f'<span style="color:#555555;font-size:10px;">'
                        f' ({len(entries)} entries)</span>'
                        f'</div>'
                    )
                    for loc in entries:
                        is_match = self._entry_matches_system(
                            loc, opportunities
                        )
                        guide_html.append(
                            self._farm_entry_html(loc, highlight=is_match)
                        )

            except Exception:
                guide_html = []

        self.guide_display.setText(
            "".join(guide_html) if guide_html else
            '<span style="color:#444444;font-size:11px;">'
            'No farming guide loaded.<br>'
            'Check <code>settings/elite_farming_locations.json</code>.'
            '</span>'
        )

        # ── Summary ───────────────────────────────────────────────────────
        n_poi  = len(pois)
        n_farm = len(farm_entries)
        if n_poi == 0 and n_farm == 0:
            self.intel_summary.setText(
                "Intel (External, advisory only) — "
                "No system-specific intel."
            )
        else:
            parts = []
            if n_poi:
                parts.append(f"{n_poi} POI{'s' if n_poi != 1 else ''}")
            if n_farm:
                parts.append(
                    f"{n_farm} farming location{'s' if n_farm != 1 else ''}"
                )
            self.intel_summary.setText(
                "Intel (External, advisory only) — "
                + " | ".join(parts)
            )
