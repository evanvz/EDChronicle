import logging
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QScrollArea,
    QFrame,
    QTabWidget,
)
from PyQt6.QtCore import Qt

from edc.ui import formatting as fmt
from edc.ui.panels.powerplay_finder_panel import PowerplayFinderPanel
from edc.ui.panels.player_faction_panel import derive_bgs_action

log = logging.getLogger(__name__)


class PowerplayPanel(QWidget):
    """
    Owns all widgets and refresh logic for the PowerPlay tab.
    Receives state via refresh(state). Knows nothing about
    main_window, repo, or any other panel.
    """

    def __init__(self, parent=None, edsm_powerplay=None, eddn_powerplay=None, fdev_powerplay=None):
        super().__init__(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(
            "QTabWidget::pane { border:1px solid #1e3a5a; background:#080f18; }"
            "QTabBar::tab { background:#0d1a2a; color:#888888; padding:5px 14px;"
            " border:1px solid #1e3a5a; border-bottom:none; margin-right:2px; }"
            "QTabBar::tab:selected { background:#080f18; color:#FFB347; border-bottom:1px solid #080f18; }"
            "QTabBar::tab:hover { color:#c8c8c8; }"
        )
        root.addWidget(self._tabs)

        # ── Tab 1: Status (existing content) ──────────────────────────────
        status_widget = QWidget()
        outer = QVBoxLayout(status_widget)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        outer.addWidget(scroll)

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(content)
        layout.setSpacing(6)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(content)

        self._tabs.addTab(status_widget, "Status")

        # ── Tab 2: Target Finder ──────────────────────────────────────────
        self.finder_panel = PowerplayFinderPanel(
            edsm_powerplay=edsm_powerplay, eddn_powerplay=eddn_powerplay, fdev_powerplay=fdev_powerplay,
        )
        self._tabs.addTab(self.finder_panel, "Target Finder")

        # ── PP Status card ────────────────────────────────────────────────
        pp_frame = QFrame()
        pp_frame.setStyleSheet(
            "QFrame { background: #0d1a2a; border: 1px solid #1e3a5a;"
            "border-radius: 5px; }"
        )
        pp_frame_l = QVBoxLayout(pp_frame)
        pp_frame_l.setContentsMargins(8, 6, 8, 6)
        pp_frame_l.setSpacing(4)

        pp_hdr = QLabel("POWERPLAY STATUS")
        pp_hdr.setStyleSheet(
            "color: #4da3ff; font-size:12px; font-weight: bold; "
            "letter-spacing: 1px; background: transparent; border: none;"
        )
        pp_frame_l.addWidget(pp_hdr)

        self.pp_summary = QLabel("")
        self.pp_summary.setWordWrap(True)
        self.pp_summary.setStyleSheet("background: transparent; border: none;")
        pp_frame_l.addWidget(self.pp_summary)

        self.pp_conflict_banner = QLabel("")
        self.pp_conflict_banner.setWordWrap(True)
        self.pp_conflict_banner.setTextFormat(Qt.TextFormat.RichText)
        self.pp_conflict_banner.setVisible(False)
        self.pp_conflict_banner.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.pp_conflict_banner.setStyleSheet("background: transparent; border: none;")
        pp_frame_l.addWidget(self.pp_conflict_banner)

        layout.addWidget(pp_frame)

        # ── Local faction BGS card ─────────────────────────────────────────
        # A system's Power control is ultimately backed by its local minor
        # faction's BGS standing — losing that faction's war/election here
        # can threaten Power control even if PP-specific metrics look fine.
        # Sits directly under the PP Status card and uses a distinct dark
        # green tint so it reads as "local faction" rather than PP data.
        bgs_frame = QFrame()
        bgs_frame.setStyleSheet(
            "QFrame { background: #0e241c; border: 1px solid #2a5c46;"
            "border-radius: 5px; }"
        )
        bgs_frame_l = QVBoxLayout(bgs_frame)
        bgs_frame_l.setContentsMargins(8, 6, 8, 6)
        bgs_frame_l.setSpacing(4)

        bgs_hdr = QLabel("LOCAL FACTION BGS")
        bgs_hdr.setStyleSheet(
            "color: #4da3ff; font-size:12px; font-weight: bold; "
            "letter-spacing: 1px; background: transparent; border: none;"
        )
        bgs_frame_l.addWidget(bgs_hdr)

        self.bgs_summary = QLabel("")
        self.bgs_summary.setWordWrap(True)
        self.bgs_summary.setTextFormat(Qt.TextFormat.RichText)
        self.bgs_summary.setStyleSheet("background: transparent; border: none;")
        bgs_frame_l.addWidget(self.bgs_summary)

        layout.addWidget(bgs_frame)

        # ── Activities card ───────────────────────────────────────────────
        act_frame = QFrame()
        act_frame.setStyleSheet(
            "QFrame { background: #0d1a2a; border: 1px solid #1e3a5a;"
            "border-radius: 5px; }"
        )
        act_frame_l = QVBoxLayout(act_frame)
        act_frame_l.setContentsMargins(8, 6, 8, 6)
        act_frame_l.setSpacing(4)

        act_hdr = QLabel("RECOMMENDED ACTIONS")
        act_hdr.setStyleSheet(
            "color: #4da3ff; font-size:12px; font-weight: bold; "
            "letter-spacing: 1px; background: transparent; border: none;"
        )
        act_frame_l.addWidget(act_hdr)

        self.pp_actions = QLabel("")
        self.pp_actions.setWordWrap(True)
        self.pp_actions.setTextFormat(Qt.TextFormat.RichText)
        self.pp_actions.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.pp_actions.setStyleSheet("background: transparent; border: none;")
        act_frame_l.addWidget(self.pp_actions)

        layout.addWidget(act_frame)

        # ── Conflict progress card ────────────────────────────────────────
        prog_frame = QFrame()
        prog_frame.setStyleSheet(
            "QFrame { background: #0d1a2a; border: 1px solid #1e3a5a;"
            "border-radius: 5px; }"
        )
        prog_frame_l = QVBoxLayout(prog_frame)
        prog_frame_l.setContentsMargins(8, 6, 8, 6)
        prog_frame_l.setSpacing(4)

        self.pp_progress_label = QLabel("CONFLICT PROGRESS")
        self.pp_progress_label.setStyleSheet(
            "color: #4da3ff; font-size:12px; font-weight: bold; "
            "letter-spacing: 1px; background: transparent; border: none;"
        )
        prog_frame_l.addWidget(self.pp_progress_label)

        self.pp_progress = QTableWidget()
        self.pp_progress.setColumnCount(2)
        self.pp_progress.setHorizontalHeaderLabels(["Power", "Conflict %"])
        self.pp_progress.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.pp_progress.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.pp_progress.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.pp_progress.verticalHeader().setVisible(False)
        self.pp_progress.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.pp_progress.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.pp_progress.setMinimumHeight(80)
        self.pp_progress.setStyleSheet("background: transparent; border: none;")
        prog_frame_l.addWidget(self.pp_progress)

        self._prog_frame = prog_frame
        self._prog_frame.setVisible(False)
        layout.addWidget(prog_frame)

        layout.addStretch(1)

    def derive_pp_action(self, pledged, ctrl, pp_state, powers):
        if not pledged:
            return ""
        friendly = bool(ctrl and ctrl == pledged)
        enemy = bool(ctrl and ctrl != pledged and ctrl != "Unoccupied")
        st = (pp_state or "").strip()
        pows = powers if isinstance(powers, list) else []

        if st in ("Fortified", "Stronghold"):
            if friendly:
                return "Fortify/defend: run PP logistics and defensive activities for your power."
            if enemy:
                return "Enemy Stronghold: expect PP opposition; avoid or undermine (if you choose)."
            return "Fortified/stronghold activity present: stay alert."
        if st == "Contested":
            if friendly:
                return "Contested: support your power's conflict effort here."
            if enemy:
                return "Contested (enemy): higher risk; avoid or oppose (if you choose)."
            return "Contested: higher risk; PP conflict activity likely."
        if st == "Unoccupied":
            if pledged in pows:
                return "Unoccupied: your power is present; watch progress and support objectives if desired."
            return "Unoccupied: no clear PP objective; treat as neutral space."
        if enemy:
            return "Enemy space: stay alert for PP opposition."
        if friendly:
            return "Friendly space: PP objectives may be available."
        return ""

    def derive_pp_activity_hint(self, pledged, ctrl, state, powers):
        if not pledged:
            return ""
        s = str(state or "").lower()
        friendly = ctrl and ctrl == pledged
        enemy = ctrl and ctrl != pledged
        hints = []
        if "stronghold" in s or "fortified" in s:
            if friendly:
                hints.append("Fortify (deliver supplies)")
            else:
                hints.append("Undermine (kill power ships)")
        elif "exploited" in s:
            if enemy:
                hints.append("Undermine enemy logistics")
            else:
                hints.append("Maintain control")
        elif "unoccupied" in s:
            hints.append("Preparation / Expansion opportunity")
        if powers and pledged not in powers:
            hints.append("Enemy agents likely present")
        return "\n".join([f"✔ {h}" for h in hints])

    def build_pp_conflict_banner_html(
        self, pledged, ctrl, pp_state, control_progress,
        reinforcement, undermining, powers,
    ) -> str:
        ctrl_txt      = fmt.text(ctrl, default="Unknown")
        state_txt     = fmt.text(pp_state, default="Active")
        progress_txt  = (
            f"{control_progress * 100:.1f}%"
            if isinstance(control_progress, (int, float)) else "—"
        )
        reinforce_txt = f"{reinforcement:,}" if isinstance(reinforcement, int) else "—"
        undermine_txt = f"{undermining:,}" if isinstance(undermining, int) else "—"

        # Controlling power line — highlight if player's own power
        pledged_txt = fmt.text(pledged, default="")
        ctrl_color  = "#4D96FF" if (pledged_txt and ctrl == pledged_txt) else "#FFB347"

        # Other powers present (excluding controller)
        other_powers = [
            p for p in (powers or [])
            if isinstance(p, str) and p and p != ctrl
        ]
        power_lines = []
        for p in other_powers[:4]:
            if pledged_txt and p == pledged_txt:
                power_lines.append(
                    f'<span style="color:#7CFC98;font-weight:700;">{p} ★</span>'
                )
            else:
                power_lines.append(f'<span style="color:#cc8866;">{p}</span>')
        powers_html = "<br>".join(power_lines) if power_lines else ""

        # State name color — acquisition = amber, reinforcement = blue family
        _state_colors = {
            "stronghold":   "#7DD4FC",
            "fortified":    "#4D96FF",
            "exploited":    "#88AACC",
            "expansion":    "#FFD93D",
            "contested":    "#FF8C00",
            "uncontrolled": "#AAAAAA",
        }
        state_color = _state_colors.get((pp_state or "").lower(), "#e0e0e0")

        return (
            '<div style="border:1px solid #1e3a5a; border-radius:6px;'
            ' overflow:hidden; margin-top:4px;">'
            '<table width="100%" cellspacing="0" cellpadding="0"'
            ' style="border-collapse:collapse;">'
            '<tr>'

            # ── Left: Undermining ──────────────────────────────────────
            '<td width="33%" valign="top"'
            ' style="background-color:#1a0808; padding:10px 12px;">'
            f'<div style="color:#FF4444;font-size:26px;font-weight:700;'
            f'line-height:1.1;">{undermine_txt}</div>'
            f'<div style="color:#FF4444;font-size:12px;font-weight:700;'
            f'letter-spacing:1px;margin-top:2px;">UNDERMINING</div>'
            + (f'<div style="margin-top:6px;font-size:12px;line-height:1.5;">'
               f'{powers_html}</div>' if powers_html else '')
            + '</td>'

            # ── Center: Power state ────────────────────────────────────
            '<td width="34%" valign="top" align="center"'
            ' style="background-color:#080f18; padding:10px 12px;">'
            '<div style="color:#9aa4b0;font-size:12px;font-weight:700;'
            'letter-spacing:1px;">POWERPLAY</div>'
            f'<div style="color:{ctrl_color};font-size:12px;font-weight:700;'
            f'margin-top:4px;">{ctrl_txt} (Controlling)</div>'
            f'<div style="color:{state_color};font-size:20px;font-weight:700;'
            f'margin-top:4px;">{state_txt}</div>'
            f'<div style="color:#FFB347;font-size:12px;font-weight:700;'
            f'margin-top:4px;">{progress_txt}</div>'
            '</td>'

            # ── Right: Reinforcement ───────────────────────────────────
            # Mirrors Undermining's #1a0808 with the red/blue channels
            # swapped (#08081a) — same darkness/weight as the red block, so
            # the two sides read as a matched pair instead of one being a
            # subtle tint and the other a noticeably brighter box.
            '<td width="33%" valign="top" align="right"'
            ' style="background-color:#08081a; padding:10px 12px;">'
            f'<div style="color:#4D96FF;font-size:26px;font-weight:700;'
            f'line-height:1.1;">{reinforce_txt}</div>'
            f'<div style="color:#4D96FF;font-size:12px;font-weight:700;'
            f'letter-spacing:1px;margin-top:2px;">REINFORCEMENT</div>'
            f'<div style="color:#88aacc;font-size:12px;margin-top:6px;">'
            f'{ctrl_txt}</div>'
            '</td>'

            '</tr></table></div>'
        )

    def refresh(self, state, pp_activities=None):
        pledged  = getattr(state, "pp_power", None)
        ctrl     = getattr(state, "system_controlling_power", None)
        if ctrl in {"Stronghold", "Fortified", "Contested"}:
            ctrl = None
        pp_state  = getattr(state, "system_powerplay_state", None)
        powers    = getattr(state, "system_powers", None) or []
        prog      = getattr(state, "system_powerplay_conflict_progress", None) or {}
        reinforce = getattr(state, "system_powerplay_reinforcement", None)
        undermine = getattr(state, "system_powerplay_undermining", None)
        progress  = getattr(state, "system_powerplay_control_progress", None)

        # Banner
        try:
            has_banner = bool(
                ctrl
                or pp_state
                or isinstance(progress, (int, float))
                or isinstance(reinforce, int)
                or isinstance(undermine, int)
            )
            if has_banner:
                self.pp_conflict_banner.setText(
                    self.build_pp_conflict_banner_html(
                        pledged=pledged, ctrl=ctrl, pp_state=pp_state,
                        control_progress=progress, reinforcement=reinforce,
                        undermining=undermine, powers=powers,
                    )
                )
                self.pp_conflict_banner.setVisible(True)
            else:
                self.pp_conflict_banner.setText("")
                self.pp_conflict_banner.setVisible(False)
        except Exception:
            self.pp_conflict_banner.setVisible(False)

        # Summary
        sysn = getattr(state, "system", None) or "Unknown system"
        if ctrl == "Unoccupied":
            rel = "🟡 Neutral"
        elif ctrl and ctrl == pledged:
            rel = "🟢 Friendly"
        elif ctrl and ctrl != pledged:
            rel = "🔴 Enemy"
        else:
            rel = "🟡 Neutral"

        bits = [rel, f"System: {sysn}"]
        if ctrl:
            bits.append(f"Controlling Power: {ctrl}")
        if pp_state:
            bits.append(f"PP State: {pp_state}")
        if isinstance(progress, (int, float)):
            bits.append(f"Control: {progress * 100:.1f}%")
        if isinstance(reinforce, int):
            bits.append(f"Reinforcement: {reinforce:,}")
        if isinstance(undermine, int):
            bits.append(f"Undermining: {undermine:,}")
        if isinstance(powers, list) and powers:
            bits.append("Powers: " + ", ".join(
                p for p in powers if isinstance(p, str)
            ))
        self.pp_summary.setText(" | ".join(bits))

        # Actions
        action = self.derive_pp_action(pledged, ctrl, pp_state, powers)
        hint   = self.derive_pp_activity_hint(pledged, ctrl, pp_state, powers)

        txt = []
        if action:
            txt.append(f"Recommended: {action}")
        if hint:
            txt.append("")
            txt.append("Best Activity Here:")
            txt.append(hint)

        self.pp_actions.setTextFormat(Qt.TextFormat.RichText)
        html_parts = []
        if txt:
            safe = "<br>".join(
                t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                for t in txt
            )
            html_parts.append(safe)

        if pp_activities:
            if ctrl and ctrl == pledged:
                system_type = "reinforcement"
            elif ctrl and ctrl != pledged:
                system_type = "undermining"
            else:
                system_type = "acquisition"

            acts = pp_activities.get_actions(system_type, pp_state or "")
            if acts:
                ethos_colors = {
                    "Combat":  "#FF6B6B",
                    "Finance": "#FFD93D",
                    "Social":  "#6BCB77",
                    "Covert":  "#C77DFF",
                }
                ethos_order = ["Combat", "Finance", "Social", "Covert"]
                is_defensive = pp_activities.is_defensive(system_type)

                html_parts.append(
                    '<br><span style="color:#FF8C00;font-weight:700;letter-spacing:1px;">'
                    'LOCAL ACTIVITIES</span>'
                )
                if is_defensive:
                    html_parts.append(
                        '<span style="color:#FFB347;font-size:12px;">'
                        '&#9888; Defensive system: your personal merits are reduced by 35% here. '
                        'Control Points are unaffected.</span>'
                    )
                html_parts.append(
                    '<span style="color:#666666;font-size:12px;">'
                    "Contribute to your Power's Control Score by completing the "
                    'following activities in this system:</span>'
                )

                bonus = [a for a in acts if pledged and pledged in a.bonus_powers]
                regular = [a for a in acts if not (pledged and pledged in a.bonus_powers)]

                if bonus:
                    html_parts.append("<br>")
                    for a in bonus:
                        color = ethos_colors.get(a.ethos, "#FFB347")
                        html_parts.append(
                            f'<span style="color:#FFB347;">&#9656;&nbsp;{a.action}'
                            f'&nbsp;<span style="color:{color};font-size:12px;">'
                            f'(Ethos Bonus)</span></span>'
                        )

                if regular:
                    grouped = {e: [] for e in ethos_order}
                    for a in regular:
                        if a.ethos in grouped:
                            grouped[a.ethos].append(a.action)
                        else:
                            grouped.setdefault(a.ethos, []).append(a.action)
                    html_parts.append("<br>")
                    for ethos in ethos_order:
                        actions = grouped.get(ethos, [])
                        if not actions:
                            continue
                        color = ethos_colors.get(ethos, "#FFFFFF")
                        for act in actions:
                            html_parts.append(
                                f'<span style="color:#E6E6E6;">&#9656;&nbsp;{act}'
                                f'&nbsp;<span style="color:{color};font-size:12px;">'
                                f'[{ethos}]</span></span>'
                            )

        self.pp_actions.setText("<br>".join(html_parts))

        # Local faction BGS
        try:
            controlling_faction_name = getattr(state, "controlling_faction", None)
            factions = getattr(state, "factions", None) or []
            faction_rec = next(
                (f for f in factions if isinstance(f, dict) and f.get("Name") == controlling_faction_name),
                None,
            )
            if not faction_rec:
                self.bgs_summary.setText(
                    "No local faction data yet — jump into a system to see its BGS standing."
                )
            else:
                sys_rec = {
                    "active_states": faction_rec.get("ActiveStates") or [],
                    "pending_states": faction_rec.get("PendingStates") or [],
                    "recovering_states": faction_rec.get("RecoveringStates") or [],
                    "faction_state": faction_rec.get("FactionState"),
                    "is_controlling": True,
                }
                bgs_action, bgs_color = derive_bgs_action(sys_rec)
                self.bgs_summary.setText(
                    f"<b>{controlling_faction_name}</b> (controlling)<br>"
                    f'<span style="color:{bgs_color};">{bgs_action}</span>'
                )
        except Exception:
            log.exception("Failed to derive local faction BGS status")
            self.bgs_summary.setText("")

        # Conflict progress table
        has_conflict = isinstance(prog, dict) and any(
            isinstance(k, str) and isinstance(v, (int, float))
            for k, v in prog.items()
        )
        self._prog_frame.setVisible(has_conflict)

        rows = []
        if isinstance(prog, dict):
            for p, v in prog.items():
                if isinstance(p, str) and isinstance(v, (int, float)):
                    rows.append((p, float(v)))
        rows.sort(key=lambda x: x[1], reverse=True)

        leader = rows[0][0] if rows else None
        shown  = rows[:12]
        self.pp_progress.setRowCount(len(shown))
        for r, (p, v) in enumerate(shown):
            power_item = QTableWidgetItem(p)
            pct_item   = QTableWidgetItem(f"{v * 100:.2f}%")
            if p == leader:
                power_item.setText(f"{p} ⭐")
            if pledged and p == pledged:
                power_item.setText(f"{p} (Your PP)")
            self.pp_progress.setItem(r, 0, power_item)
            self.pp_progress.setItem(r, 1, pct_item)

        try:
            self.finder_panel.refresh(state, pp_activities)
        except Exception:
            pass
