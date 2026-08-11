import logging
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTextEdit,
    QScrollArea,
    QFrame,
    QSizePolicy,
    QPushButton,
)
from PyQt6.QtCore import Qt, pyqtSignal

from edc.ui import formatting as fmt

log = logging.getLogger(__name__)


class ExplorationPanel(QWidget):
    """
    Inara-inspired Exploration tab.
    Shows system signals, body cards, and materials shortlist.
    Receives state, cfg, and planet_values via refresh().
    Emits min_value_changed(str) for the Settings tab slider label.
    """

    min_value_changed = pyqtSignal(str)
    body_clicked = pyqtSignal(str)

    # Rare raw materials to highlight
    RARE = {
        "polonium", "tellurium", "ruthenium", "yttrium",
        "antimony", "arsenic", "selenium", "zirconium",
        "niobium", "tin", "molybdenum", "technetium",
    }

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

        self.exploration_action = QLabel("")
        self.exploration_action.setWordWrap(True)
        hdr_l.addWidget(self.exploration_action)

        self.exploration_hint = QLabel("")
        self.exploration_hint.setWordWrap(True)
        hdr_l.addWidget(self.exploration_hint)

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

        # ── Signals box (always visible at top) ───────────────────────────
        sig_frame = QFrame()
        sig_frame.setStyleSheet(
            "QFrame { background: #0d1a2a; border: 1px solid #1e3a5a;"
            "border-radius: 5px; }"
        )
        sig_l = QVBoxLayout(sig_frame)
        sig_l.setContentsMargins(8, 6, 8, 6)
        sig_l.setSpacing(2)
        self._signals_expanded = True
        self._signals_summary_html = ""
        self._signals_full_html = ""

        sig_hdr_row = QHBoxLayout()
        sig_hdr_lbl = QLabel("SYSTEM SIGNALS (FSS)")
        sig_hdr_lbl.setStyleSheet(
            "color: #7a7a7a; font-size:12px; font-weight: bold; "
            "letter-spacing: 1px; background: transparent; border: none;"
        )
        self._sig_toggle_btn = QPushButton("Show detail ▼")
        self._sig_toggle_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; "
            "color: #FFB347; font-size:12px; padding: 0px; }"
            "QPushButton:hover { color: #FF8C00; }"
        )
        self._sig_toggle_btn.setVisible(False)
        self._sig_toggle_btn.clicked.connect(self._toggle_signals)
        sig_hdr_row.addWidget(sig_hdr_lbl)
        sig_hdr_row.addStretch()
        sig_hdr_row.addWidget(self._sig_toggle_btn)

        self.system_signals_box = QLabel("")
        self.system_signals_box.setWordWrap(True)
        self.system_signals_box.setTextFormat(Qt.TextFormat.RichText)
        self.system_signals_box.setStyleSheet("background: transparent; border: none;")
        sig_l.addLayout(sig_hdr_row)
        sig_l.addWidget(self.system_signals_box)
        self._content_layout.addWidget(sig_frame)

        # ── Rings box (which bodies have rings, scan status, hotspots) ─────
        rings_frame = QFrame()
        rings_frame.setStyleSheet(
            "QFrame { background: #0d1a2a; border: 1px solid #1e3a5a;"
            "border-radius: 5px; }"
        )
        rings_l = QVBoxLayout(rings_frame)
        rings_l.setContentsMargins(8, 6, 8, 6)
        rings_l.setSpacing(2)
        rings_hdr = QLabel("RINGS IN THIS SYSTEM")
        rings_hdr.setStyleSheet(
            "color: #7a7a7a; font-size:12px; font-weight: bold; "
            "letter-spacing: 1px; background: transparent; border: none;"
        )
        self.rings_box = QLabel("")
        self.rings_box.setWordWrap(True)
        self.rings_box.setTextFormat(Qt.TextFormat.RichText)
        self.rings_box.setStyleSheet("background: transparent; border: none;")
        rings_l.addWidget(rings_hdr)
        rings_l.addWidget(self.rings_box)
        self._rings_frame = rings_frame
        self._rings_frame.setVisible(False)
        self._content_layout.addWidget(rings_frame)

        # ── Bodies section label ──────────────────────────────────────────
        self._bodies_label = QLabel("SCANNED BODIES")
        self._bodies_label.setStyleSheet(
            "color: #7a7a7a; font-size:12px; font-weight: bold;"
            "letter-spacing: 1px; padding: 4px 0px 2px 2px;"
        )
        self._content_layout.addWidget(self._bodies_label)

        # ── Body cards container ──────────────────────────────────────────
        self._cards_widget = QWidget()
        self._cards_widget.setStyleSheet("background: transparent;")
        self._cards_layout = QVBoxLayout(self._cards_widget)
        self._cards_layout.setSpacing(5)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.addWidget(self._cards_widget)
        # body_name -> (card widget, the exact _build_body_card args that
        # produced it) — lets refresh reuse/reposition an unchanged card
        # instead of destroying and recreating every card on every
        # refresh. That full teardown-rebuild (previously: clear the whole
        # layout, then rebuild from scratch) is what caused a visible
        # empty-then-repopulated flicker during an active FSS scan,
        # confirmed live: the card borders stayed but the text inside
        # blanked out, repeatedly, once per newly-discovered body.
        self._body_cards: dict = {}

        # ── Materials shortlist ───────────────────────────────────────────
        mat_frame = QFrame()
        mat_frame.setStyleSheet(
            "QFrame { background: #0d1a1a; border: 1px solid #1e3a2a;"
            "border-radius: 5px; }"
        )
        mat_l = QVBoxLayout(mat_frame)
        mat_l.setContentsMargins(8, 6, 8, 6)
        mat_l.setSpacing(2)
        mat_hdr = QLabel("MATERIALS SHORTLIST (landable + Geo signals)")
        mat_hdr.setStyleSheet(
            "color: #7a7a7a; font-size:12px; font-weight: bold; "
            "letter-spacing: 1px; background: transparent; border: none;"
        )
        self.materials_box = QLabel("")
        self.materials_box.setWordWrap(True)
        self.materials_box.setTextFormat(Qt.TextFormat.RichText)
        self.materials_box.setStyleSheet("background: transparent; border: none;")
        mat_l.addWidget(mat_hdr)
        mat_l.addWidget(self.materials_box)
        self._content_layout.addWidget(mat_frame)

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _norm_token(self, val):
        if not isinstance(val, str):
            return ""
        return (
            val.replace("$", "").replace(";", "")
            .replace("_", " ").strip().title()
        )

    def _esc(self, t):
        return str(t or "").replace(
            "&", "&amp;"
        ).replace("<", "&lt;").replace(">", "&gt;")

    def _badge(self, text, bg="#2a2a3a", fg="#AAAAAA", bold=False):
        fw = "font-weight:700;" if bold else ""
        return (
            f'<span style="background:{bg};color:{fg};{fw}'
            f'font-size:12px;padding:1px 5px;border-radius:3px;">'
            f'{self._esc(text)}</span>'
        )

    # ── Main refresh ──────────────────────────────────────────────────────────
    def refresh(self, state, cfg, planet_values, spansh_rings=None):
        try:
            min_100k = int(getattr(cfg, "min_planet_value_100k", 5) or 5)
        except Exception:
            min_100k = 10
        if min_100k < 0:
            min_100k = 0
        min_value = min_100k * 100_000
        self.min_value_changed.emit(f"{min_100k / 10:.1f}M")

        self._refresh_signals(state)
        self._refresh_rings(state, spansh_rings)
        self._refresh_bodies(state, min_value, planet_values)
        self._refresh_materials(state)

    # ── Rings box ─────────────────────────────────────────────────────────────
    def _refresh_rings(self, state, spansh_rings=None):
        system_address = getattr(state, "system_address", None)
        all_rings = getattr(state, "rings", None) or {}

        # Personal/persisted data (this commander's own scans) is the base —
        # merge in Spansh's community data on top: rings Spansh knows about
        # that we've never even scanned ourselves get added (so a ring known
        # only from other commanders' uploads still shows up), and rings we
        # haven't personally scanned get the community's hotspot data
        # attached for reference.
        merged: dict = {}
        for name, rec in all_rings.items():
            if isinstance(rec, dict) and rec.get("system_address") == system_address:
                merged[name] = dict(rec)

        for r in (spansh_rings or []):
            if not isinstance(r, dict) or not r.get("ring_name"):
                continue
            name = r["ring_name"]
            if name not in merged:
                merged[name] = {
                    "parent_body": r.get("parent_body"),
                    "ring_class": "",
                    "distance_ls": None,
                    "scanned": False,
                    "hotspots": [],
                }
            merged[name]["community_signals"] = r.get("signals") or []

        if not merged:
            self._rings_frame.setVisible(False)
            return

        rings = list(merged.items())

        def _dist(item):
            d = item[1].get("distance_ls")
            return d if isinstance(d, (int, float)) else float("inf")

        rings.sort(key=_dist)

        closest_unscanned = next((name for name, rec in rings if not rec.get("scanned")), None)

        lines = []
        for name, rec in rings:
            dist = rec.get("distance_ls")
            dist_txt = f"{dist:,.0f} ls" if isinstance(dist, (int, float)) else "? ls"
            ring_class = self._norm_token(rec.get("ring_class") or "")

            if rec.get("scanned"):
                hotspots = rec.get("hotspots") or []
                if hotspots:
                    hs_txt = ", ".join(f"{h.get('name')} x{h.get('count')}" for h in hotspots)
                    status = f'<span style="color:#6BCB77;">✅ {self._esc(hs_txt)}</span>'
                else:
                    status = '<span style="color:#888888;">✅ Scanned — no hotspots</span>'
            else:
                marker = " 👉 CLOSEST UNSCANNED" if name == closest_unscanned else ""
                community = rec.get("community_signals") or []
                if community:
                    cs_txt = ", ".join(f"{h.get('name')} x{h.get('count')}" for h in community)
                    status = (
                        f'<span style="color:#4D96FF;">🌐 Community: {self._esc(cs_txt)} '
                        f'(not scanned by you){marker}</span>'
                    )
                else:
                    color = "#FFD93D" if name == closest_unscanned else "#888888"
                    status = (
                        f'<span style="color:{color};">❗ Missing everywhere — '
                        f'DSS it to be first to report{marker}</span>'
                    )

            lines.append(
                f'💍 {self._esc(name)} ({self._esc(ring_class)}) — {dist_txt} — {status}'
            )

        self.rings_box.setText("<br>".join(lines))
        self._rings_frame.setVisible(True)

    # ── Signals box ───────────────────────────────────────────────────────────
    def _refresh_signals(self, state):
        sigs = getattr(state, "system_signals", None) or []

        if not isinstance(sigs, list) or not sigs:
            # Show body count hint instead
            total    = getattr(state, "system_body_count", None)
            resolved = len(getattr(state, "resolved_body_ids", set()) or set())
            fss_done = getattr(state, "fss_complete", False)
            if isinstance(total, int) and total > 0:
                if fss_done:
                    self.system_signals_box.setText(
                        f'<span style="color:#6BCB77;">All {total} bodies discovered</span>'
                    )
                else:
                    remaining = max(0, total - resolved)
                    self.system_signals_box.setText(
                        f'<span style="color:#AAAAAA;">'
                        f'Bodies resolved: {resolved}/{total} '
                        f'— {remaining} remaining. Use FSS to discover.</span>'
                    )
            else:
                self.system_signals_box.setText(
                    '<span style="color:#444444;">No signals discovered yet. Honk to start.</span>'
                )
            return

        cat_order  = ["Phenomena", "Megaship", "Station", "Installation",
                      "NavBeacon", "TouristBeacon", "USS", "Wreckage", "Other"]
        hidden     = {"FleetCarrier"}
        cats       = {k: [] for k in cat_order}
        cat_counts = {k: 0 for k in cat_order}
        uss_counts = {}

        for s in sigs:
            if not isinstance(s, dict):
                continue
            cat_raw = s.get("Category") if isinstance(s.get("Category"), str) else "Other"
            if cat_raw in hidden:
                continue
            cat = self._norm_token(cat_raw) or "Other"
            if cat not in cats:
                cat = "Other"
            cats[cat].append(s)
            cat_counts[cat] += 1
            if cat == "USS":
                u = self._norm_token(s.get("USSType") or "")
                if u:
                    uss_counts[u] = uss_counts.get(u, 0) + 1

        # Summary line
        summary_parts = []
        for k in cat_order:
            if cat_counts.get(k, 0):
                summary_parts.append(
                    f'<span style="color:#4D96FF;font-weight:700;">{k}</span>'
                    f'&nbsp;<span style="color:#CCCCCC;">x{cat_counts[k]}</span>'
                )

        html = []
        if summary_parts:
            html.append(" &nbsp;|&nbsp; ".join(summary_parts))

        # Detail lines per category — max 3 per cat to avoid crowding
        for cat in cat_order:
            if not cats[cat]:
                continue
            cat_suffix = (
                f' <span style="color:#444444;font-size:11px;">'
                f'— scan skimmers first, attack only if Wanted</span>'
                if cat == "Wreckage" else ""
            )
            html.append(
                f'<br><span style="color:#7a7a7a;font-size:12px;">'
                f'{cat.upper()}</span>{cat_suffix}'
            )
            shown_in_cat = 0
            for s in cats[cat]:
                shown_in_cat += 1
                nm    = self._norm_token(s.get("SignalName") or "Signal") or "Signal"
                stype = self._norm_token(s.get("SignalType") or "")
                uss   = self._norm_token(s.get("USSType") or "")
                tl    = s.get("ThreatLevel")
                tr    = s.get("TimeRemaining")
                bits  = [f'<span style="color:#CCCCCC;">{self._esc(nm)}</span>']
                if cat == "USS" and uss:
                    bits.append(f'<span style="color:#888888;">({self._esc(uss)})</span>')
                if cat == "Other" and stype:
                    bits.append(f'<span style="color:#888888;">[{self._esc(stype)}]</span>')
                if isinstance(tl, int):
                    bits.append(f'<span style="color:#FF6B6B;">Threat {tl}</span>')
                if isinstance(tr, (int, float)):
                    bits.append(f'<span style="color:#888888;">TR {int(tr)}s</span>')
                html.append(" ".join(bits))
            pass

        # Summary only — first line
        self._signals_summary_html = html[0] if html else ""
        self._signals_full_html    = "<br>".join(html)

        # Default to expanded, show full detail
        self._signals_expanded = True
        self._sig_toggle_btn.setText("Hide detail ▲")

        self.system_signals_box.setText(self._signals_full_html)

        # Show toggle button only if there is detail beyond summary
        has_detail = len(html) > 1
        self._sig_toggle_btn.setVisible(has_detail)


    def _toggle_signals(self):
        self._signals_expanded = not self._signals_expanded
        if self._signals_expanded:
            self.system_signals_box.setText(self._signals_full_html)
            self._sig_toggle_btn.setText("Hide detail ▲")
        else:
            self.system_signals_box.setText(self._signals_summary_html)
            self._sig_toggle_btn.setText("Show detail ▼")

    # ── Body cards ────────────────────────────────────────────────────────────
    def _refresh_bodies(self, state, min_value, planet_values):
        if not state.bodies:
            for card, _sig in self._body_cards.values():
                card.deleteLater()
            self._body_cards.clear()
            self._bodies_label.setVisible(False)
            self.exploration_action.setText(
                "🌍 Exploration: no bodies resolved yet — "
                "use FSS / honk / nav beacon"
            )
            self.exploration_hint.setText("")
            return

        self._bodies_label.setVisible(True)

        # Sort bodies by estimated value descending
        body_items = []
        for body, rec in state.bodies.items():
            if not isinstance(rec, dict):
                continue
            est = rec.get("EstimatedValue")
            sort_val = int(est) if isinstance(est, int) else 0
            body_items.append((sort_val, body, rec))
        body_items.sort(key=lambda x: x[0], reverse=True)

        bio_bodies   = 0
        geo_bodies   = 0
        tf_unmapped  = 0
        hv_unmapped  = 0
        shown        = 0
        seen_bodies  = set()

        for sort_val, body, rec in body_items:
            est        = rec.get("EstimatedValue")
            dist       = rec.get("DistanceLS")
            pc         = rec.get("PlanetClass") or ""
            pc_disp    = self._norm_token(pc) or pc
            tf         = rec.get("Terraformable", False)
            was_mapped = bool(rec.get("WasMapped", False))
            dss_mapped = bool(rec.get("DSSMapped", False)) or bool(rec.get("BioGenuses"))
            first      = rec.get("FirstDiscovered", False)
            bio       = rec.get("BioSignals",      0) or 0
            geo       = rec.get("GeoSignals",      0) or 0
            human     = rec.get("HumanSignals",    0) or 0
            guardian  = rec.get("GuardianSignals", 0) or 0
            thargoid  = rec.get("ThargoidSignals", 0) or 0
            other_sig = rec.get("OtherSignals",    0) or 0
            genuses   = rec.get("BioGenuses", []) or []
            landable      = rec.get("Landable", False)
            volcanism     = rec.get("Volcanism") or ""
            materials     = rec.get("Materials") or {}
            first_footfall = bool(rec.get("FirstFootfall", False))
            has_footfall   = bool(rec.get("HasFootfall", False))

            if isinstance(bio, int) and bio > 0:
                bio_bodies += 1
            if isinstance(geo, int) and geo > 0:
                geo_bodies += 1
            if tf and not dss_mapped:
                tf_unmapped += 1
            if isinstance(est, int) and est >= min_value and not dss_mapped:
                hv_unmapped += 1

            shown += 1
            signature = (
                body, pc_disp, dist, est, tf, was_mapped, dss_mapped,
                first, bio, geo, human, guardian, thargoid, other_sig,
                genuses, landable, volcanism, materials, min_value,
                first_footfall, has_footfall,
            )
            existing = self._body_cards.get(body)
            if existing is not None and existing[1] == signature:
                card = existing[0]
            else:
                if existing is not None:
                    existing[0].deleteLater()
                card = self._build_body_card(*signature)
                self._body_cards[body] = (card, signature)
            # addWidget on a widget already in this layout just repositions
            # it (no destroy/recreate) — this is what keeps an unchanged
            # card from ever flickering, even as new cards get inserted
            # around it and the sort order shifts.
            self._cards_layout.addWidget(card)
            seen_bodies.add(body)

        for stale_body in set(self._body_cards) - seen_bodies:
            self._body_cards.pop(stale_body)[0].deleteLater()

        self.exploration_action.setText(
            f"🌍 Exploration: {shown} bodies • "
            f"{bio_bodies} with bio • {geo_bodies} with geo • "
            f"{tf_unmapped} TF unmapped • {hv_unmapped} high-value unmapped"
        )

        total       = getattr(state, "system_body_count", None)
        personally_scanned = len(getattr(state, "resolved_body_ids", set()) or set())
        scanned     = len(state.bodies)
        if isinstance(total, int) and total > 0:
            unknown = max(0, total - scanned)
            self.exploration_hint.setText(
                f"Bodies: {scanned}/{total} known "
                f"({personally_scanned} scanned by you) — {unknown} unknown"
            )
        else:
            self.exploration_hint.setText(
                f"Bodies: {scanned} known (honk for total count)"
            )

    def _build_body_card(
        self, body, pc_disp, dist, est, tf, was_mapped, dss_mapped,
        first, bio, geo, human, guardian, thargoid, other_sig,
        genuses, landable, volcanism, materials, min_value,
        first_footfall=False, has_footfall=False
    ):
        esc = self._esc

        # Card border colour based on value/interest
        if isinstance(est, int) and est >= min_value and not dss_mapped:
            border_color = "#4D96FF"
            bg_color     = "#0a1520"
        elif bio and bio > 0:
            border_color = "#6BCB77"
            bg_color     = "#0a1a0a"
        elif geo and geo > 0:
            border_color = "#FFB347"
            bg_color     = "#1a1200"
        elif tf and not dss_mapped:
            border_color = "#C77DFF"
            bg_color     = "#120a1a"
        else:
            border_color = "#1e2a3a"
            bg_color     = "#0d1015"

        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background: {bg_color}; border: 1px solid {border_color};"
            f"border-radius: 5px; }}"
        )
        card_l = QVBoxLayout(card)
        card_l.setContentsMargins(10, 7, 10, 7)
        card_l.setSpacing(4)

        # ── Header row ────────────────────────────────────────────────────
        hdr_row = QHBoxLayout()
        hdr_row.setSpacing(6)

        name_btn = QPushButton(body)
        name_btn.setFlat(True)
        name_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; "
            f"color: {border_color}; font-weight: 700; font-size: 12px; "
            f"text-align: left; padding: 0px; }}"
            f"QPushButton:hover {{ color: #FFFFFF; text-decoration: underline; }}"
        )
        name_btn.clicked.connect(lambda checked=False, b=body: self.body_clicked.emit(b))
        hdr_row.addWidget(name_btn)

        if pc_disp:
            pc_lbl = QLabel(f"- {esc(pc_disp)}")
            pc_lbl.setStyleSheet(
                "color: #888888; font-size:12px; background: transparent; border: none;"
            )
            hdr_row.addWidget(pc_lbl)

        hdr_row.addStretch(1)

        # Badges top right
        badges = []
        if landable:
            badges.append(self._badge("Landable", "#1a3a1a", "#6BCB77", bold=True))
        if tf:
            badges.append(self._badge("Terraformable", "#2a1a3a", "#C77DFF", bold=True))
        if first:
            badges.append(self._badge("First Discovery", "#2a1a00", "#FFB347", bold=True))
        if dss_mapped:
            badges.append(self._badge("DSS Mapped", "#1a2a3a", "#4D96FF"))
        elif was_mapped:
            badges.append(self._badge("Prev Mapped", "#1a1a2a", "#888888"))

        if first_footfall:
            badges.append(self._badge("First Footfall", "#2a1500", "#FFD700", bold=True))
        elif has_footfall:
            badges.append(self._badge("Footfall", "#1a1a1a", "#AAAAAA"))

        if badges:
            badge_lbl = QLabel(" ".join(badges))
            badge_lbl.setTextFormat(Qt.TextFormat.RichText)
            badge_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            badge_lbl.setStyleSheet("background: transparent; border: none;")
            hdr_row.addWidget(badge_lbl)

        card_l.addLayout(hdr_row)

        # ── Info row ──────────────────────────────────────────────────────
        info_html = []

        dist_txt = (
            fmt.int_commas(dist) + " Ls"
            if isinstance(dist, (int, float)) else ""
        )
        est_txt = fmt.credits(est, default="?") if isinstance(est, int) else ""

        if dist_txt:
            info_html.append(
                f'<span style="color:#7a7a7a;font-size:12px;">DISTANCE</span>'
                f'&nbsp;<span style="color:#CCCCCC;font-size:12px;">{esc(dist_txt)}</span>'
            )
        if est_txt:
            val_color = "#FFB347" if isinstance(est, int) and est >= min_value else "#AAAAAA"
            info_html.append(
                f'<span style="color:#7a7a7a;font-size:12px;">EST. VALUE</span>'
                f'&nbsp;<span style="color:{val_color};font-size:12px;font-weight:700;">'
                f'{esc(est_txt)}</span>'
            )
        if isinstance(bio, int) and bio > 0:
            info_html.append(
                f'<span style="color:#7a7a7a;font-size:12px;">BIO</span>'
                f'&nbsp;<span style="color:#6BCB77;font-size:12px;font-weight:700;">'
                f'{bio}</span>'
            )
        if isinstance(geo, int) and geo > 0:
            info_html.append(
                f'<span style="color:#7a7a7a;font-size:12px;">GEO</span>'
                f'&nbsp;<span style="color:#FFB347;font-size:12px;font-weight:700;">'
                f'{geo}</span>'
            )
        if isinstance(human, int) and human > 0:
            info_html.append(
                f'<span style="color:#7a7a7a;font-size:12px;">HUMAN</span>'
                f'&nbsp;<span style="color:#4D96FF;font-size:12px;font-weight:700;">'
                f'{human}</span>'
            )
        if isinstance(guardian, int) and guardian > 0:
            info_html.append(
                f'<span style="color:#7a7a7a;font-size:12px;">GUARDIAN</span>'
                f'&nbsp;<span style="color:#C77DFF;font-size:12px;font-weight:700;">'
                f'{guardian}</span>'
            )
        if isinstance(thargoid, int) and thargoid > 0:
            info_html.append(
                f'<span style="color:#7a7a7a;font-size:12px;">THARGOID</span>'
                f'&nbsp;<span style="color:#FF6B6B;font-size:12px;font-weight:700;">'
                f'{thargoid}</span>'
            )
        if isinstance(other_sig, int) and other_sig > 0:
            info_html.append(
                f'<span style="color:#7a7a7a;font-size:12px;">OTHER</span>'
                f'&nbsp;<span style="color:#AAAAAA;font-size:12px;font-weight:700;">'
                f'{other_sig}</span>'
            )
        if volcanism and "no volcanism" not in volcanism.lower():
            info_html.append(
                f'<span style="color:#7a7a7a;font-size:12px;">VOLCANISM</span>'
                f'&nbsp;<span style="color:#FF8888;font-size:12px;">'
                f'{esc(volcanism.strip())}</span>'
            )

        if info_html:
            info_lbl = QLabel(" &nbsp;&nbsp; ".join(info_html))
            info_lbl.setTextFormat(Qt.TextFormat.RichText)
            info_lbl.setWordWrap(True)
            info_lbl.setStyleSheet("background: transparent; border: none;")
            card_l.addWidget(info_lbl)

        # ── Bio genuses ───────────────────────────────────────────────────
        if isinstance(genuses, list) and genuses:
            genus_badges = " ".join(
                self._badge(str(g), "#1a2a1a", "#6BCB77")
                for g in genuses if g
            )
            genus_lbl = QLabel(genus_badges)
            genus_lbl.setTextFormat(Qt.TextFormat.RichText)
            genus_lbl.setWordWrap(True)
            genus_lbl.setStyleSheet("background: transparent; border: none;")
            card_l.addWidget(genus_lbl)

        # ── Materials row (landable only) ─────────────────────────────────
        if landable and isinstance(materials, dict) and materials:
            mat_items = sorted(
                [(float(v), str(k)) for k, v in materials.items()
                 if isinstance(v, (int, float))],
                reverse=True
            )
            mat_badges = []
            for pct, nm in mat_items[:10]:
                raw  = nm.strip().lower()
                disp = nm.capitalize() if nm.islower() else nm
                if raw in self.RARE:
                    badge = self._badge(
                        f"{disp} {pct:.1f}%", "#2a1a00", "#FFD93D"
                    )
                else:
                    badge = self._badge(
                        f"{disp} {pct:.1f}%", "#1a1a2a", "#888888"
                    )
                mat_badges.append(badge)

            if mat_badges:
                mat_lbl = QLabel(" ".join(mat_badges))
                mat_lbl.setTextFormat(Qt.TextFormat.RichText)
                mat_lbl.setWordWrap(True)
                mat_lbl.setStyleSheet("background: transparent; border: none;")
                card_l.addWidget(mat_lbl)

        return card

    # ── Materials shortlist ───────────────────────────────────────────────────
    def _refresh_materials(self, state):
        try:
            rare = self.RARE
            low_threshold = 25
            low_raw = set()
            inv_raw = getattr(state, "materials_raw", {}) or {}
            if isinstance(inv_raw, dict):
                for k, v in inv_raw.items():
                    if isinstance(k, str) and isinstance(v, int) and v <= low_threshold:
                        low_raw.add(k.strip().lower())

            targets = []
            for body, rec in (state.bodies or {}).items():
                if not isinstance(rec, dict):
                    continue
                if rec.get("Landable") is not True:
                    continue
                geo = rec.get("GeoSignals", 0) or 0
                if not (isinstance(geo, int) and geo > 0):
                    continue

                dist     = rec.get("DistanceLS")
                dist_v   = float(dist) if isinstance(dist, (int, float)) else None
                volc     = rec.get("Volcanism") or ""
                volc_ok  = bool(
                    isinstance(volc, str) and volc.strip()
                    and "no volcanism" not in volc.strip().lower()
                )
                mats     = rec.get("Materials") or {}
                if not isinstance(mats, dict):
                    mats = {}

                rare_score = sum(
                    float(v) for k, v in mats.items()
                    if isinstance(v, (int, float)) and str(k).strip().lower() in rare
                )
                need_score = sum(
                    float(v) for k, v in mats.items()
                    if isinstance(v, (int, float)) and str(k).strip().lower() in low_raw
                )
                score = (
                    (geo * 1000)
                    + (120 if volc_ok else 0)
                    + (need_score * 20.0)
                    + (rare_score * 8.0)
                    - ((dist_v or 0.0) * 0.10)
                )
                targets.append((score, body, geo, dist_v, volc, mats))

            targets.sort(key=lambda x: x[0], reverse=True)
            show = targets[:6]

            if not show:
                self.materials_box.setText(
                    '<span style="color:#444444;">No landable bodies with Geological signals yet.</span>'
                )
                return

            html = []
            for i, (_, body, geo, dist_v, volc, mats) in enumerate(show, 1):
                head = f'<span style="color:#FFB347;font-weight:700;">{i}. {self._esc(body)}</span>'
                if isinstance(dist_v, float):
                    head += f'<span style="color:#888888;"> — {dist_v:.0f} Ls</span>'
                head += f'<span style="color:#6BCB77;"> — Geo {geo}</span>'
                if (
                    isinstance(volc, str) and volc.strip()
                    and "no volcanism" not in volc.lower()
                ):
                    head += f'<span style="color:#FF8888;"> — Volcanism</span>'
                html.append(head)

                mat_items = sorted(
                    [(float(v), str(k)) for k, v in mats.items()
                     if isinstance(v, (int, float))],
                    reverse=True
                )
                if mat_items:
                    parts = []
                    for pct, nm in mat_items[:6]:
                        raw  = nm.strip().lower()
                        disp = nm.capitalize() if nm.islower() else nm
                        bang = "!" if raw in low_raw else ""
                        star = "*" if raw in rare else ""
                        color = "#FFD93D" if raw in rare else "#888888"
                        parts.append(
                            f'<span style="color:{color};">{self._esc(disp)}{bang}{star} {pct:.1f}%</span>'
                        )
                    html.append("&nbsp;&nbsp;" + " &nbsp; ".join(parts))

                html.append("")

            self.materials_box.setText("<br>".join(html).strip())

        except Exception:
            self.materials_box.setText("")

    # ── resizeEvent ───────────────────────────────────────────────────────────
    def _refresh_materials_shortlist(self, state):
        """Alias kept for main_window compatibility."""
        self._refresh_materials(state)

    def resizeEvent(self, event):
        super().resizeEvent(event)