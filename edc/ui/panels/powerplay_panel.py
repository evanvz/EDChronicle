import logging
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QScrollArea,
)
from PyQt6.QtCore import Qt

from edc.ui import formatting as fmt

log = logging.getLogger(__name__)


class PowerplayPanel(QWidget):
    """
    Owns all widgets and refresh logic for the PowerPlay tab.
    Receives state via refresh(state). Knows nothing about
    main_window, repo, or any other panel.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # Outer layout holds just the scroll area
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        outer.addWidget(scroll)

        # Content widget inside scroll area
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(content)
        layout.setSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(content)

        layout.addWidget(QLabel("PowerPlay"))

        self.pp_summary = QLabel("")
        self.pp_summary.setWordWrap(True)

        self.pp_conflict_banner = QLabel("")
        self.pp_conflict_banner.setWordWrap(True)
        self.pp_conflict_banner.setTextFormat(Qt.TextFormat.RichText)
        self.pp_conflict_banner.setVisible(False)
        self.pp_conflict_banner.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.pp_actions = QLabel("")
        self.pp_actions.setWordWrap(True)
        self.pp_actions.setTextFormat(Qt.TextFormat.RichText)
        self.pp_actions.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )

        self.pp_progress_label = QLabel("Conflict progress (if present)")
        self.pp_progress_label.setVisible(False)

        self.pp_progress = QTableWidget()
        self.pp_progress.setColumnCount(2)
        self.pp_progress.setHorizontalHeaderLabels(["Power", "Conflict %"])
        self.pp_progress.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.pp_progress.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.pp_progress.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.pp_progress.verticalHeader().setVisible(False)
        self.pp_progress.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.pp_progress.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.pp_progress.setMinimumHeight(120)
        self.pp_progress.setVisible(False)

        layout.addWidget(self.pp_summary)
        layout.addWidget(self.pp_conflict_banner)
        layout.addWidget(self.pp_actions)
        layout.addWidget(self.pp_progress_label)
        layout.addWidget(self.pp_progress)
        layout.addStretch(1)

    def derive_pp_action(self, pledged, ctrl, pp_state, powers):
        """
        Single authority for what should I do here PowerPlay action text.
        """
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
        self,
        pledged,
        ctrl,
        pp_state,
        control_progress,
        reinforcement,
        undermining,
        powers,
    ) -> str:
        ctrl_txt = fmt.text(ctrl, default="Unknown")
        state_txt = fmt.text(pp_state, default="Active")

        if isinstance(control_progress, (int, float)):
            progress_txt = f"{control_progress * 100:.1f}%"
        else:
            progress_txt = "—"

        reinforce_txt = (
            f"{reinforcement:,}" if isinstance(reinforcement, int) else "—"
        )
        undermine_txt = (
            f"{undermining:,}" if isinstance(undermining, int) else "—"
        )

        other_powers = []
        if isinstance(powers, list):
            for p in powers:
                if isinstance(p, str) and p and p != ctrl:
                    other_powers.append(p)

        enemy_lines = []
        pledged_txt = fmt.text(pledged, default="")
        for p in other_powers[:5]:
            if pledged_txt and p == pledged_txt:
                enemy_lines.append(
                    f'<span style="color:#7CFC98; font-weight:700;">{p} ★</span>'
                )
            else:
                enemy_lines.append(p)

        enemy_txt = "<br>".join(enemy_lines) if enemy_lines else "—"

        return f"""
<div style="
    background-color:#1f1f1f;
    border:1px solid #333333;
    border-radius:8px;
    padding:10px 12px;
    margin-top:4px;
    margin-bottom:4px;">
<table width="100%" cellspacing="0" cellpadding="0">
    <tr>
    <td width="33%" valign="top">
        <div style="color:#ff7043; font-size:24px; font-weight:700;">{undermine_txt}</div>
        <div style="color:#ff7043; font-size:12px; font-weight:700;">UNDERMINING</div>
        <div style="color:#ffb199; font-size:12px; margin-top:6px;">{enemy_txt}</div>
    </td>
    <td width="34%" valign="top" align="center">
        <div style="color:#bdbdbd; font-size:11px; font-weight:700;">POWERPLAY</div>
        <div style="color:#ff9f43; font-size:20px; font-weight:700; margin-top:2px;">{ctrl_txt}</div>
        <div style="color:#64b5f6; font-size:16px; font-weight:700; margin-top:2px;">{state_txt}</div>
        <div style="color:#ff7043; font-size:15px; font-weight:700; margin-top:2px;">{progress_txt}</div>
    </td>
    <td width="33%" valign="top" align="right">
        <div style="color:#64b5f6; font-size:24px; font-weight:700;">{reinforce_txt}</div>
        <div style="color:#64b5f6; font-size:12px; font-weight:700;">REINFORCEMENT</div>
        <div style="color:#d0e6ff; font-size:12px; margin-top:6px;">{ctrl_txt}</div>
    </td>
    </tr>
</table>
</div>
"""

    def refresh(self, state, pp_activities=None):
        pledged = getattr(state, "pp_power", None)
        ctrl = getattr(state, "system_controlling_power", None)
        if ctrl in {"Stronghold", "Fortified", "Contested"}:
            ctrl = None
        pp_state = getattr(state, "system_powerplay_state", None)
        powers = getattr(state, "system_powers", None) or []
        prog = getattr(state, "system_powerplay_conflict_progress", None) or {}
        reinforce = getattr(state, "system_powerplay_reinforcement", None)
        undermine = getattr(state, "system_powerplay_undermining", None)
        progress = getattr(state, "system_powerplay_control_progress", None)

        try:
            has_banner_data = bool(
                ctrl
                or pp_state
                or isinstance(progress, (int, float))
                or isinstance(reinforce, int)
                or isinstance(undermine, int)
            )
            if has_banner_data:
                self.pp_conflict_banner.setText(
                    self.build_pp_conflict_banner_html(
                        pledged=pledged,
                        ctrl=ctrl,
                        pp_state=pp_state,
                        control_progress=progress,
                        reinforcement=reinforce,
                        undermining=undermine,
                        powers=powers,
                    )
                )
                self.pp_conflict_banner.setVisible(True)
            else:
                self.pp_conflict_banner.setText("")
                self.pp_conflict_banner.setVisible(False)
        except Exception:
            self.pp_conflict_banner.setText("")
            self.pp_conflict_banner.setVisible(False)

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
            bits.append(f"PowerPlay State: {pp_state}")
        if isinstance(progress, (int, float)):
            bits.append(f"Control Progress: {progress * 100:.1f}%")
        if isinstance(reinforce, int):
            bits.append(f"Reinforcement: {reinforce:,}")
        if isinstance(undermine, int):
            bits.append(f"Undermining: {undermine:,}")
        if isinstance(powers, list) and powers:
            bits.append(
                "Powers present: "
                + ", ".join([p for p in powers if isinstance(p, str)])
            )
        self.pp_summary.setText(" | ".join(bits))

        action = self.derive_pp_action(pledged, ctrl, pp_state, powers)
        hint = self.derive_pp_activity_hint(pledged, ctrl, pp_state, powers)

        txt = []
        if action:
            txt.append(f"Recommended: {action}")
        if hint:
            txt.append("")
            txt.append("Best Activity Here:")
            txt.append(hint)

        # Add pp_activities list if available
        self.pp_actions.setTextFormat(Qt.TextFormat.RichText)

        html_parts = []
        if txt:
            safe = "<br>".join(
                t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                for t in txt
            )
            html_parts.append(safe)

        if pp_activities:
            pp_state = getattr(state, "system_powerplay_state", None)
            acts = pp_activities.get_actions(pp_state or "")
            if acts:
                ethos_colors = {
                    "Combat":    "#FF6B6B",
                    "Finance":   "#FFD93D",
                    "Social":    "#6BCB77",
                    "Logistics": "#4D96FF",
                    "Covert":    "#C77DFF",
                }
                ethos_order = [
                    "Combat", "Finance", "Social",
                    "Logistics", "Covert"
                ]
                grouped = {e: [] for e in ethos_order}
                for a in acts:
                    if a.ethos in grouped:
                        grouped[a.ethos].append(a.action)
                    else:
                        grouped.setdefault(a.ethos, []).append(a.action)

                html_parts.append("<br><b>Recommended Activities:</b>")
                for ethos in ethos_order:
                    actions = grouped.get(ethos, [])
                    if not actions:
                        continue
                    color = ethos_colors.get(ethos, "#FFFFFF")
                    html_parts.append(
                        f'<br><span style="color:{color};'
                        f'font-weight:700;">{ethos}</span>'
                    )
                    for action in actions:
                        html_parts.append(
                            f'<span style="color:{color};">'
                            f'&nbsp;&nbsp;• {action}</span>'
                        )

        self.pp_actions.setText("<br>".join(html_parts))

        has_conflict_rows = isinstance(prog, dict) and any(
            isinstance(k, str) and isinstance(v, (int, float))
            for k, v in prog.items()
        )
        self.pp_progress_label.setVisible(has_conflict_rows)
        self.pp_progress.setVisible(has_conflict_rows)

        rows = []
        if isinstance(prog, dict):
            for p, v in prog.items():
                if isinstance(p, str) and isinstance(v, (int, float)):
                    rows.append((p, float(v)))
        rows.sort(key=lambda x: x[1], reverse=True)

        leader = rows[0][0] if rows else None
        shown = rows[:12]
        self.pp_progress.setRowCount(len(shown))
        for r, (p, v) in enumerate(shown):
            power_item = QTableWidgetItem(p)
            pct_item = QTableWidgetItem(f"{v * 100:.2f}%")
            if p == leader:
                power_item.setText(f"{p} ⭐")
            if pledged and p == pledged:
                power_item.setText(f"{p} (Your PP)")
            self.pp_progress.setItem(r, 0, power_item)
            self.pp_progress.setItem(r, 1, pct_item)