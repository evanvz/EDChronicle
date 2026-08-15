import logging
from urllib.parse import quote, unquote

from persistence.repository import _parse_states
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QScrollArea,
    QFrame,
    QApplication,
)
from PyQt6.QtCore import Qt

log = logging.getLogger(__name__)


def _get_system_opportunities(state):
    """
    Returns a set of tags describing what farming opportunities exist
    in the current system, from live game state. Module-level (not a
    method) so it's testable without a QApplication.
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
    if "empire" in alleg:
        tags.add("empire")
    if "federation" in alleg:
        tags.add("federation")

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
            if "civilunrest" in s:
                tags.add("civil_unrest")
            if "infrastructurefailure" in s:
                tags.add("infrastructure_failure")

    return tags


def _tags_from_faction_snapshot_row(row: dict) -> set:
    """
    Same tag vocabulary as _get_system_opportunities(), derived from a
    persisted faction_snapshots row (government/allegiance/faction_state/
    active_states) instead of live game state -- used for searching
    systems the player isn't currently in. No security/economy tags:
    faction_snapshots doesn't carry those columns (they're system-level,
    not per-faction), and none of this guide's state_tags need them.
    """
    tags = set()
    govt = str(row.get("government") or "").lower()
    alleg = str(row.get("allegiance") or "").lower()
    if "anarchy" in govt:
        tags.add("anarchy")
    if "empire" in alleg:
        tags.add("empire")
    if "federation" in alleg:
        tags.add("federation")

    all_states = [str(row.get("faction_state") or "").lower()]
    all_states += [s.lower() for s in _parse_states(row.get("active_states"))]
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
        if "civilunrest" in s:
            tags.add("civil_unrest")
        if "infrastructurefailure" in s:
            tags.add("infrastructure_failure")

    return tags


_STATE_TEXT_TAGS = {
    "outbreak": "outbreak",
    "boom": "boom",
}


def _state_text_to_tags(state_text: str) -> set:
    """
    Maps an examples[].state free-text value (from the farming guide's
    HGE entry) to the live-tag vocabulary _get_system_opportunities()
    produces. Deliberately narrow -- covers only the known state-text
    variants this guide's data actually uses, not a general parser.
    """
    s = (state_text or "").lower()
    tags = set()
    for key, tag in _STATE_TEXT_TAGS.items():
        if key in s:
            tags.add(tag)
    if "war" in s:
        tags.add("war")
    if "imperial" in s:
        tags.add("empire")
    if "federal" in s:
        tags.add("federation")
    return tags


def _entry_matches_system(loc: dict, tags: set) -> set:
    """
    Returns the subset of `tags` this entry actually matches, driven by
    curated data (loc["state_tags"], or -- for entries with an
    examples[] list -- each example's own state mapped via
    _state_text_to_tags()) -- never free-text keyword guessing against
    the entry's name/method. Empty set means no live match (the entry
    may still appear via an exact system/body name match, a separate,
    unrelated path in FarmingLocations.get_for_system()).
    """
    examples = loc.get("examples")
    if isinstance(examples, list) and examples:
        matched = set()
        for ex in examples:
            if not isinstance(ex, dict):
                continue
            matched |= _state_text_to_tags(ex.get("state") or "") & tags
        return matched

    entry_tags = set(loc.get("state_tags") or [])
    return entry_tags & tags


def _with_matched_examples(loc: dict, matched_tags: set, opportunities: set) -> dict:
    """
    Given an entry and the tags it matched, returns either the entry
    unchanged (no match, or no examples[] to narrow down) or a shallow
    copy carrying `_matched_examples` -- the specific example(s) whose
    own state overlaps the live tags. Shared by every card that renders
    farm entries, so a match always shows the same specific material(s)
    regardless of which card it's rendered in.
    """
    if not matched_tags or not isinstance(loc.get("examples"), list):
        return loc
    entry = dict(loc)
    entry["_matched_examples"] = [
        ex for ex in loc["examples"]
        if isinstance(ex, dict)
        and _state_text_to_tags(ex.get("state") or "") & opportunities
    ]
    return entry


def _build_nearby_farming_results(
    static_sites: list,
    coords_by_system: dict,
    live_rows: list,
    guide_records: list,
    material_filter: str,
    ref_x: float, ref_y: float, ref_z: float,
    limit: int = 50,
) -> list:
    """
    Combines static named-site matches and live BGS-state matches into
    one nearest-first, optionally material-filtered result list.

    static_sites: guide records with a "system" field.
    coords_by_system: {system_name_lower: (x, y, z)} for static_sites'
    systems.
    live_rows: raw rows from Repository.get_controlling_faction_snapshots_with_coords().
    guide_records: the full farming_locations._records list, matched
    against each live_row's derived tags.
    """
    def _dist(x, y, z):
        return ((x - ref_x) ** 2 + (y - ref_y) ** 2 + (z - ref_z) ** 2) ** 0.5

    mf = (material_filter or "").strip().lower()
    results = []

    for site in static_sites:
        sys_name = str(site.get("system") or "")
        coords = coords_by_system.get(sys_name.lower())
        if not coords:
            continue
        x, y, z = coords
        dist = _dist(x, y, z)
        materials = site.get("key_materials") or []
        examples = site.get("examples") or []
        mat_names = list(materials) if materials else [
            str(ex.get("material") or "") for ex in examples if isinstance(ex, dict)
        ]
        for mat in mat_names:
            if not mat:
                continue
            if mf and mf not in mat.lower():
                continue
            results.append({
                "material": mat,
                "site_name": str(site.get("name") or ""),
                "system_name": sys_name,
                "distance_ly": dist,
                "source": "static",
                "state": None,
            })

    for row in live_rows:
        x, y, z = row.get("x"), row.get("y"), row.get("z")
        if x is None or y is None or z is None:
            continue
        dist = _dist(x, y, z)
        tags = _tags_from_faction_snapshot_row(row)
        if not tags:
            continue
        for rec in guide_records:
            if not isinstance(rec, dict):
                continue
            matched_tags = _entry_matches_system(rec, tags)
            if not matched_tags:
                continue
            entry = _with_matched_examples(rec, matched_tags, tags)
            matched_examples = entry.get("_matched_examples")
            if matched_examples:
                mat_state_pairs = [
                    (str(ex.get("material") or ""), str(ex.get("state") or ""))
                    for ex in matched_examples
                ]
            else:
                mat_state_pairs = [
                    (mat, None) for mat in (rec.get("key_materials") or [])
                ]
            for mat, st in mat_state_pairs:
                if not mat:
                    continue
                if mf and mf not in mat.lower():
                    continue
                results.append({
                    "material": mat,
                    "site_name": str(rec.get("name") or ""),
                    "system_name": str(row.get("system_name") or ""),
                    "distance_ly": dist,
                    "source": "live",
                    "state": st,
                })

    results.sort(key=lambda r: r["distance_ly"])
    return results[:limit]


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
            "color: #7a7a7a; font-size:12px; font-weight: bold; "
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
            "color: #7a7a7a; font-size:12px; font-weight: bold; "
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

        # ── Body farming matches card ─────────────────────────────────────
        body_farm_frame = QFrame()
        body_farm_frame.setStyleSheet(
            "QFrame { background: #0d1a1a; border: 1px solid #1a3a3a;"
            "border-radius: 5px; }"
        )
        body_farm_l = QVBoxLayout(body_farm_frame)
        body_farm_l.setContentsMargins(8, 6, 8, 6)
        body_farm_l.setSpacing(4)
        body_farm_hdr = QLabel("SURFACE SCAN — FARMING MATCHES")
        body_farm_hdr.setStyleSheet(
            "color: #7a7a7a; font-size:12px; font-weight: bold; "
            "letter-spacing: 1px; background: transparent; border: none;"
        )
        body_farm_l.addWidget(body_farm_hdr)
        self.body_farm_display = QLabel("")
        self.body_farm_display.setWordWrap(True)
        self.body_farm_display.setTextFormat(Qt.TextFormat.RichText)
        self.body_farm_display.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.body_farm_display.setStyleSheet("background: transparent; border: none;")
        body_farm_l.addWidget(self.body_farm_display)
        self._content_layout.addWidget(body_farm_frame)

        # ── Odyssey farming candidates card ─────────────────────────────────
        odyssey_frame = QFrame()
        odyssey_frame.setStyleSheet(
            "QFrame { background: #1a0d1a; border: 1px solid #3a1e3a;"
            "border-radius: 5px; }"
        )
        odyssey_l = QVBoxLayout(odyssey_frame)
        odyssey_l.setContentsMargins(8, 6, 8, 6)
        odyssey_l.setSpacing(4)
        odyssey_hdr = QLabel("ODYSSEY FARMING CANDIDATES")
        odyssey_hdr.setStyleSheet(
            "color: #7a7a7a; font-size:12px; font-weight: bold; "
            "letter-spacing: 1px; background: transparent; border: none;"
        )
        odyssey_l.addWidget(odyssey_hdr)
        self.odyssey_display = QLabel("")
        self.odyssey_display.setWordWrap(True)
        self.odyssey_display.setTextFormat(Qt.TextFormat.RichText)
        self.odyssey_display.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.odyssey_display.setStyleSheet("background: transparent; border: none;")
        self.odyssey_display.setToolTip("Click a system name to copy it to the clipboard.")
        self.odyssey_display.linkActivated.connect(self._on_odyssey_link)
        odyssey_l.addWidget(self.odyssey_display)
        self._content_layout.addWidget(odyssey_frame)

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
            "color: #7a7a7a; font-size:12px; font-weight: bold; "
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

        # ── BGS history card ──────────────────────────────────────────────
        bgs_frame = QFrame()
        bgs_frame.setStyleSheet(
            "QFrame { background: #0d0d1a; border: 1px solid #2a2a4a;"
            "border-radius: 5px; }"
        )
        bgs_l = QVBoxLayout(bgs_frame)
        bgs_l.setContentsMargins(8, 6, 8, 6)
        bgs_l.setSpacing(4)
        bgs_hdr = QLabel("BGS HISTORY — THIS SYSTEM")
        bgs_hdr.setStyleSheet(
            "color: #7a7a7a; font-size:12px; font-weight: bold; "
            "letter-spacing: 1px; background: transparent; border: none;"
        )
        bgs_l.addWidget(bgs_hdr)
        self.bgs_display = QLabel("")
        self.bgs_display.setWordWrap(True)
        self.bgs_display.setTextFormat(Qt.TextFormat.RichText)
        self.bgs_display.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.bgs_display.setStyleSheet("background: transparent; border: none;")
        bgs_l.addWidget(self.bgs_display)
        self._content_layout.addWidget(bgs_frame)

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
            f'font-size:12px;font-weight:700;padding:1px 5px;'
            f'border-radius:3px;">{self._esc(domain.upper())}</span>'
        ) if domain else ""

        if highlight:
            line = (
                '<div style="margin-bottom:8px;padding:4px 8px;'
                'background:#1a2a00;border-left:3px solid #6BCB77;'
                'border-radius:4px;">'
                '<span style="color:#6BCB77;font-size:12px;'
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
                f' <span style="color:#4D96FF;font-size:12px;">'
                f'— {self._esc(system)}</span>'
            )
        if body:
            line += (
                f' <span style="color:#888888;font-size:12px;">'
                f'/ {self._esc(body)}</span>'
            )
        if method:
            line += (
                f'<br><span style="color:#6BCB77;font-size:12px;">'
                f'&nbsp;&nbsp;⚙ {self._esc(method)}</span>'
            )
        matched_examples = loc.get("_matched_examples") or []
        if matched_examples:
            for ex in matched_examples:
                mat = str(ex.get("material") or "")
                st = str(ex.get("state") or "")
                if not mat:
                    continue
                line += (
                    f'<br><span style="color:#FFD93D;font-size:12px;">'
                    f'&nbsp;&nbsp;⚡ {self._esc(mat)}'
                    + (f' — {self._esc(st)}' if st else '')
                    + '</span>'
                )
        if note:
            line += (
                f'<br><span style="color:#FFD93D;font-size:12px;">'
                f'&nbsp;&nbsp;📌 {self._esc(note)}</span>'
            )
        if mats:
            if isinstance(mats, list):
                mat_txt = ", ".join(str(m) for m in mats[:8])
            else:
                mat_txt = str(mats)
            line += (
                f'<br><span style="color:#FFD93D;font-size:12px;">'
                f'&nbsp;&nbsp;Mats: {self._esc(mat_txt)}</span>'
            )
        # Sites array — multiple system/body locations
        sites = loc.get("sites") or []
        if isinstance(sites, list) and sites:
            line += (
                '<br><span style="color:#7a7a7a;font-size:12px;">'
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
                        f' <span style="color:#7a7a7a;font-size:12px;">'
                        f'({self._esc(s_coords)})</span>'
                    )
                if isinstance(s_mats, list) and s_mats:
                    mat_str = ", ".join(str(m) for m in s_mats[:4])
                    site_line += (
                        f' <span style="color:#FFD93D;font-size:12px;">'
                        f'— {self._esc(mat_str)}</span>'
                    )
                if site_line:
                    line += (
                        f'<br><span style="font-size:12px;">'
                        f'&nbsp;&nbsp;&nbsp;&nbsp;• {site_line}</span>'
                    )

        line += '</div>'
        return line

    def _on_odyssey_link(self, link: str):
        if link.startswith("copy:"):
            QApplication.clipboard().setText(unquote(link[len("copy:"):]))

    def _odyssey_candidates_html(self, candidates):
        """Renders the Odyssey farming candidates list as rich-text rows."""
        if not candidates:
            return (
                '<span style="color:#444444;font-size:12px;">'
                'No tracked systems currently match — data comes from '
                'systems you’ve visited or refreshed.</span>'
            )

        rows = []
        for c in candidates:
            system_name = str(c.get("system_name") or "")
            signals = c.get("matched_signals") or []
            age_txt = self._format_age(c.get("data_timestamp"))

            badges = "".join(
                f'<span style="background:#2a1a2a;color:#C77DFF;'
                f'font-size:12px;font-weight:700;padding:1px 5px;'
                f'border-radius:3px;margin-right:4px;">{self._esc(sig)}</span>'
                for sig in signals
            )
            rows.append(
                '<div style="margin-bottom:6px;">'
                f'<a href="copy:{quote(system_name)}" '
                f'style="color:#CCCCCC;font-weight:700;text-decoration:none;">'
                f'{self._esc(system_name)}</a> '
                f'{badges}'
                + (
                    f'<br><span style="color:#7a7a7a;font-size:12px;">'
                    f'&nbsp;&nbsp;{self._esc(age_txt)}</span>'
                    if age_txt else ""
                )
                + '</div>'
            )
        return "".join(rows)

    def _format_age(self, data_timestamp):
        """Turns a normalized 'YYYY-MM-DDTHH:MM:SSZ' timestamp into a short
        human-readable age string, e.g. 'today', '3 days ago'. Returns ''
        for missing/unparseable input (legacy rows with no timestamp)."""
        if not data_timestamp:
            return ""
        from datetime import datetime, timezone
        try:
            dt = datetime.strptime(data_timestamp, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            return ""
        days = (datetime.now(timezone.utc) - dt).days
        if days <= 0:
            return "today"
        if days == 1:
            return "1 day ago"
        return f"{days} days ago"


    def refresh(self, state, farming_locations, faction_history=None, farming_candidates=None):
        sys_name = getattr(state, "system", None) or ""

        # ── BGS history ───────────────────────────────────────────────────
        history_html = []
        for rec in (faction_history or [])[:30]:
            if not isinstance(rec, dict):
                continue
            fname = self._esc(rec.get("faction_name") or "")
            fdate = self._esc(rec.get("snapshot_date") or "")
            infl = rec.get("influence")
            infl_txt = f"{float(infl) * 100:.1f}%" if isinstance(infl, (int, float)) else "?"
            fstate = self._esc(rec.get("faction_state") or "")
            ctrl_badge = (
                ' <span style="color:#6BCB77;font-size:12px;">★ controlling</span>'
                if rec.get("is_controlling") else ""
            )
            history_html.append(
                f'<div style="margin-bottom:4px;">'
                f'<span style="color:#888888;font-size:12px;">{fdate}</span> '
                f'<span style="color:#CCCCCC;font-weight:700;">{fname}</span> '
                f'<span style="color:#FFB347;">{infl_txt}</span>'
                + (f' <span style="color:#4D96FF;font-size:12px;">[{fstate}]</span>' if fstate else "")
                + ctrl_badge
                + '</div>'
            )

        self.bgs_display.setText(
            "".join(history_html) if history_html else
            '<span style="color:#444444;font-size:12px;">'
            'No BGS history recorded for this system yet — '
            'history accumulates one snapshot per faction per day as you visit.'
            '</span>'
        )

        # ── Odyssey farming candidates ───────────────────────────────────
        self.odyssey_display.setText(
            self._odyssey_candidates_html(farming_candidates or [])
        )

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
                f'font-size:12px;font-weight:700;padding:1px 5px;'
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
                    f'<br><span style="color:#FFD93D;font-size:12px;">'
                    f'&nbsp;&nbsp;📌 {self._esc(note)}</span>'
                )
            if source:
                line += (
                    f'<br><span style="color:#7a7a7a;font-size:12px;">'
                    f'&nbsp;&nbsp;src: {self._esc(source)}</span>'
                )
            line += '</div>'
            poi_html.append(line)

        self.poi_display.setText(
            "".join(poi_html) if poi_html else
            '<span style="color:#444444;font-size:12px;">'
            'No external POIs for this system.<br>'
            'Add POIs to <code>settings/external_pois.json</code> '
            'to see them here.</span>'
        )

        # ── System-specific farming ───────────────────────────────────────
        farm_entries = []
        if farming_locations:
            try:
                all_records = getattr(farming_locations, "_records", []) or []
                opportunities = _get_system_opportunities(state)
                # Exact system name matches
                by_system = farming_locations.get_for_system(sys_name) if sys_name else []
                seen_ids = {id(r) for r in by_system}
                # State-tag matches (boom/war/outbreak etc.) -- entries
                # with an examples[] list only show the specific
                # example(s) whose own state is actually live, not the
                # whole entry.
                state_matches = []
                for r in all_records:
                    if not isinstance(r, dict) or id(r) in seen_ids:
                        continue
                    matched_tags = _entry_matches_system(r, opportunities)
                    if not matched_tags:
                        continue
                    state_matches.append(_with_matched_examples(r, matched_tags, opportunities))
                farm_entries = by_system + state_matches
            except Exception:
                farm_entries = []

        farm_html = [self._farm_entry_html(loc) for loc in farm_entries
                     if isinstance(loc, dict)]

        self.farming_display.setText(
            "".join(farm_html) if farm_html else
            '<span style="color:#444444;font-size:12px;">'
            'No specific farming locations for this system.<br>'
            'Browse the full guide below.</span>'
        )

        # ── Body farming matches (surface scan cross-reference) ───────────
        body_farm_html = []
        n_body_farm_matches = 0
        if farming_locations:
            try:
                all_records = getattr(farming_locations, "_records", []) or []
                guardian_entries = [r for r in all_records if isinstance(r, dict) and r.get("domain") == "guardian"]
                thargoid_entries = [r for r in all_records if isinstance(r, dict) and r.get("domain") == "thargoid"]

                # Guide entries actually IN this system -- guardian_entries
                # above stays global (needed for the "is this system in the
                # guide at all" check below); the per-body display must only
                # ever show sites that are actually here, not just the first
                # N entries of the whole guide. Thargoid entries are excluded
                # from this: confirmed (settings/elite_farming_locations.json)
                # they carry no "system" field at all -- they're generic
                # advisory reference material (e.g. "Scout NHSS"), not
                # location-pinned sites, so thargoid_entries stays global too.
                sys_entries = farming_locations.get_for_system(sys_name)
                guardian_sys_entries = [r for r in sys_entries if r.get("domain") == "guardian"]
                onfoot_sys_entries   = [r for r in sys_entries if r.get("domain") == "odyssey_onfoot"]

                # Known systems for each domain (for new-site detection)
                known_guardian_systems = {
                    str(r.get("system") or "").lower()
                    for r in guardian_entries if r.get("system")
                }
                known_thargoid_systems = {
                    str(r.get("system") or "").lower()
                    for r in thargoid_entries if r.get("system")
                }
                current_sys_lower = sys_name.lower()

                bodies           = getattr(state, "bodies", {}) or {}
                human_signals    = getattr(state, "human_signals", {}) or {}
                guardian_signals = getattr(state, "guardian_signals", {}) or {}
                thargoid_signals = getattr(state, "thargoid_signals", {}) or {}

                for body_name, rec in bodies.items():
                    if not isinstance(rec, dict):
                        continue

                    h_sig = int(human_signals.get(body_name, 0) or 0)
                    g_sig = int(guardian_signals.get(body_name, 0) or 0)
                    t_sig = int(thargoid_signals.get(body_name, 0) or 0)

                    # Deliberately NOT matching on this body's own raw surface
                    # composition (e.g. Zirconium, Selenium) against the guide's
                    # material lists — those are common G1-G4 raws present on
                    # huge numbers of landable bodies, so a name-only overlap
                    # with a specific known site elsewhere (a wreck, a shard
                    # field) told you nothing about this system and just read
                    # as if that site were here. Only an actual detected
                    # anomaly signal on this body is a genuine "match".
                    if h_sig == 0 and g_sig == 0 and t_sig == 0:
                        continue

                    n_body_farm_matches += 1

                    # Pick border colour: thargoid > guardian > human > material
                    border = "#FF6B6B" if t_sig else ("#FF8888" if g_sig else ("#FFD93D" if h_sig else "#2AFFCC"))
                    body_farm_html.append(
                        f'<div style="margin-bottom:8px;padding:4px 8px;'
                        f'background:#0a1a1a;border-left:3px solid {border};'
                        f'border-radius:4px;">'
                        f'<span style="color:{border};font-size:12px;font-weight:700;">'
                        f'{self._esc(body_name)}</span>'
                    )

                    if t_sig > 0:
                        fg_t, _ = self._domain_color("thargoid")
                        # Thargoid guide has no fixed systems — can't distinguish known vs new
                        # so just surface the guide entries as reference
                        body_farm_html.append(
                            f'<br><span style="color:#FF6B6B;font-size:12px;">'
                            f'&nbsp;&nbsp;☣ {t_sig} thargoid signal(s)'
                            f'</span>'
                        )
                        for fm in thargoid_entries[:3]:
                            name = str(fm.get("name") or "")
                            body_farm_html.append(
                                f'<br><span style="color:{fg_t};font-size:12px;">'
                                f'&nbsp;&nbsp;⛏ {self._esc(name)}</span>'
                            )

                    if g_sig > 0:
                        fg_g, _ = self._domain_color("guardian")
                        # Guardian guide has specific known systems — flag if this is a new one
                        if known_guardian_systems and current_sys_lower not in known_guardian_systems:
                            body_farm_html.append(
                                f'<br><span style="color:#FF8888;font-weight:700;font-size:12px;">'
                                f'&nbsp;&nbsp;🔺 {g_sig} guardian signal(s) — POTENTIALLY UNDISCOVERED SITE'
                                f'</span>'
                                f'<br><span style="color:#888888;font-size:12px;">'
                                f'&nbsp;&nbsp;Not in farming guide — consider logging and reporting'
                                f'</span>'
                            )
                        else:
                            body_farm_html.append(
                                f'<br><span style="color:#FF8888;font-size:12px;">'
                                f'&nbsp;&nbsp;🔺 {g_sig} guardian signal(s)'
                                f'</span>'
                            )
                        for fm in guardian_sys_entries[:3]:
                            name = str(fm.get("name") or "")
                            body_farm_html.append(
                                f'<br><span style="color:{fg_g};font-size:12px;">'
                                f'&nbsp;&nbsp;⛏ {self._esc(name)}</span>'
                            )

                    if h_sig > 0:
                        body_farm_html.append(
                            f'<br><span style="color:#FFD93D;font-size:12px;">'
                            f'&nbsp;&nbsp;⚠ {h_sig} human signal(s) — possible installation or crash site'
                            f'</span>'
                        )
                        for fm in onfoot_sys_entries[:2]:
                            name = str(fm.get("name") or "")
                            fg, _ = self._domain_color("odyssey_onfoot")
                            body_farm_html.append(
                                f'<br><span style="color:{fg};font-size:12px;">'
                                f'&nbsp;&nbsp;⛏ {self._esc(name)}</span>'
                            )

                    body_farm_html.append('</div>')
            except Exception:
                log.exception("Body farming match error")

        self.body_farm_display.setText(
            "".join(body_farm_html) if body_farm_html else
            '<span style="color:#444444;font-size:12px;">'
            'No surface scan farming matches yet.<br>'
            'Perform a DSS scan to cross-reference body materials.</span>'
        )

        # ── Full farming guide ────────────────────────────────────────────
        guide_html = []
        if farming_locations:
            try:
                all_records = getattr(farming_locations, "_records", []) or []
                opportunities = _get_system_opportunities(state)
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
                        f'font-size:12px;letter-spacing:1px;">'
                        f'{self._esc(label)}</span>'
                        f'<span style="color:#7a7a7a;font-size:12px;">'
                        f' ({len(entries)} entries)</span>'
                        f'</div>'
                    )
                    for loc in entries:
                        matched_tags = _entry_matches_system(
                            loc, opportunities
                        )
                        entry = _with_matched_examples(loc, matched_tags, opportunities)
                        guide_html.append(
                            self._farm_entry_html(entry, highlight=bool(matched_tags))
                        )

            except Exception:
                guide_html = []

        self.guide_display.setText(
            "".join(guide_html) if guide_html else
            '<span style="color:#444444;font-size:12px;">'
            'No farming guide loaded.<br>'
            'Check <code>settings/elite_farming_locations.json</code>.'
            '</span>'
        )

        # ── Summary ───────────────────────────────────────────────────────
        n_poi  = len(pois)
        n_farm = len(farm_entries)
        n_body_farm = n_body_farm_matches
        if n_poi == 0 and n_farm == 0 and n_body_farm == 0:
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
            if n_body_farm:
                parts.append(
                    f"{n_body_farm} body farming match{'es' if n_body_farm != 1 else ''}"
                )
            self.intel_summary.setText(
                "Intel (External, advisory only) — "
                + " | ".join(parts)
            )
