# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See the LICENSE file in the project root for full terms.

"""Faction Expansion tracker — a standalone window for pushing one
squadron-aligned faction toward the 75% BGS expansion threshold in one
target system, alongside that system's PowerPlay standing.

Reuses existing data wherever it already exists rather than duplicating
it: faction_snapshots (influence history, via Repository.get_faction_history)
and Frontier's own official PowerPlay CSV feed (FdevPowerPlayCache,
already integrated) are both read as-is. The two genuinely new pieces are
mission-completion tracking (faction_mission_completions, since
active_missions discards a mission's faction/system the instant it
completes) and the pinned target system itself (FactionExpansionPinStore).

BGS expansion evaluates on the DAILY BGS tick; PowerPlay's own cycle
(undermining/reinforcement/decay/control) is WEEKLY (Thursdays). These
are shown as two separate countdowns, not merged -- conflating them would
misrepresent when expansion actually triggers.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, QObject, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QDialog, QFrame, QSizePolicy,
)

from edc.ui.style import CARD_STYLE as _CARD_STYLE, HDR_STYLE as _HDR_STYLE, PRIMARY_BUTTON_STYLE as _BTN_STYLE
from edc.ui import formatting as fmt
from edc.core.edsm_faction_lookup import fetch_system_factions, ERROR_BLOCKED, ERROR_NOT_FOUND

log = logging.getLogger("edc.faction_expansion")

_EXPANSION_THRESHOLD = 75.0


def _parse_states(raw) -> List[str]:
    """Parses a faction_snapshots active_states/pending_states JSON column
    (a list of {"State": ..., "Trend": ...} dicts) into a flat list of
    State strings. Duplicated from player_faction_panel.py's identical
    helper rather than imported -- that module already imports FROM this
    one (FactionExpansionDialog), so importing back would be circular."""
    if not raw:
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [
        str(s.get("State"))
        for s in data
        if isinstance(s, dict) and s.get("State")
    ]


def _is_expanding(latest_snapshot: Optional[Dict[str, Any]]) -> bool:
    """True if the faction's most recent snapshot shows Frontier's own
    "Expansion" BGS state -- either as the primary faction_state or
    listed in active_states (both are real places EDSM's data puts it,
    kept as two checks rather than assuming one). This is the actual
    trigger signal: once expansion is active, influence decays a little
    per day for about a week until it either completes or fails, so the
    push needs to continue rather than stop the moment 75% is crossed."""
    if not latest_snapshot:
        return False
    state = (latest_snapshot.get("faction_state") or "").strip().lower()
    if state == "expansion":
        return True
    active = {s.lower() for s in _parse_states(latest_snapshot.get("active_states"))}
    return "expansion" in active


class _ExpansionLookupWorker(QObject):
    """Live EDSM faction-influence lookup for the pinned target system --
    same fetch_system_factions() call the existing "Add System" flow on
    the Player Faction tab already uses."""
    finished = pyqtSignal(object, object, str)  # (result dict or None, error code or None, queried system name)

    def __init__(self, system_name: str):
        super().__init__()
        self._system_name = system_name

    def run(self):
        result, error = fetch_system_factions(self._system_name)
        self.finished.emit(result, error, self._system_name)


class _InfluenceTrendWidget(QWidget):
    """Small custom-painted line chart: daily influence % history for one
    faction, with a dashed line marking the 75% expansion threshold."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._points: List[tuple] = []  # [(date_str, influence_pct), ...] oldest first
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_points(self, points: List[tuple]) -> None:
        self._points = points
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        pad_l, pad_r, pad_t, pad_b = 36, 12, 12, 20

        p.fillRect(self.rect(), QColor("#0a1520"))

        plot_w = max(1, w - pad_l - pad_r)
        plot_h = max(1, h - pad_t - pad_b)

        def y_for(pct: float) -> float:
            pct = max(0.0, min(100.0, pct))
            return pad_t + plot_h * (1 - pct / 100.0)

        # Gridlines + axis labels at 0/25/50/75/100%
        p.setPen(QPen(QColor("#1e3a5a"), 1))
        font = p.font()
        font.setPointSize(8)
        p.setFont(font)
        for pct in (0, 25, 50, 75, 100):
            y = y_for(pct)
            p.drawLine(pad_l, int(y), w - pad_r, int(y))
            p.setPen(QColor("#6a7a8a"))
            p.drawText(2, int(y) + 4, f"{pct}")
            p.setPen(QPen(QColor("#1e3a5a"), 1))

        # 75% expansion threshold, highlighted
        p.setPen(QPen(QColor("#FFB347"), 1, Qt.PenStyle.DashLine))
        y75 = y_for(_EXPANSION_THRESHOLD)
        p.drawLine(pad_l, int(y75), w - pad_r, int(y75))

        if len(self._points) < 2:
            p.setPen(QColor("#6a7a8a"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Not enough history yet")
            p.end()
            return

        n = len(self._points)
        step = plot_w / max(1, n - 1)
        coords = [
            (pad_l + i * step, y_for(pct))
            for i, (_d, pct) in enumerate(self._points)
        ]

        p.setPen(QPen(QColor("#4D96FF"), 2))
        for i in range(len(coords) - 1):
            x1, y1 = coords[i]
            x2, y2 = coords[i + 1]
            p.drawLine(int(x1), int(y1), int(x2), int(y2))
        p.setBrush(QColor("#4D96FF"))
        for x, y in coords:
            p.drawEllipse(int(x) - 2, int(y) - 2, 4, 4)

        p.end()


class _PowerPlayBarWidget(QWidget):
    """Custom-painted undermining/reinforcement bar, mirroring the shape
    of Inara's own PowerPlay display -- red segment (undermining) on the
    left, blue segment (reinforcement) on the right, sized proportionally
    to the larger of the two so neither side ever fully dominates the
    other visually when one is much smaller."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._undermining = 0
        self._reinforcement = 0
        self.setMinimumHeight(48)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_values(self, undermining: int, reinforcement: int) -> None:
        self._undermining, self._reinforcement = undermining, reinforcement
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        bar_h = 14
        bar_y = (h - bar_h) // 2

        total = max(1, self._undermining + self._reinforcement)
        mid = w // 2

        # Track background, split down the middle.
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#3a1a1a"))
        p.drawRect(0, bar_y, mid, bar_h)
        p.setBrush(QColor("#12203a"))
        p.drawRect(mid, bar_y, w - mid, bar_h)

        # Each half filled by its own share of the total -- undermining
        # grows leftward from the centre, reinforcement grows rightward,
        # so equal values look visually balanced either side of the divider.
        under_frac = self._undermining / total
        reinforce_frac = self._reinforcement / total
        p.setBrush(QColor("#E85D5D"))
        seg_w = int(mid * under_frac * 2)
        p.drawRect(max(0, mid - seg_w), bar_y, min(seg_w, mid), bar_h)
        p.setBrush(QColor("#4D96FF"))
        seg_w2 = int((w - mid) * reinforce_frac * 2)
        p.drawRect(mid, bar_y, min(seg_w2, w - mid), bar_h)

        p.setPen(QColor("#E85D5D"))
        font = p.font()
        font.setBold(True)
        p.setFont(font)
        p.drawText(4, bar_y - 4, f"{self._undermining:,} undermining")
        p.setPen(QColor("#4D96FF"))
        fm = p.fontMetrics()
        text = f"{self._reinforcement:,} reinforcement"
        p.drawText(w - fm.horizontalAdvance(text) - 4, bar_y - 4, text)
        p.end()


class FactionExpansionDialog(QDialog):
    """Non-modal window: track one squadron-aligned faction's push toward
    75% influence (BGS expansion) in one target system, alongside that
    system's PowerPlay standing. See this module's own docstring for the
    daily-vs-weekly tick distinction."""

    def __init__(self, panel: "PlayerFactionPanel"):
        super().__init__(None)
        self.setStyleSheet("QDialog { background:#080f18; color:#c8c8c8; }")
        self._panel = panel
        self._thread: Optional[QThread] = None
        self._worker: Optional[_ExpansionLookupWorker] = None
        self._system_address: Optional[int] = None
        self._tracked_system_name: Optional[str] = None
        self.setWindowTitle("Faction Expansion Tracker")
        self.resize(760, 640)

        layout = QVBoxLayout(self)

        pin_row = QHBoxLayout()
        self._system_edit = QLineEdit()
        self._system_edit.setPlaceholderText("Target system name…")
        self._system_edit.setStyleSheet("background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;")
        self._system_edit.returnPressed.connect(self._on_track_clicked)
        pin_row.addWidget(self._system_edit, 1)
        track_btn = QPushButton("Track")
        track_btn.setStyleSheet(_BTN_STYLE)
        track_btn.clicked.connect(self._on_track_clicked)
        pin_row.addWidget(track_btn)
        refresh_btn = QPushButton("⟳ Refresh")
        refresh_btn.setStyleSheet(_BTN_STYLE)
        refresh_btn.clicked.connect(self._on_refresh_clicked)
        pin_row.addWidget(refresh_btn)
        self._untrack_btn = QPushButton("Untrack")
        self._untrack_btn.setStyleSheet(_BTN_STYLE)
        self._untrack_btn.setEnabled(False)
        self._untrack_btn.clicked.connect(self._on_untrack_clicked)
        pin_row.addWidget(self._untrack_btn)
        layout.addLayout(pin_row)

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet("color:#888888; font-size:11px; background:transparent; border:none;")
        layout.addWidget(self._status_label)

        self._header_label = QLabel("")
        self._header_label.setWordWrap(True)
        self._header_label.setStyleSheet("color:#FFB347; font-size:16px; font-weight:bold; background:transparent; border:none;")
        layout.addWidget(self._header_label)

        # Auto-refreshes the influence side every 2 minutes while this
        # window is open, same as the Raven Colonial window's own timer --
        # otherwise influence % would silently lag behind the mission
        # counter, which updates live off the MissionCompleted event.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(2 * 60 * 1000)
        self._refresh_timer.timeout.connect(self._on_auto_refresh_tick)

        self._expansion_banner = QLabel("")
        self._expansion_banner.setWordWrap(True)
        self._expansion_banner.setStyleSheet(
            "background:#2a1a00; color:#FFB347; border:1px solid #5a3a00; border-radius:4px;"
            " padding:6px; font-weight:bold;"
        )
        self._expansion_banner.setVisible(False)
        layout.addWidget(self._expansion_banner)

        # ── Influence card ───────────────────────────────────────────────
        inf_card = QFrame()
        inf_card.setStyleSheet(_CARD_STYLE)
        inf_l = QVBoxLayout(inf_card)
        inf_hdr = QLabel("EXPANSION PROGRESS")
        inf_hdr.setStyleSheet(_HDR_STYLE)
        inf_l.addWidget(inf_hdr)
        self._influence_label = QLabel("No data yet.")
        self._influence_label.setStyleSheet("font-size:14px; background:transparent; border:none;")
        inf_l.addWidget(self._influence_label)
        self._trend_widget = _InfluenceTrendWidget()
        inf_l.addWidget(self._trend_widget)
        layout.addWidget(inf_card)

        # ── PowerPlay card ───────────────────────────────────────────────
        pp_card = QFrame()
        pp_card.setStyleSheet(_CARD_STYLE)
        pp_l = QVBoxLayout(pp_card)
        pp_hdr = QLabel("POWERPLAY STANDING")
        pp_hdr.setStyleSheet(_HDR_STYLE)
        pp_l.addWidget(pp_hdr)
        self._pp_label = QLabel("No PowerPlay data for this system.")
        self._pp_label.setWordWrap(True)
        self._pp_label.setStyleSheet("background:transparent; border:none;")
        pp_l.addWidget(self._pp_label)
        self._pp_bar = _PowerPlayBarWidget()
        pp_l.addWidget(self._pp_bar)
        layout.addWidget(pp_card)

        # ── Missions + ticks card ────────────────────────────────────────
        bottom_row = QHBoxLayout()

        missions_card = QFrame()
        missions_card.setStyleSheet(_CARD_STYLE)
        missions_l = QVBoxLayout(missions_card)
        missions_hdr = QLabel("MISSIONS COMPLETED FOR THIS FACTION")
        missions_hdr.setStyleSheet(_HDR_STYLE)
        missions_l.addWidget(missions_hdr)
        self._missions_label = QLabel("—")
        self._missions_label.setWordWrap(True)
        self._missions_label.setStyleSheet("font-size:13px; background:transparent; border:none;")
        missions_l.addWidget(self._missions_label)
        bottom_row.addWidget(missions_card, 1)

        ticks_card = QFrame()
        ticks_card.setStyleSheet(_CARD_STYLE)
        ticks_l = QVBoxLayout(ticks_card)
        ticks_hdr = QLabel("TICKS")
        ticks_hdr.setStyleSheet(_HDR_STYLE)
        ticks_l.addWidget(ticks_hdr)
        self._ticks_label = QLabel("—")
        self._ticks_label.setWordWrap(True)
        self._ticks_label.setStyleSheet("font-size:12px; background:transparent; border:none;")
        ticks_l.addWidget(self._ticks_label)
        bottom_row.addWidget(ticks_card, 1)

        layout.addLayout(bottom_row)

        # ── Static reference ─────────────────────────────────────────────
        ref = QLabel(
            "<b>How to push influence up:</b> Run missions for the faction, prioritizing high-"
            "influence rewards. Trade commodities at their stations. Turn in bounty vouchers and "
            "combat bonds at their security offices. Sell exploration data at one of their stations. "
            "Once expansion triggers it lasts about a week -- influence drifts down daily, so keep "
            "supporting the push to actually complete it."
        )
        ref.setWordWrap(True)
        ref.setStyleSheet("color:#9aa4b0; font-size:11px; background:transparent; border:none; padding-top:4px;")
        layout.addWidget(ref)

        self._load_pinned()

    # ── Pin lifecycle ────────────────────────────────────────────────────

    def _load_pinned(self) -> None:
        store = self._panel._faction_expansion_pin_store
        system_name = store.load() if store else None
        if not system_name:
            return
        self._system_edit.setText(system_name)
        self._start_lookup(system_name)

    def _on_track_clicked(self) -> None:
        system_name = self._system_edit.text().strip()
        if not system_name:
            return
        self._start_lookup(system_name)

    def _on_refresh_clicked(self) -> None:
        system_name = self._system_edit.text().strip()
        if system_name:
            self._start_lookup(system_name)

    def _on_untrack_clicked(self) -> None:
        store = self._panel._faction_expansion_pin_store
        if store:
            store.clear()
        self._refresh_timer.stop()
        self._system_address = None
        self._tracked_system_name = None
        self._untrack_btn.setEnabled(False)
        self._expansion_banner.setVisible(False)
        self._header_label.setText("")
        self._influence_label.setText("No data yet.")
        self._trend_widget.set_points([])
        self._pp_label.setText("No PowerPlay data for this system.")
        self._pp_bar.set_values(0, 0)
        self._missions_label.setText("—")
        self._ticks_label.setText("—")
        self._status_label.setText("Untracked.")

    # ── EDSM lookup ──────────────────────────────────────────────────────

    def _start_lookup(self, system_name: str) -> None:
        if self._thread and self._thread.isRunning():
            return
        if not self._panel._faction_name:
            self._status_label.setText("No squadron faction configured yet on the Player Faction tab.")
            return
        self._status_label.setText(f"Looking up {system_name}…")
        self._worker = _ExpansionLookupWorker(system_name)
        if self._thread is not None:
            self._thread.wait()  # old-thread teardown race -- see main_window.py's _start_spansh_enrich docstring
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_lookup_finished)
        self._worker.finished.connect(self._thread.quit)
        self._thread.start()

    def _on_lookup_finished(self, result: Optional[dict], error: Optional[str], queried_name: str) -> None:
        if not result:
            if error == ERROR_BLOCKED:
                self._status_label.setText(f"EDSM lookup for {queried_name!r} failed — try again shortly.")
            elif error == ERROR_NOT_FOUND:
                self._status_label.setText(f"{queried_name!r} isn't in EDSM's database.")
            else:
                self._status_label.setText(f"Lookup for {queried_name!r} failed.")
            return

        faction_name = self._panel._faction_name
        factions = result.get("factions") or []
        match = next((f for f in factions if f.get("Name") == faction_name), None)
        if not match:
            self._status_label.setText(f"{result['system_name']} found, but {faction_name} isn't present there.")
            return

        try:
            repo = self._panel._repo
            repo.save_system_name_if_missing(result["system_address"], result["system_name"])
            is_controlling = bool(match.pop("is_controlling", False))
            data_timestamp = match.pop("LastUpdate", None)
            repo.save_faction_snapshot(
                result["system_address"], dict(match), date.today().isoformat(), is_controlling,
                data_timestamp, "edsm",
            )
        except Exception:
            log.exception("Failed to save EDSM-sourced faction snapshot for expansion tracker")
            self._status_label.setText("Found it, but saving failed — see log.")
            return

        store = self._panel._faction_expansion_pin_store
        if store:
            store.save(result["system_name"])
        self._system_address = result["system_address"]
        self._tracked_system_name = result["system_name"]
        self._untrack_btn.setEnabled(True)
        self._status_label.setText("")
        self._render(result["system_name"], match.get("Influence"))
        if not self._refresh_timer.isActive():
            self._refresh_timer.start()

    def _on_auto_refresh_tick(self) -> None:
        if self._tracked_system_name:
            self._start_lookup(self._tracked_system_name)

    def showEvent(self, event) -> None:
        """Refresh-on-open, same as the Raven Colonial window -- whatever
        is currently tracked gets a fresh fetch every time this window is
        reopened, on top of the interval timer and the manual buttons."""
        super().showEvent(event)
        if self._tracked_system_name and not (self._thread and self._thread.isRunning()):
            self._start_lookup(self._tracked_system_name)

    # ── Render ───────────────────────────────────────────────────────────

    def _render(self, system_name: str, current_influence: Optional[float]) -> None:
        faction_name = self._panel._faction_name
        pct = (current_influence or 0.0) * 100.0
        self._header_label.setText(f"{faction_name} — {system_name}")

        history = self._panel._repo.get_faction_history(self._system_address, faction_name)
        history_asc = list(reversed(history))  # get_faction_history is DESC; chart wants oldest-first
        points = [(h["snapshot_date"], (h.get("influence") or 0.0) * 100.0) for h in history_asc]
        self._trend_widget.set_points(points)

        delta_txt = ""
        if len(points) >= 2:
            delta = points[-1][1] - points[-2][1]
            arrow = "▲" if delta > 0 else ("▼" if delta < 0 else "→")
            delta_txt = f"  ({arrow} {abs(delta):.1f} pts since last snapshot)"
        gap = max(0.0, _EXPANSION_THRESHOLD - pct)
        self._influence_label.setText(
            f"{pct:.1f}% influence{delta_txt}  —  {gap:.1f} pts to {_EXPANSION_THRESHOLD:.0f}% expansion threshold"
            if gap > 0 else
            f"{pct:.1f}% influence{delta_txt}  —  ✅ at or above the {_EXPANSION_THRESHOLD:.0f}% expansion threshold"
        )

        latest = history[0] if history else None
        if _is_expanding(latest):
            self._expansion_banner.setText(
                "🚧 EXPANSION IN PROGRESS — Frontier's own BGS state for this faction here is "
                "\"Expansion\". It lasts about a week; influence drifts down a little each day "
                "until it completes, so keep running missions/trading/etc. for this faction here "
                "or the push can fail before it finishes."
            )
            self._expansion_banner.setVisible(True)
        else:
            self._expansion_banner.setVisible(False)

        # PowerPlay
        fdev = getattr(self._panel, "_fdev_powerplay", None)
        pp = fdev.get_by_name(system_name) if fdev else None
        if pp:
            qty_for = pp.get("qty_for") or 0
            qty_against = pp.get("qty_against") or 0
            self._pp_bar.set_values(qty_against, qty_for)
            self._pp_label.setText(
                f"{pp.get('power') or 'Unknown power'} — {pp.get('state') or 'Unknown state'}"
                f"  •  Predicted: {pp.get('prediction') or '—'}"
            )
        else:
            self._pp_bar.set_values(0, 0)
            self._pp_label.setText("No PowerPlay data for this system.")

        # Missions
        counts = self._panel._repo.get_faction_mission_completion_counts(self._system_address, faction_name)
        self._missions_label.setText(
            f"Today: {counts['today']} (weight {counts['weighted_today']})   •   "
            f"Last 7 days: {counts['last_7_days']} (weight {counts['weighted_last_7_days']})\n"
            "Weight sums Frontier's own \"+\" to \"+++++\" mission-impact rating -- a rough relative "
            "signal, not a real point total (the game never exposes exact influence points)."
        )

        # Ticks
        self._render_ticks()

    def _render_ticks(self) -> None:
        lines = []
        last_bgs = getattr(self._panel, "_latest_known_tick", None)
        if last_bgs:
            age_txt, _ = fmt.relative_time(last_bgs)
            try:
                last_dt = datetime.fromisoformat(last_bgs.replace("Z", "+00:00"))
                next_est = last_dt + timedelta(hours=24)
                remaining = next_est - datetime.now(timezone.utc)
                if remaining.total_seconds() > 0:
                    hrs = int(remaining.total_seconds() // 3600)
                    mins = int((remaining.total_seconds() % 3600) // 60)
                    lines.append(f"BGS tick: last seen {age_txt} — next estimated in ~{hrs}h {mins}m")
                else:
                    lines.append(f"BGS tick: last seen {age_txt} — overdue, likely already ticked")
            except Exception:
                lines.append(f"BGS tick: last seen {age_txt}")
        else:
            lines.append("BGS tick: unknown yet")

        now = datetime.now(timezone.utc)
        days_ahead = (3 - now.weekday()) % 7  # Thursday = weekday 3
        next_thu = (now + timedelta(days=days_ahead)).replace(hour=7, minute=0, second=0, microsecond=0)
        if next_thu <= now:
            next_thu += timedelta(days=7)
        remaining_pp = next_thu - now
        d = remaining_pp.days
        h = remaining_pp.seconds // 3600
        lines.append(f"PowerPlay tick: next ~{d}d {h}h (Thursdays ~07:00 UTC, community-estimated)")

        self._ticks_label.setText("\n".join(lines))
