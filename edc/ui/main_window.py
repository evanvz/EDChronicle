import logging
from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QMessageBox,
    QSlider,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QScrollArea,
    QLineEdit,
    QComboBox,
    QSpinBox,
    QListWidget,
    QListWidgetItem,
    QFileDialog,
    QSplitter,
    QStackedWidget,
    QGraphicsOpacityEffect,
    QFrame,
    QAbstractScrollArea,
    QSizePolicy,
)
from PyQt6.QtCore import QThread, Qt, QTimer, QSettings, QPropertyAnimation, QEasingCurve, QSize
from PyQt6.QtGui import QTextCursor, QColor
from pathlib import Path

from edc.core.state import GameState
from edc.core.event_engine import EventEngine
from edc.core.journal_watcher import JournalWatcher
from edc.ui.watcher_controller import WatcherController
from edc.ui.system_data_loader import SystemDataLoader
from edc.ui.panels.combat_panel import CombatPanel
from edc.ui.panels.inventory_panel import ShiplockerPanel, MaterialsPanel
from edc.ui.panels.powerplay_panel import PowerplayPanel
from edc.ui.panels.overview_panel import OverviewPanel
from edc.ui.panels.exploration_panel import ExplorationPanel
from edc.ui.panels.exobiology_panel import ExobiologyPanel
from edc.ui.panels.intel_panel import IntelPanel
from edc.core.status_watcher import StatusWatcher
from edc.core.planet_values import PlanetValueTable
from edc.core.exo_values import ExoValueTable
from edc.core.external_intel import ExternalIntel
from edc.core.item_catalog import ItemCatalog
from edc.core.farming_locations import FarmingLocations
from edc.core.powerplay_activities import PowerPlayActivityTable
from edc.ui import formatting as fmt
from typing import Any, Dict, List, Optional

from persistence.database import Database
from persistence.schema import SCHEMA_SQL
from persistence.repository import Repository

from edc.core.session_ledger import SessionLedger

log = logging.getLogger("edc.ui.main")

class MainWindow(QMainWindow):

    def refresh_from_state(self):
        self._refresh_system_card()
        self._refresh_exploration()
        self._refresh_powerplay()

    def start_auto_watch(self):
        self._auto_start_if_configured()

    def load_last_system_data(self):
        self.system_data_loader.load_last_system_data()

    def _save_session_ledger(self):
        try:
            self.session_ledger.save(
                {
                    "combat_unsold_total": int(getattr(self.state, "combat_unsold_total", 0) or 0),
                    "exploration_unsold_total_est": int(getattr(self.state, "exploration_unsold_total_est", 0) or 0),
                    "exobiology_unsold_total_est": int(getattr(self.state, "exobiology_unsold_total_est", 0) or 0),
                }
            )
        except Exception:
            pass

    def _planet_value_class_name(self, planet_class: str) -> str:
        pc = (planet_class or "").strip()
        mapping = {
            "Earthlike body": "Earth-like World",
            "High metal content body": "High Metal Content Planet",
            "Rocky body": "Rocky Body",
            "Rocky ice body": "Rocky Ice Body",
            "Water world": "Water World",
            "Ammonia world": "Ammonia World",
        }
        return mapping.get(pc, pc)

    # --- add inside class MainWindow, near other helper methods ---
    def _format_star_class_label(self, star_class: str | None) -> str:
        if not isinstance(star_class, str) or not star_class.strip():
            return ""

        sc = star_class.strip().upper()

        scoopable = {"O", "B", "A", "F", "G", "K", "M"}
        brown_dwarfs = {"L", "T", "Y"}

        if sc in scoopable:
            return f"{sc} • Scoopable"
        if sc in brown_dwarfs:
            return f"{sc} • Brown Dwarf"
        if sc.startswith("D"):
            return f"{sc} • White Dwarf"
        if sc in {"N", "NEUTRON"}:
            return f"{sc} • Neutron Star"

        return sc

    def _get_star_class_label_and_color(self, star_class: str | None) -> tuple[str, str]:
        if not isinstance(star_class, str) or not star_class.strip():
            return "", ""

        sc = star_class.strip().upper()

        scoopable = {"O", "B", "A", "F", "G", "K", "M"}
        brown_dwarfs = {"L", "T", "Y"}

        if sc in scoopable:
            return f"{sc} • Scoopable", "#7CFC98"   # soft green
        if sc in brown_dwarfs:
            return f"{sc} • Brown Dwarf", "#FFCC66" # amber
        if sc.startswith("D"):
            return f"{sc} • White Dwarf", "#FFB366" # orange-amber
        if sc in {"N", "NEUTRON"}:
            return f"{sc} • Neutron Star", "#FF9966" # deeper orange

        return sc, "#D3D3D3"  # neutral fallback

    def resizeEvent(self, event):
        try:
            if hasattr(self, "expl_outer_split"):
                total_width = self.width()

                # Dynamic biasing
                if total_width > 1600:
                    left_ratio = 0.65
                elif total_width > 1200:
                    left_ratio = 0.55
                else:
                    left_ratio = 0.50

                left_size = int(total_width * left_ratio)
                right_size = total_width - left_size

                self.expl_outer_split.setSizes([left_size, right_size])
            # Vertical bias (Signals vs Materials)
            if hasattr(self, "expl_right_split"):
                total_height = self.height()

                if total_height > 1000:
                    top_ratio = 0.70
                elif total_height > 800:
                    top_ratio = 0.60
                else:
                    top_ratio = 0.50

                top_size = int(total_height * top_ratio)
                bottom_size = total_height - top_size

                self.expl_right_split.setSizes([top_size, bottom_size])
        except Exception:
            pass

        super().resizeEvent(event)

    def _on_exploration_min_value_changed(self, text: str):
        if hasattr(self, "min_value_label"):
            self.min_value_label.setText(text)

    def _on_exo_min_value_changed(self, text: str):
        if hasattr(self, "exo_min_label"):
            self.exo_min_label.setText(text)

    def __init__(self, cfg_store, cfg, auto_start: bool = True):
        super().__init__()
        self.cfg_store = cfg_store
        self.cfg = cfg

        self.setWindowTitle("ED Companion Lite(Fresh Build)")
        self.resize(1000, 650)

        self.state = GameState()

        # Canonical paths: app_dir for shipped assets, settings_dir for writable JSON/caches.
        app_dir = Path(getattr(self.cfg_store, "app_dir", Path.cwd()))
        settings_base = Path(getattr(self.cfg_store, "settings_dir", app_dir / "settings"))

        data_dir = app_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        self.db = Database(data_dir / "edhelper.db")
        self.db.executescript(SCHEMA_SQL)
        self.repo = Repository(self.db)

        self.session_ledger = SessionLedger(data_dir / "session_ledger.json")
        ledger = self.session_ledger.load()
        self.state.combat_unsold_total = int(ledger.get("combat_unsold_total", 0) or 0)
        self.state.exploration_unsold_total_est = int(ledger.get("exploration_unsold_total_est", 0) or 0)
        self.state.exobiology_unsold_total_est = int(ledger.get("exobiology_unsold_total_est", 0) or 0)

        # Load value tables from the canonical app_dir only (no Path.cwd fallbacks).
        self.planet_values = PlanetValueTable.load_from_paths(settings_base / "planet_values.json")
        self.exo_values = ExoValueTable.load_from_paths(settings_base / "exo_values.json")
        self.pp_activities = PowerPlayActivityTable.load_from_paths(settings_base / "powerplay_activities.json")

        log.info("MainWindow paths: app_dir=%s settings_dir=%s", str(app_dir), str(settings_base))

        self.external_intel = ExternalIntel(settings_base)
        self.item_catalog = ItemCatalog(settings_base / "inara_items_catalog.json")
        self.farming_locations = FarmingLocations(settings_base / "elite_farming_locations.json")

        self.engine = EventEngine(
            self.state,
            settings_base,
            planet_values=self.planet_values,
            exo_values=self.exo_values,
            external_intel=self.external_intel,
        )

        self.system_data_loader = SystemDataLoader(
            state=self.state,
            repo=self.repo,
            planet_values=self.planet_values,
            on_refresh_exploration=self._refresh_exploration,
            on_refresh_materials_shortlist=self._refresh_materials_shortlist,
            on_refresh_exobiology=self._refresh_exobiology,
            planet_value_class_name_fn=self._planet_value_class_name,
        )

        self.watcher_controller = WatcherController(
            on_event=self._on_event,
            on_status=self._on_status,
            on_error=self._on_error,
        )

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        # ===============================
        # Elite Header Bar
        # ===============================
        self.header_bar = QLabel("ELITE DANGEROUS COMMAND COMPANION LITE")
        self.header_bar.setStyleSheet("""
            font-size: 18px;
            font-weight: bold;
            color: #FF8C00;
            padding-left: 12px;
            padding-top: 8px;
        """)

        # ---- Header layout (title left, session tracker right) ----
        self.hud = QLabel("Not connected")
        self.status = QLabel("Status: idle")

        btn_start = QPushButton("Start Watching Journals")
        btn_stop = QPushButton("Stop")

        left_header = QVBoxLayout()
        left_header.setContentsMargins(0, 0, 0, 0)
        left_header.setSpacing(6)
        left_header.addWidget(self.header_bar)
        left_header.addWidget(self.hud)
        left_header.addWidget(self.status)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(8)
        btn_row.addWidget(btn_start)
        btn_row.addWidget(btn_stop)
        btn_row.addStretch(1)
        left_header.addLayout(btn_row)

        # Session tracker panel
        self.session_panel = QLabel()
        self.session_panel.setText("Session\nKills: 0\nBounties: 0 cr")
        self.session_panel.setTextFormat(Qt.TextFormat.RichText)
        self.session_panel.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.session_panel.setStyleSheet("""
            color: #FF8C00;
            font-weight: bold;
            padding-left: 10px;
            padding-top: 4px;
        """)

        # Route tracker panel
        self.route_panel = QLabel()
        self.route_panel.setText("Route\nNext: -\nJumps: -")
        self.route_panel.setTextFormat(Qt.TextFormat.RichText)
        self.route_panel.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.route_panel.setStyleSheet("""
            color: #87CEFA;
            font-weight: bold;
            padding-left: 10px;
            padding-top: 4px;
        """)

        right_header = QHBoxLayout()
        right_header.setContentsMargins(0, 0, 0, 0)
        right_header.setSpacing(10)
        right_header.addWidget(self.route_panel)
        right_header.addWidget(self.session_panel)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(12)
        header_layout.addLayout(left_header, 1)
        header_layout.addLayout(right_header, 0)

        layout.addLayout(header_layout)

        self.min_value_label = QLabel()
        self.min_value_slider = QSlider()
        self.min_value_slider.setOrientation(Qt.Orientation.Horizontal)
        self.min_value_slider.setMinimum(0)
        # 0..200 => 0.0M .. 20.0M in steps of 0.1M (100k credits)
        self.min_value_slider.setMaximum(200)
        self.min_value_slider.setValue(int(getattr(self.cfg, "min_planet_value_100k", 10) or 10))
        self.min_value_slider.valueChanged.connect(self._on_min_value_changed)

        # Exobiology filter: "high value" threshold (M cr)
        self.exo_min_label = QLabel()
        self.exo_min_slider = QSlider()
        self.exo_min_slider.setOrientation(Qt.Orientation.Horizontal)
        self.exo_min_slider.setMinimum(0)
        self.exo_min_slider.setMaximum(50)
        self.exo_min_slider.setValue(int(getattr(self.cfg, "exo_high_value_m", 2) or 2))
        self.exo_min_slider.valueChanged.connect(self._on_exo_min_changed)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)

        # === ELITE SIDEBAR LAYOUT ===
        main_layout = QHBoxLayout()
        layout.addLayout(main_layout)

        # Sidebar
        self.sidebar = QListWidget()
        self.sidebar.setFrameShape(QFrame.Shape.NoFrame)
        self.sidebar.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sidebar.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sidebar.setFixedWidth(200)
        self.sidebar.setIconSize(QSize(20, 20))
        self.sidebar.setSpacing(4)

        # Stacked content
        self.stack = QStackedWidget()

        main_layout.addWidget(self.sidebar)
        main_layout.addWidget(self.stack, 1)

        # Overview tab (System Card)
        self.overview_panel = OverviewPanel()
        self.overview_panel.navigate_to.connect(self.sidebar.setCurrentRow)
        self.stack.addWidget(self.overview_panel)
        self.sidebar.addItem("Overview")

        # Exploration tab
        self.exploration_panel = ExplorationPanel()
        self.exploration_panel.min_value_changed.connect(
            self._on_exploration_min_value_changed
        )
        self.stack.addWidget(self.exploration_panel)
        self.sidebar.addItem("Exploration")

        # Exobiology tab
        self.exobiology_panel = ExobiologyPanel()
        self.exobiology_panel.exo_min_value_changed.connect(
            self._on_exo_min_value_changed
        )
        self.stack.addWidget(self.exobiology_panel)
        self.sidebar.addItem("Exobiology")

        # PowerPlay tab
        self.powerplay_panel = PowerplayPanel()
        self.stack.addWidget(self.powerplay_panel)
        self.sidebar.addItem("PowerPlay")

        # Combat tab (stub)
        self.combat_panel = CombatPanel()
        self.stack.addWidget(self.combat_panel)
        self.sidebar.addItem("Combat")

        # Intel tab (external / advisory)
        self.intel_panel = IntelPanel()
        self.stack.addWidget(self.intel_panel)
        self.sidebar.addItem("Intel")

        self.shiplocker_panel = ShiplockerPanel()
        self.stack.addWidget(self.shiplocker_panel)
        self.sidebar.addItem("Odyssey")
        
        self.materials_panel = MaterialsPanel()
        self.stack.addWidget(self.materials_panel)
        self.sidebar.addItem("Materials")

        # Settings tab
        tab_settings = QWidget()
        st = QVBoxLayout(tab_settings)

        st.addWidget(QLabel("Settings"))

        st.addWidget(QLabel("Elite Dangerous Journal Folder:"))
        row = QHBoxLayout()
        self.settings_journal_edit = QLineEdit(self.cfg.journal_dir or "")
        btn_browse = QPushButton("Browse…")
        row.addWidget(self.settings_journal_edit)
        row.addWidget(btn_browse)
        st.addLayout(row)

        st.addWidget(QLabel("Exploration filter: minimum planet value (M cr)"))
        row2 = QHBoxLayout()
        row2.addWidget(self.min_value_slider)
        row2.addWidget(self.min_value_label)
        st.addLayout(row2)

        st.addWidget(QLabel("Exobiology: high-value threshold (M cr)"))
        row3 = QHBoxLayout()
        row3.addWidget(self.exo_min_slider)
        row3.addWidget(self.exo_min_label)
        st.addLayout(row3)

        st.addStretch(1)
        self.stack.addWidget(tab_settings)
        self.sidebar.addItem("Settings")

        # Log tab
        tab_log = QWidget()
        lg = QVBoxLayout(tab_log)
        lg.addWidget(QLabel("Log"))
        lg.addWidget(self.log_box)
        self.stack.addWidget(tab_log)
        self.sidebar.addItem("Log")

        btn_start.clicked.connect(self.start_watching)
        btn_stop.clicked.connect(self.stop_watching)
        btn_browse.clicked.connect(self._browse_journal_dir)
        self.settings_journal_edit.editingFinished.connect(self._on_settings_journal_changed)

        # ---- Intel hint suppression (show once per system change) ----
        self._last_intel_system_key: str = ""

        # ---- UI refresh debounce (journal bursts can be spammy) ----
        self._hud_refresh_pending = False
        self._hud_refresh_timer = QTimer(self)
        self._hud_refresh_timer.setSingleShot(True)
        self._hud_refresh_timer.timeout.connect(self._do_hud_refresh)

        # Sidebar navigation
        self.sidebar.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.sidebar.setCurrentRow(0)
        self._refresh_hud()
        if auto_start:
            self._auto_start_if_configured()

    def load_current_system_data(self):
        self.system_data_loader.load_current_system_data()

    def _auto_start_if_configured(self):
        """
        Auto-start journal watching on launch if a journal_dir is configured and valid.
        Uses a silent start to avoid modal popups on startup.
        """
        try:
            jd = (self.cfg.journal_dir or "").strip()
            if not jd:
                return
            p = Path(jd)
            if not p.exists():
                self.status.setText("Status: journal folder missing (set in Settings)")
                return
            QTimer.singleShot(0, lambda: self.start_watching(silent=True))
        except Exception:
            pass

    def _on_min_value_changed(self, v: int):
        # persist immediately
        try:
            self.cfg.min_planet_value_100k = int(v)
            self.cfg_store.save(self.cfg)
        except Exception:
            pass
        self.status.setText("Status: settings saved")
        self._refresh_exploration()

    def _on_exo_min_changed(self, v: int):
        # persist immediately
        try:
            self.cfg.exo_high_value_m = int(v)
            self.cfg_store.save(self.cfg)
        except Exception:
            pass
        self.status.setText("Status: settings saved")
        self._refresh_hud()
        self._refresh_exobiology()

    def _browse_journal_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Elite Dangerous Journal Folder")
        if folder:
            self.settings_journal_edit.setText(folder)
            self._on_settings_journal_changed()

    def _on_settings_journal_changed(self):
        path = (self.settings_journal_edit.text() or "").strip()
        self.cfg.journal_dir = path if path else None
        try:
            self.cfg_store.save(self.cfg)
        except Exception:
            pass
        self.status.setText("Status: settings saved")

    def _on_overview_action_link(self, link: str):
        self.overview_panel._on_overview_action_link(link)

    def start_watching(self, silent: bool = False):
        if not self.cfg.journal_dir:
            if not silent:
                QMessageBox.warning(self, "Missing setting", "Set your Journal folder in Settings first.")
            else:
                self.status.setText("Status: missing journal folder (set in Settings)")
            return
        journal_path = Path(self.cfg.journal_dir)
        if not journal_path.exists():
            if not silent:
                QMessageBox.warning(self, "Invalid folder", "That folder doesn't exist.")
            else:
                self.status.setText("Status: journal folder invalid (set in Settings)")
            return
        # Stop any existing watcher cleanly
        self.stop_watching()
        status_path = journal_path / "Status.json"
        self.watcher_controller.start_watching(journal_path, status_path)
        self.status.setText(f"Status: watching {journal_path}")
        self._append(f"Started watching: {journal_path}")
        self._append(f"Started watching status: {status_path}")

    def _pp_state_category(self, pp_state: str, friendly: bool):
        s = (pp_state or "").lower()
        if "unoccupied" in s or "expansion" in s:
            return "Acquisition"
        if friendly:
            return "Reinforcing"
        return "Undermining"
    
    def stop_watching(self):
        self.watcher_controller.stop_watching()

    def closeEvent(self, event):
        self.stop_watching()
        super().closeEvent(event)

    def _on_status(self, msg: str):
        self.status.setText(f"Status: {msg}")
        self._append(msg)

    def _on_error(self, msg: str):
        self._append(f"[ERROR] {msg}")

    def _on_event(self, evt: dict):
        name = evt.get("event", "UNKNOWN")
        self._append(f"[EVENT] {name}")

        old_system_address = getattr(self.state, "system_address", None)
        state, msgs = self.engine.process(evt)
        self.state = state

        if name in (
            "Bounty",
            "RedeemVoucher",
            "Scan",
            "MultiSellExplorationData",
            "SellExplorationData",
            "ScanOrganic",
            "SellOrganicData",
        ):
            self._save_session_ledger()

        incoming_system_address = evt.get("SystemAddress")

        if name in ("Location", "FSDJump"):
            if isinstance(incoming_system_address, int) and incoming_system_address != old_system_address:
                self.state.system_address = incoming_system_address
                self.load_current_system_data()
                self._refresh_hud()
                self._refresh_exploration()

        if name == "StartJump" and evt.get("JumpType") == "Hyperspace":
            self._clear_all_panels()

        for m in msgs:
            if m == "refresh_powerplay":
                self._refresh_powerplay()
            else:
                self._append(m)

        if name != "StartJump":
            self._schedule_hud_refresh()

        # Refresh PowerPlay panel when relevant events occur
        if name in ("Location", "FSDJump", "Powerplay", "PowerplayState"):
            self._refresh_powerplay()

        # Refresh exploration panel when signal or scan data arrives
        if name in ("FSSSignalDiscovered", "FSSDiscoveryScan", "SAASignalsFound"):
            self._refresh_exploration()

    def _schedule_hud_refresh(self):
        """Coalesce multiple rapid journal events into a single UI refresh."""
        try:
            if self._hud_refresh_pending:
                return
            self._hud_refresh_pending = True

            # 75ms feels "live" but avoids thrashing during FSS/DSS bursts.
            self._hud_refresh_timer.start(75)
        except Exception:
            # Worst case: fall back to immediate refresh
            self._hud_refresh_pending = False
            try:
                self._refresh_hud()
            except Exception:
                log.exception("UI refresh error (fallback)")

    def _do_hud_refresh(self):
        """Timer callback for the debounced HUD refresh."""
        self._hud_refresh_pending = False
        try:
            self._refresh_hud()
        except Exception:
            log.exception("UI refresh error")

    def _derive_pp_action(self, pledged, ctrl, pp_state, powers):
        return self.powerplay_panel.derive_pp_action(
            pledged, ctrl, pp_state, powers
        )

    def _format_poi_line(self, poi: Dict[str, Any]) -> str:
        """One-line, low-noise POI formatting for HUD."""
        try:
            title = fmt.text(poi.get("title") or "POI", default="POI")
            body = fmt.text(poi.get("body") or "", default="")
            note = fmt.text(poi.get("note") or "", default="")
            cat = fmt.text(poi.get("category") or "", default="")
            bits = []
            if cat:
                bits.append(cat)
            bits.append(title)
            if body:
                bits.append(f"@ {body}")
            line = " — ".join([" ".join(bits[:2]).strip(), " ".join(bits[2:]).strip()]).strip(" —")
            if note:
                line = f"{line} — {note}"
            return line.strip()
        except Exception:
            return ""

    def _format_farm_line(self, farm: Dict[str, Any]) -> str:
        """One-line, low-noise farming formatting for HUD."""
        try:
            name = fmt.text(farm.get("name") or "Farming", default="Farming")
            body = fmt.text(farm.get("body") or "", default="")
            method = fmt.text(farm.get("method") or "", default="")
            mats = farm.get("key_materials") or farm.get("materials") or []
            mats_txt = ""
            if isinstance(mats, list):
                top = [fmt.text(x, default="") for x in mats][:2]
                top = [x for x in top if x]
                if top:
                    mats_txt = ", ".join(top)
            bits = [name]
            if body:
                bits.append(f"@ {body}")
            if method:
                bits.append(method)
            line = " — ".join([b for b in bits if b])
            if mats_txt:
                line = f"{line} (e.g. {mats_txt})"
            return line.strip()
        except Exception:
            return ""

    def _maybe_add_system_intel_hints(self, lines: List[str]) -> None:
        """Add POI/Farming hints once per system change (non-spammy)."""
        try:
            sys_name = fmt.text(getattr(self.state, "system", None), default="").strip()
            sys_addr = getattr(self.state, "system_address", None)
            addr_key = str(sys_addr) if isinstance(sys_addr, int) else ""
            if not sys_name:
                return

            system_key = f"{sys_name}|{addr_key}"
            if system_key == self._last_intel_system_key:
                return
            self._last_intel_system_key = system_key

            pois = self.external_intel.get_pois(sys_name, sys_addr if isinstance(sys_addr, int) else None) or []
            farms = self.farming_locations.get_for_system(sys_name) if sys_name else []

            poi_lines = []
            if isinstance(pois, list):
                for p in pois[:3]:
                    if isinstance(p, dict):
                        s = self._format_poi_line(p)
                        if s:
                            poi_lines.append(s)

            farm_lines = []
            if isinstance(farms, list):
                for f in farms[:2]:
                    if isinstance(f, dict):
                        s = self._format_farm_line(f)
                        if s:
                            farm_lines.append(s)

            if poi_lines:
                lines.append(f"📌 POI: {poi_lines[0]}")
                for extra in poi_lines[1:]:
                    lines.append(f"   ↳ {extra}")

            if farm_lines:
                lines.append(f"⛏️ Farming: {farm_lines[0]}")
                for extra in farm_lines[1:]:
                    lines.append(f"   ↳ {extra}")
        except Exception:
            log.exception("Failed to add system intel hints")

    def _refresh_hud(self):
        parts = []
        lines = []
        self._pp_action_text = ""
        action_state = self._compute_action_state()
        if (
            self.state.commander
            or self.state.ship
            or self.state.credits is not None
            or self.state.system
        ):
            parts.append(f"CMDR {self.state.commander or '?'}")
        if self.state.ship:
            parts.append(f"Ship: {self.state.ship}")
        if self.state.credits is not None:
            parts.append(f"Credits: {fmt.credits(self.state.credits, default='?')}")
        if self.state.system:
            if getattr(self.state, "in_hyperspace", False):
                sc = getattr(self.state, "jump_star_class", None)
                if sc:
                    parts.append(f"Jumping to: {self.state.system} ({sc})")
                else:
                    parts.append(f"Jumping to: {self.state.system}")
            else:
                parts.append(f"System: {self.state.system}")

        if self.state.pp_power:
            # Keep it compact
            pr = self.state.pp_rank if self.state.pp_rank is not None else "?"
            me = self.state.pp_merits if self.state.pp_merits is not None else "?"
            parts.append(f"PP: {self.state.pp_power} (R{pr} M{me})")
        if self.state.last_event:
            parts.append(f"Last: {self.state.last_event}")
        if parts:
            lines.append(" | ".join(parts))

        # PowerPlay: one-line "what can I do here?" hint (only if pledged and PP context exists)
        try:
            pledged = getattr(self.state, "pp_power", None)
            ctrl = getattr(self.state, "system_controlling_power", None)
            pp_state = getattr(self.state, "system_powerplay_state", None) or ""
            reinforce = getattr(self.state, "system_powerplay_reinforcement", None)
            undermine = getattr(self.state, "system_powerplay_undermining", None)
            progress = getattr(self.state, "system_powerplay_control_progress", None)
            powers = getattr(self.state, "system_powers", None) or []

            action = self._derive_pp_action(pledged, ctrl, pp_state, powers)
            if action:
                self._pp_action_text = f"PP Action: {action}"
        except Exception:
            pass

        # Ensure PowerPlay tab updates whenever HUD refreshes
        try:
            self._refresh_powerplay()
        except Exception:
            pass

        # ---- Update session tracker ----
        try:
            kills = getattr(self.state, "session_kills", 0)
            combat_session = int(getattr(self.state, "combat_session_collected", 0) or 0)
            combat_unsold = int(getattr(self.state, "combat_unsold_total", 0) or 0)

            exploration_session = int(getattr(self.state, "exploration_session_collected_est", 0) or 0)
            exploration_unsold = int(getattr(self.state, "exploration_unsold_total_est", 0) or 0)

            exo_session = int(getattr(self.state, "exobiology_session_collected_est", 0) or 0)
            exo_unsold = int(getattr(self.state, "exobiology_unsold_total_est", 0) or 0)

            pp_merits_session = int(
                getattr(self.state, "pp_merits_session", 0) or 0
            )

            pp_line = ""
            if pp_merits_session > 0:
                pp_line = (
                    f"<br><span style='color:#DDA0DD;'>"
                    f"PP Merits: +{pp_merits_session:,}</span>"
                )

            pp_merits_session = int(
                getattr(self.state, "pp_merits_session", 0) or 0
            )
            pp_line = ""
            if pp_merits_session > 0:
                pp_line = (
                    f"<br><span style='color:#DDA0DD;'>"
                    f"PP Merits: +{pp_merits_session:,}</span>"
                )

            self.session_panel.setText(
                "Session<br>"
                f"Kills: {kills}<br>"
                f"<span style='color:#FF8C66;'>Combat: {combat_session:,} cr</span><br>"
                f"<span style='color:#FFB199;'>Combat Unsold: {combat_unsold:,} cr</span><br>"
                f"<span style='color:#87CEFA;'>Exploration: {exploration_session:,} cr</span><br>"
                f"<span style='color:#B7E3FF;'>Expl. Unsold: {exploration_unsold:,} cr</span><br>"
                f"<span style='color:#7CFC98;'>Exobio: {exo_session:,} cr</span><br>"
                f"<span style='color:#BDFCC9;'>Exo Unsold: {exo_unsold:,} cr</span>"
                f"{pp_line}"
            )

        except Exception:
            pass

        # ---- Update route tracker ----
        try:
            if not getattr(self.state, "in_hyperspace", False):
                route_target = getattr(self.state, "route_target_system", None)
                route_star_class = getattr(self.state, "route_target_star_class", None)
                route_jumps = getattr(self.state, "route_remaining_jumps", None)

                target_txt = route_target if isinstance(route_target, str) and route_target.strip() else "-"
                star_label, star_color = self._get_star_class_label_and_color(route_star_class)
                jumps_txt = str(route_jumps) if isinstance(route_jumps, int) else "-"

                if star_label:
                    next_line = (
                        f"Next: {target_txt} "
                        f"(<span style='color:{star_color};'>{star_label}</span>)"
                    )
                else:
                    next_line = f"Next: {target_txt}"

                self.route_panel.setText(
                    "Route<br>"
                    f"{next_line}<br>"
                    f"Jumps: {jumps_txt}"
                )
        except Exception:
            pass

        # PowerPlay status + action (ONLY if PP context exists in this system)
        try:
            pledged = self.state.pp_power
            ctrl = getattr(self.state, "system_controlling_power", None)
            pp_state = getattr(self.state, "system_powerplay_state", None)
            pw = getattr(self.state, "system_powers", None) or []
            prog = getattr(self.state, "system_powerplay_conflict_progress", None) or {}

            has_pp_context = bool(ctrl or pp_state or pw or prog)

            if pledged and has_pp_context:
                # --- Status line (HUD only) ---
                if ctrl == "Unoccupied":
                    ptxt = ", ".join([p for p in pw[:3] if isinstance(p, str)])
                    extra = f" | Powers: {ptxt}" if ptxt else ""
                    lines.append(f"🟡 PP: Neutral ({ctrl}) — {pp_state or 'Active'}{extra}")
                elif ctrl and ctrl == pledged:
                    lines.append(f"🟢 PP: Friendly space ({ctrl}) — {pp_state or 'Active'}")
                elif ctrl and ctrl != pledged:
                    lines.append(f"🔴 PP: Enemy-Controlled ({ctrl}) — {pp_state or 'Active'} (caution)")
                else:
                    ptxt = ", ".join([p for p in pw[:3] if isinstance(p, str)])
                    extra = f" | Powers: {ptxt}" if ptxt else ""
                    lines.append(f"🟡 PP: {pp_state or 'Active'}{extra}")

                # --- Action hint (Overview only) ---
                s = str(pp_state or "").lower()
                friendly = bool(ctrl and ctrl == pledged)
                enemy = bool(ctrl and ctrl != pledged and ctrl != "Unoccupied")

                action = None
                if "stronghold" in s or "fortified" in s:
                    if friendly:
                        action = "Fortify"
                    elif enemy:
                        action = "Enemy Stronghold"
                elif "contested" in s or "conflict" in s:
                    action = "Conflict ongoing"
                elif "unoccupied" in s:
                    if pledged in pw:
                        action = "Unoccupied"

                if action:
                    # Keep formatting consistent with the earlier PP action text.
                    if not self._pp_action_text:
                        self._pp_action_text = f"PP Action: {action}"
        except Exception:
            pass

        cgs = getattr(self.state, "community_goals", {}) or {}
        active = []
        for _cgid, rec in cgs.items():
            if not isinstance(rec, dict):
                continue
            if rec.get("IsComplete"):
                continue
            if rec.get("Title"):
                active.append(rec)
        if active:
            # Prefer the most recently joined CG if present
            prefer = getattr(self.state, "last_cg_joined", None)
            chosen = None
            if isinstance(prefer, int):
                chosen = cgs.get(prefer)
            if not isinstance(chosen, dict) or not chosen.get("Title") or chosen.get("IsComplete"):
                chosen = active[0]

            title = chosen.get("Title", "Community Goal")
            sysn = chosen.get("SystemName")
            mkt = chosen.get("MarketName")
            exp = chosen.get("Expiry")
            tier = chosen.get("TierReached")
            top = chosen.get("TopTierName")
            pc = chosen.get("PlayerContribution")

            loc = " — ".join([x for x in [sysn, mkt] if x])
            tier_txt = "/".join([x for x in [tier, top] if x])
            pc_txt = f"{pc:,}" if isinstance(pc, int) else "?"

            # Convert expiry timestamp to "Ends in Xd Yh"
            ends_txt = ""
            try:
                if isinstance(exp, str) and exp.endswith("Z"):
                    from datetime import datetime, timezone

                    expiry_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
                    now = datetime.now(timezone.utc)
                    remaining = expiry_dt - now

                    if remaining.total_seconds() > 0:
                        days = remaining.days
                        hours = int((remaining.seconds) / 3600)
                        if days > 0:
                            ends_txt = f"{days}d {hours}h"
                        else:
                            ends_txt = f"{hours}h"
            except Exception:
                ends_txt = ""

            percentile = chosen.get("PlayerPercentileBand")
            percentile_txt = f"Top {percentile}%" if isinstance(percentile, int) else ""
        
            bits = [f"CG: {title}"]
            if loc:
                bits.append(loc)
            bits.append(f"You {pc_txt}")
            if percentile_txt:
                bits.append(percentile_txt)
            if ends_txt:
                bits.append(f"Ends in {ends_txt}")
            lines.append(" | ".join(bits))

        # One-line "action hints" (what's worth doing in THIS system)
        try:
            min_100k = int(getattr(self.cfg, "min_planet_value_100k", 10) or 10)
        except Exception:
            min_100k = 10
        min_value = min_100k * 100_000
        fss_value = max(300_000, int(min_value * 0.20))

        try:
            exo_m = int(getattr(self.cfg, "exo_high_value_m", 2) or 2)
        except Exception:
            exo_m = 2
        exo_min = exo_m * 1_000_000

        # keep labels in sync
        try:
            self.exo_min_label.setText(f"{exo_m}M")
        except Exception:
            pass

        # Build genus -> max known species value map (from exo_values.json)
        genus_max_value = {}
        if self.exo_values:
            for rec in self.exo_values.by_species.values():
                g = rec.genus
                v = rec.base_value
                if isinstance(g, str) and isinstance(v, int):
                    prev = genus_max_value.get(g)
                    if prev is None or v > prev:
                        genus_max_value[g] = v
        if action_state["exploration"]:
            lines.append(action_state["exploration"])


        # Exobiology: split "bio signals exist" vs "we have real exobio targets/values"
        # Bio signals from FSS may not include genus until DSS/mapping events arrive.
        bio_need_dss = 0
        for _body, rec in (self.state.bodies or {}).items():
            if not isinstance(rec, dict):
                continue
            bio = rec.get("BioSignals", 0) or 0
            gen = rec.get("BioGenuses", []) or []
            if isinstance(bio, int) and bio > 0 and not gen:
                bio_need_dss += 1

        if action_state["exobiology"]:
            lines.extend(action_state["exobiology"])

        # DSS-confirmed genus → possible high-value exo (potential, not guaranteed)
        dss_hv_genus_bodies = 0
        for _body, rec in (self.state.bodies or {}).items():
            if not isinstance(rec, dict):
                continue
            gen = rec.get("BioGenuses", []) or []
            if not gen:
                continue
            for g in gen:
                max_v = genus_max_value.get(g)
                if isinstance(max_v, int) and max_v >= exo_min:
                    dss_hv_genus_bodies += 1
                    break

        if dss_hv_genus_bodies:
            lines.append(
                f"🔬 Action: {dss_hv_genus_bodies} bodies with possible high-value exo genus (DSS confirmed, ≥ {exo_m}M)"
            )

        # Only count "high value exo" when we have ScanOrganic-derived records (values may exist)
        exo_incomplete = 0
        exo_hv_incomplete = 0
        for _k, rec in (self.state.exo or {}).items():
            if not isinstance(rec, dict):
                continue
            last = (rec.get("LastScanType") or "").upper()
            if last == "CODEX":
                continue
            if rec.get("Complete"):
                continue
            exo_incomplete += 1
            base_v = rec.get("BaseValue")
            pot_v = rec.get("PotentialValue")
            hv = base_v if isinstance(base_v, int) else (pot_v if isinstance(pot_v, int) else None)
            if isinstance(hv, int) and hv >= exo_min:
                exo_hv_incomplete += 1

        if exo_incomplete:
            lines.append(f"🔬 Action: {exo_hv_incomplete} high-value exo incomplete (≥ {exo_m}M) | {exo_incomplete} exo incomplete")

        # Journal-derived system signals (NonBodyCount + discovered signal list)
        try:
            total = getattr(self.state, "system_body_count", None)
            resolved = len(getattr(self.state, "resolved_body_ids", set()) or set())
            fss_complete = getattr(self.state, "fss_complete", False)
            if isinstance(total, int) and not fss_complete and total > resolved:
                remaining = total - resolved
                lines.append(f"🔎 Action: {remaining} bodies unresolved (FSS)")
        except Exception:
            pass

        # Low-noise “POI-like” cues: surface only when we have discovered notable phenomena / megaships (journal-derived)
        try:
            sigs = getattr(self.state, "system_signals", None) or []
            phen = 0
            mega = 0
            tour = 0
            for s in sigs:
                if not isinstance(s, dict):
                    continue
                if s.get("Category") == "Phenomena":
                    phen += 1
                if s.get("Category") == "Megaship":
                    mega += 1
                if s.get("Category") == "TouristBeacon":
                    tour += 1
            if phen:
                lines.append(f"✨ Action: Stellar phenomena discovered ({phen})")
            if mega:
                lines.append(f"🚢 Action: Megaship signals discovered ({mega})")
            if tour:
                lines.append(f"✨ Action: Tourist Beacon discovered ({tour})")
        except Exception:
            pass

        # Geological (journal-derived; useful for material farming)
        try:
            geo_bodies = 0
            for _b, n in (getattr(self.state, "geo_signals", None) or {}).items():
                if isinstance(n, int) and n > 0:
                    geo_bodies += 1
            if geo_bodies:
                lines.append(f"🪨 Action: Geological signals on {geo_bodies} bodies")
        except Exception:
            pass

        # Materials shortlist (journal-derived; requires landable + Geo; improves “what do I land on first?”)
        try:
            mat_targets = 0
            mat_scanned = 0
            for _body, rec in (self.state.bodies or {}).items():
                if not isinstance(rec, dict):
                    continue
                landable = rec.get("Landable")
                if landable is not True:
                    continue
                geo = rec.get("GeoSignals", 0) or 0
                if not (isinstance(geo, int) and geo > 0):
                    continue
                mat_targets += 1

                mats = rec.get("Materials") or {}
                if isinstance(mats, dict) and any(isinstance(v, (int, float)) for v in mats.values()):
                    mat_scanned += 1

            if mat_targets > 0:
                if mat_scanned > 0:
                    lines.append(f"⛏️ Action: Materials shortlist ready ({mat_scanned}/{mat_targets} targets scanned)")
                else:
                    lines.append(f"⛏️ Action: Materials targets available ({mat_targets} landable geo) — scan bodies")
        except Exception:
            pass

        # Low-inventory RAW mats available in THIS system (journal-derived; requires Scan.Materials)
        try:
            low_threshold = 25
            inv_raw = getattr(self.state, "materials_raw", {}) or {}
            low_raw = set()
            if isinstance(inv_raw, dict):
                for k, v in inv_raw.items():
                    if isinstance(k, str) and isinstance(v, int) and v <= low_threshold:
                        low_raw.add(k.strip().lower())

            avail_keys = []
            if low_raw:
                for _body, rec in (self.state.bodies or {}).items():
                    if not isinstance(rec, dict):
                        continue
                    if rec.get("Landable") is not True:
                        continue
                    geo = rec.get("GeoSignals", 0) or 0
                    if not (isinstance(geo, int) and geo > 0):
                        continue
                    mats = rec.get("Materials") or {}
                    if not isinstance(mats, dict):
                        continue
                    for mk, pct in mats.items():
                        if not isinstance(mk, str) or not isinstance(pct, (int, float)):
                            continue
                        mk2 = mk.strip().lower()
                        if mk2 in low_raw and mk2 not in avail_keys:
                            avail_keys.append(mk2)

            if avail_keys:
                mats_loc = getattr(self.state, "materials_localised", {}) or {}
                names = []
                for key in avail_keys[:4]:
                    disp = mats_loc.get(key) if isinstance(mats_loc, dict) else None
                    disp = disp or key.replace("_", " ").title()
                    names.append(disp)
                tail = "…" if len(avail_keys) > 4 else ""
                lines.append(f"🧩 Action: Low RAW mats available in-system ({', '.join(names)}{tail})")
        except Exception:
            pass

        # Low materials inventory (journal-derived; independent of any planner)
        try:
            low_threshold = 25
            total_zero = 0
            total_low = 0
            for src_name in ("materials_raw", "materials_manufactured", "materials_encoded"):
                src = getattr(self.state, src_name, {}) or {}
                if not isinstance(src, dict):
                    continue
                for _k, v in src.items():
                    if not isinstance(v, int):
                        continue
                    if v == 0:
                        total_zero += 1
                    if v <= low_threshold:
                        total_low += 1
            if total_low > 0:
                lines.append(f"🧰 Action: Low materials stock (≤{low_threshold}) — {total_low} items ({total_zero} zero)")
        except Exception:
            pass

        # System-entry advisory hints (POIs + farming), once per system change
        self._maybe_add_system_intel_hints(lines)

        # Mirror only the action lines into Overview (clickable links to tabs)
        try:
            contact_lines = []
            action_lines = []
            intel_lines = []
            poi_lines = []
            seen = set()
            has_pp_action = False
            # PP enemy scan alerts (Overview only)
            # Contact Alert
            try:
                for alert in (getattr(self.state, "pp_enemy_alerts", None) or []):
                    if not isinstance(alert, dict):
                        continue
                    msg = alert.get("msg", "")
                    if msg and msg not in seen:
                        seen.add(msg)
                        contact_lines.append(
                            f'<span style="color:#FF4444;">⚠ {msg}</span>'
                        )
            except Exception:
                pass

            for ln in (lines or []):
                if not isinstance(ln, str) or not ln.strip():
                    continue
                if ln in seen:
                    continue
                seen.add(ln)
                ll = ln.lower()
                if "action:" in ll:
                    action_lines.append(ln)
                elif "intel:" in ll or "poi:" in ll:
                    intel_lines.append(ln)

            # PP action line
            pp_txt = getattr(self, "_pp_action_text", "") or ""
            if pp_txt:
                has_pp_action = True

            final_lines = []
            if contact_lines:
                final_lines.extend(contact_lines[:3])
            if action_lines:
                final_lines.extend(action_lines[:6])
            if intel_lines:
                final_lines.extend(intel_lines[:4])
            if has_pp_action:
                final_lines.append(pp_txt)

            self._animate_overview_update("<br>".join(final_lines))
        except Exception:
            pass

        # HUD should NOT duplicate Overview action lines; keep "Action:" hints in Overview only.
        hud_lines = []
        for ln in (lines or []):
            if not isinstance(ln, str):
                continue
            if ln.startswith("🌍 Action:") or ln.startswith("🔬 Action:") or ln.startswith("🧬 Action:") or ln.startswith("🛡️") or ln.startswith("🔎 Action:") or ln.startswith("🪨 Action:") or ln.startswith("⛏️ Action:") or ln.startswith("✨ Action:") or ln.startswith("🧩 Action:") or ln.startswith("📌 Intel:"):                continue
            hud_lines.append(ln)
        # Suppress Action lines from HUD (they belong in Overview panel)
        clean_lines = [ln for ln in lines if "Action:" not in ln]
        self.hud.setText("\n".join(clean_lines) if clean_lines else "Not connected")
        self._refresh_system_card()
        self._refresh_exploration()
        self._refresh_exobiology()
        self._refresh_powerplay()
        self._refresh_combat()
        self._refresh_intel()
        self._refresh_materials_inventory()
        self._refresh_shiplocker_inventory()

    def _animate_overview_update(self, html: str):
        self.overview_panel.animate_overview_update(html)

    def _refresh_shiplocker_inventory(self):
        self.shiplocker_panel.refresh(self.state, self.item_catalog)

    def _refresh_materials_inventory(self):
        self.materials_panel.refresh(self.state, self.item_catalog)

    def _refresh_intel(self):
        self.intel_panel.refresh(self.state, self.farming_locations)

    def _refresh_combat(self):
        self.combat_panel.refresh(self.state)

    def _refresh_powerplay(self):
        self.powerplay_panel.refresh(self.state, self.pp_activities)

    def _refresh_exobiology(self):
        self.exobiology_panel.refresh(
            self.state, self.cfg, self.exo_values
        )

    def _refresh_exploration(self):
        self.exploration_panel.refresh(
            self.state, self.cfg, self.planet_values
        )

    def _refresh_materials_shortlist(self):
        self.exploration_panel._refresh_materials_shortlist(self.state)

    def _norm_token(self, value):
        """Normalize Frontier-style token strings for display.

        Examples:
        '$SYSTEM_SECURITY_low;' -> 'Low'
        '$economy_Extraction;'  -> 'Extraction'
        '$government_Corporate;' -> 'Corporate'
        """
        s = fmt.text(value)
        if not s:
            return ""
        s = s.strip()
        if s.endswith(";"):
            s = s[:-1].strip()
        if s.startswith("$"):
            s = s[1:]
        # Drop common token prefixes, keep the meaningful tail
        if "_" in s:
            parts = [p for p in s.split("_") if p]
            if parts:
                s = parts[-1]
        s = s.replace("_", " ").strip()
        if not s:
            return ""
        # Preserve ALLCAPS abbreviations, otherwise Title-case first letter only
        if s.isupper():
            return s
        return s[:1].upper() + s[1:]

    def _refresh_system_card(self):
        self.overview_panel.refresh(self.state)

    def _clear_all_panels(self):
        """Clear all system-specific UI panels on jump."""
        try:
            self.overview_panel.refresh(self.state)
        except Exception:
            pass
        try:
            self.exploration_panel.refresh(
                self.state, self.cfg, self.planet_values
            )
        except Exception:
            pass
        try:
            self.exobiology_panel.refresh(
                self.state, self.cfg, self.exo_values
            )
        except Exception:
            pass
        try:
            self.combat_panel.refresh(self.state)
        except Exception:
            pass
        try:
            self.powerplay_panel.refresh(self.state, self.pp_activities)
        except Exception:
            pass
        try:
            self.intel_panel.refresh(
                self.state, self.farming_locations
            )
        except Exception:
            pass

    def _compute_action_state(self):
        """
        Single authority for all 'Action:' decisions.
        Returns a dict with preformatted action strings or None.
        """
        out = {
            "exploration": None,
            "exobiology": [],
        }

        try:
            min_100k = int(getattr(self.cfg, "min_planet_value_100k", 10) or 10)
            if min_100k < 0:
                min_100k = 0
            min_value = min_100k * 100_000

            exo_m = int(getattr(self.cfg, "exo_high_value_m", 2) or 2)
            exo_min = exo_m * 1_000_000
        except Exception:
            return out

        hv_unmapped = 0
        tf_unmapped = 0
        bio_need_dss = 0

        genus_max = {}
        if self.exo_values:
            for rec in self.exo_values.by_species.values():
                g = rec.genus
                v = rec.base_value
                if isinstance(g, str) and isinstance(v, int):
                    genus_max[g] = max(v, genus_max.get(g, 0))

        for _body, rec in (self.state.bodies or {}).items():
            if not isinstance(rec, dict):
                continue

            est = rec.get("EstimatedValue")
            dss_mapped = bool(rec.get("DSSMapped", False)) or bool(rec.get("BioGenuses"))
            tf = bool(rec.get("Terraformable", False))

            bio = rec.get("BioSignals", 0) or 0
            gen = rec.get("BioGenuses", []) or []

            if tf and not dss_mapped:
                tf_unmapped += 1

            if isinstance(est, int) and est >= min_value and not dss_mapped:
                hv_unmapped += 1

            if isinstance(bio, int) and bio > 0 and not gen:
                bio_need_dss += 1

        if hv_unmapped > 0 or tf_unmapped > 0:
            out["exploration"] = (
                f"🌍 Action: {hv_unmapped} bodies worth mapping (FSS) | {tf_unmapped} TF unmapped"
            )

        if bio_need_dss > 0:
            out["exobiology"].append(
                f"🔬 Action: {bio_need_dss} bodies have bio signals — DSS/map to reveal genus"
            )

        dss_hv = 0
        for _body, rec in (self.state.bodies or {}).items():
            gen = rec.get("BioGenuses", []) or []
            for g in gen:
                if genus_max.get(g, 0) >= exo_min:
                    dss_hv += 1
                    break

        if dss_hv > 0:
            out["exobiology"].append(
                f"🔬 Action: {dss_hv} bodies with possible high-value exo genus (≥ {exo_m}M)"
            )

        return out

    def _append(self, text: str):
        self.log_box.append(text)
        # Keep the UI log bounded (long play sessions otherwise grow unbounded).
        try:
            doc = self.log_box.document()
            max_blocks = 2000
            excess = doc.blockCount() - max_blocks
            if excess > 0:
                cur = QTextCursor(doc)
                cur.movePosition(QTextCursor.MoveOperation.Start)
                # Remove oldest blocks first
                for _ in range(excess):
                    cur.select(QTextCursor.SelectionType.BlockUnderCursor)
                    cur.removeSelectedText()
                    cur.deleteChar()  # remove the newline after the block
        except Exception:
            pass
