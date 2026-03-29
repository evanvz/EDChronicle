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

        self.overview_actions = QLabel("")
        self.overview_actions.setWordWrap(True)
        self.overview_actions.setTextFormat(Qt.TextFormat.RichText)
        self.overview_actions.setOpenExternalLinks(False)
        self.overview_actions.linkActivated.connect(self._on_overview_action_link)

        # Subtle fade animation for Overview updates
        self._overview_opacity = QGraphicsOpacityEffect(self.overview_actions)
        self.overview_actions.setGraphicsEffect(self._overview_opacity)
        self._overview_opacity.setOpacity(1.0)
        self._last_overview_html = ""
        self._last_overview_lines = set()

        self.system_card = QTextEdit()
        self.system_card.setReadOnly(True)
        self.system_card.setMinimumHeight(180)

        self.factions_table = QTableWidget()
        self.factions_table.setColumnCount(6)
        self.factions_table.setHorizontalHeaderLabels(["Faction", "Government", "Allegiance", "Active", "Influence", "Rep"])
        self.factions_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.factions_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.factions_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.factions_table.verticalHeader().setVisible(False)
        self.factions_table.setShowGrid(False)
        self.factions_table.setAlternatingRowColors(True)
        self.factions_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.factions_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.factions_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.factions_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.factions_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.factions_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.factions_table.setMinimumHeight(280)

        self.exploration_table = QTableWidget()
        self.exploration_table.setColumnCount(10)
        self.exploration_table.setHorizontalHeaderLabels(
            ["Body", "Class", "LS", "Bio", "Geo", "Bio DSS", "Est. Value", "Prev Map", "DSS", "Flags"]
        )
        self.exploration_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.exploration_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.exploration_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.exploration_table.verticalHeader().setVisible(False)
        self.exploration_table.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored)
        self.exploration_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.exploration_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.exploration_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.exploration_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.exploration_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.exploration_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.exploration_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.exploration_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.exploration_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.exploration_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self.exploration_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        self.exploration_table.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeMode.ResizeToContents)
        self.exploration_table.horizontalHeader().setSectionResizeMode(9, QHeaderView.ResizeMode.ResizeToContents)
        self.exploration_table.setMinimumHeight(120)
        self.exploration_table.setSortingEnabled(False)
        self.exploration_action = QLabel("")
        self.exploration_action.setWordWrap(True)
        self.exploration_hint = QLabel("")
        self.exploration_hint.setWordWrap(True)

        self.system_signals_box = QTextEdit()
        self.system_signals_box.setReadOnly(True)
        self.system_signals_box.setMinimumHeight(120)

        self.materials_box = QTextEdit()
        self.materials_box.setReadOnly(True)
        self.materials_box.setMinimumHeight(80)

        # Intel (external / advisory)
        self.intel_summary = QLabel("")
        self.intel_summary.setWordWrap(True)
        self.intel_box = QTextEdit()
        self.intel_box.setReadOnly(True)

        # Exobiology
        self.exo_table = QTableWidget()
        self.exo_table.setColumnCount(9)
        self.exo_table.setHorizontalHeaderLabels(
            ["Body", "Genus", "Species", "Variant", "Potential", "Base Value", "Samples", "CCR", "Status"]
        )
        self.exo_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.exo_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.exo_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.exo_table.verticalHeader().setVisible(False)
        self.exo_table.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored)
        self.exo_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.exo_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.exo_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.exo_table.setSortingEnabled(False)
        self.exo_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.exo_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.exo_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.exo_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)  # Variant
        self.exo_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)  # Potential
        self.exo_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)  # Base Value
        self.exo_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)  # Samples
        self.exo_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)  # CCR
        self.exo_table.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeMode.ResizeToContents)  # Status
        self.exo_table.setMinimumHeight(120)
        self.exo_action = QLabel("")
        self.exo_action.setWordWrap(True)
        self.exo_hint = QLabel("")
        self.exo_hint.setWordWrap(True)

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
        tab_overview = QWidget()
        ov = QVBoxLayout(tab_overview)
        ov.addWidget(self.overview_actions)
        top_label = QLabel("System")
        bottom_label = QLabel("Factions (top by influence)")
        top_label.setContentsMargins(0, 0, 0, 0)
        bottom_label.setContentsMargins(0, 0, 0, 0)

        top_panel = QWidget()
        top_l = QVBoxLayout(top_panel)
        top_l.setContentsMargins(0, 0, 0, 0)
        top_l.addWidget(top_label)
        top_l.addWidget(self.system_card)

        bottom_panel = QWidget()
        bot_l = QVBoxLayout(bottom_panel)
        bot_l.setContentsMargins(0, 0, 0, 0)
        bot_l.addWidget(bottom_label)
        bot_l.addWidget(self.factions_table)

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(top_panel)
        split.addWidget(bottom_panel)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 7)
        split.setSizes([140, 520])
        ov.addWidget(split)

        self.stack.addWidget(tab_overview)
        self.sidebar.addItem("Overview")

        # Exploration tab
        tab_explore = QWidget()
        ex = QVBoxLayout(tab_explore)
        ex.setContentsMargins(0, 0, 0, 0)

        # ===== HEADER STRIP =====
        header_panel = QWidget()
        header_layout = QVBoxLayout(header_panel)
        header_layout.setContentsMargins(8, 8, 8, 4)
        header_layout.addWidget(QLabel("Exploration (scans → instant estimate)"))
        header_layout.addWidget(self.exploration_action)

        ex.addWidget(header_panel, 0)

        # ===== RIGHT VERTICAL SPLIT =====
        self.expl_right_split = QSplitter(Qt.Orientation.Vertical)

        signals_panel = QWidget()
        signals_layout = QVBoxLayout(signals_panel)
        signals_layout.setContentsMargins(8, 8, 8, 8)
        signals_layout.addWidget(QLabel("System signals (FSS)"))
        signals_layout.addWidget(self.system_signals_box)

        materials_panel = QWidget()
        materials_layout = QVBoxLayout(materials_panel)
        materials_layout.setContentsMargins(8, 8, 8, 8)
        materials_layout.addWidget(QLabel("Materials shortlist (landable + Geo signals)"))
        materials_layout.addWidget(self.materials_box)

        self.expl_right_split.addWidget(signals_panel)
        self.expl_right_split.addWidget(materials_panel)
        self.expl_right_split.setStretchFactor(0, 1)
        self.expl_right_split.setStretchFactor(1, 1)
        self.expl_right_split.setChildrenCollapsible(False)

        # ===== MAIN HORIZONTAL SPLIT =====
        self.expl_outer_split = QSplitter(Qt.Orientation.Horizontal)
        self.expl_outer_split.addWidget(self.exploration_table)
        self.expl_outer_split.addWidget(self.expl_right_split)
        self.expl_outer_split.setStretchFactor(0, 1)
        self.expl_outer_split.setStretchFactor(1, 1)
        self.expl_outer_split.setChildrenCollapsible(False)

        ex.addWidget(self.expl_outer_split, 1)

        # ===== FOOTER =====
        ex.addWidget(self.exploration_hint, 0)

        self.stack.addWidget(tab_explore)
        self.sidebar.addItem("Exploration")

        # Exobiology tab
        tab_exo = QWidget()
        xb = QVBoxLayout(tab_exo)
        xb.addWidget(QLabel("Exobiology"))
        xb.addWidget(self.exo_action)
        xb.addWidget(self.exo_table, 1)
        self.stack.addWidget(tab_exo)
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
        tab_intel = QWidget()
        it = QVBoxLayout(tab_intel)
        it.addWidget(QLabel("Intel (External, advisory only)"))
        it.addWidget(self.intel_summary)
        it.addWidget(self.intel_box, 1)
        self.stack.addWidget(tab_intel)
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
        try:
            mapping = {
                "exploration": 1,
                "exobiology": 2,
                "powerplay": 3,
                "combat": 4,
                "intel": 5,
                "odyssey": 6,
                "materials": 7,
                "settings": 8,
                "log": 9,
            }
            idx = mapping.get(link)
            if idx is not None:
                self.sidebar.setCurrentRow(idx)
        except Exception:
            pass

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

        for m in msgs:
            if m == "refresh_powerplay":
                self._refresh_powerplay()
            else:
                self._append(m)

        self._schedule_hud_refresh()

        # Refresh PowerPlay panel when relevant events occur
        if name in ("Location", "FSDJump", "Powerplay", "PowerplayState"):
            self._refresh_powerplay()

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

            self.session_panel.setText(
                "Session<br>"
                f"Kills: {kills}<br>"
                f"<span style='color:#FF8C66;'>Combat: {combat_session:,} cr</span><br>"
                f"<span style='color:#FFB199;'>Combat Unsold: {combat_unsold:,} cr</span><br>"
                f"<span style='color:#87CEFA;'>Exploration: {exploration_session:,} cr</span><br>"
                f"<span style='color:#B7E3FF;'>Expl. Unsold: {exploration_unsold:,} cr</span><br>"
                f"<span style='color:#7CFC98;'>Exobio: {exo_session:,} cr</span><br>"
                f"<span style='color:#BDFCC9;'>Exo Unsold: {exo_unsold:,} cr</span>"
            )
        except Exception:
            pass

        # ---- Update route tracker ----
        try:
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
                    lines.append(f"🔴 PP: Enemy-controlled ({ctrl}) — {pp_state or 'Active'} (caution)")
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

            bits = [f"CG: {title}"]
            if loc:
                bits.append(loc)
            bits.append(f"You {pc_txt}")
            if ends_txt:
                bits.append(f"Ends in {ends_txt}")
            lines.append(" | ".join(bits))

        # Session ledger (gross totals for this app run)
        cod_col = int(getattr(self.state, "session_codex_collected", 0) or 0)
        cod_sold = int(getattr(self.state, "session_codex_earnings", 0) or 0)

        if cod_col > 0 or cod_sold > 0:
            lines.append(f"Codex | Collected: {cod_col:,} cr | Sold: {cod_sold:,} cr")
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
                cur = getattr(self.state, "current_contact_alert", "") or ""
                if isinstance(cur, str) and cur.strip():
                    safe = cur.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    contact_lines.append(safe)
            except Exception:
                pass
            for ln in lines:
                if not isinstance(ln, str):
                    continue
                if ln in seen:
                    continue
                seen.add(ln)

                if "Action:" in ln:
                    if ln.startswith("🧰"):
                        action_lines.append(f'<a href="materials"><span style="color:#FF8C00;">➤</span> {ln}</a>')
                    elif ln.startswith("🔬"):
                        action_lines.append(f'<a href="exobiology"><span style="color:#FF8C00;">➤</span> {ln}</a>')
                    else:
                        action_lines.append(f'<a href="exploration"><span style="color:#FF8C00;">➤</span> {ln}</a>')
                elif ln.startswith("📌 Intel:") or ln.startswith("⛏️ Intel:"):
                    intel_lines.append(f'<a href="intel">{ln}</a>')
                elif ln.startswith("📌 POI:") or ln.startswith("⛏️ Farming:"):
                    poi_lines.append(ln)
            if getattr(self, "_pp_action_text", ""):
                action_lines.append(f'<a href="powerplay">🛡️ {self._pp_action_text}</a>')

            final_lines = []

            # Keep Overview compact: only show top-priority action items here.
            max_action_lines = 5
            max_intel_lines = 2
            max_poi_lines = 2

            if contact_lines:
                final_lines.append('<span style="color:#FF8C00; font-weight:700; font-size:13px;">CONTACT</span>')
                final_lines.extend(contact_lines[:2])

            if action_lines:
                final_lines.append('<span style="color:#FF8C00; font-weight:700; font-size:13px;">ACTIONS</span>')
                final_lines.extend(action_lines[:max_action_lines])

            if intel_lines:
                final_lines.append('<span style="color:#FF8C00; font-weight:700; font-size:13px;">INTEL</span>')
                final_lines.extend(intel_lines[:max_intel_lines])

            if poi_lines:
                final_lines.append('<span style="color:#FF8C00; font-weight:700; font-size:13px;">POI</span>')
                final_lines.extend(poi_lines[:max_poi_lines])

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
        try:
            if not isinstance(html, str):
                self.overview_actions.setText(html or "")
                return

            # Split into logical lines
            new_lines = set(html.split("<br>"))

            # First render (no animation)
            if not getattr(self, "_last_overview_html", ""):
                self.overview_actions.setText(html)
                self._last_overview_html = html
                self._last_overview_lines = new_lines
                return

            # If nothing changed → do nothing
            if html == self._last_overview_html:
                return

            # Detect newly added lines
            added_lines = new_lines - getattr(self, "_last_overview_lines", set())

            # Always update content
            self.overview_actions.setText(html)

            # Only animate if something NEW was added
            if added_lines:
                self._overview_opacity.setOpacity(0.0)

                anim = QPropertyAnimation(self._overview_opacity, b"opacity")
                anim.setDuration(220)
                anim.setStartValue(0.0)
                anim.setEndValue(1.0)
                anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                anim.start()

                self._overview_anim = anim

            # Save current state
            self._last_overview_html = html
            self._last_overview_lines = new_lines

        except Exception:
            self.overview_actions.setText(html)

    def _refresh_shiplocker_inventory(self):
        self.shiplocker_panel.refresh(self.state, self.item_catalog)

    def _refresh_materials_inventory(self):
        self.materials_panel.refresh(self.state, self.item_catalog)

    def _refresh_intel(self):
        # External intel (POIs) + Farming locations (both advisory, offline)
        pois = getattr(self.state, "external_pois", None) or []
        sys_name = getattr(self.state, "system", None) or ""
        farms = self.farming_locations.get_for_system(sys_name) if sys_name else []

        lines = []
        poi_count = 0
        farm_count = 0

        # POIs
        if isinstance(pois, list) and pois:
            poi_count = len(pois)
            lines.append("External POIs (advisory)")
            for rec in pois:
                if not isinstance(rec, dict):
                    continue
                title = rec.get("title") or rec.get("name") or "POI"
                cat = rec.get("category") or ""
                body = rec.get("body") or ""
                note = rec.get("note") or rec.get("description") or ""
                src = rec.get("source") or ""
                bits = []
                if cat:
                    bits.append(f"[{cat}]")
                bits.append(str(title))
                if body:
                    bits.append(f"— {body}")
                if note:
                    bits.append(f"— {note}")
                if src:
                    bits.append(f"(src: {src})")
                lines.append(" ".join(bits))

        # Farming locations
        if isinstance(farms, list) and farms:
            farm_count = len(farms)
            if lines:
                lines.append("")
            lu = getattr(self.farming_locations, "last_updated", None)
            lu_txt = f" (updated: {lu})" if isinstance(lu, str) and lu.strip() else ""
            lines.append(f"Farming locations in-system (advisory){lu_txt}")
            for rec in farms:
                if not isinstance(rec, dict):
                    continue
                dom = rec.get("domain") or ""
                name = rec.get("name") or "Farm Site"
                body = rec.get("body") or ""
                method = rec.get("method") or ""
                mats = rec.get("key_materials") or []
                if not isinstance(mats, list):
                    mats = []
                mats_txt = ", ".join([str(x) for x in mats[:6] if isinstance(x, str) and x.strip()])
                tail = "…" if len(mats) > 6 else ""
                bits = []
                if dom:
                    bits.append(f"[{dom}]")
                bits.append(str(name))
                if body:
                    bits.append(f"— {body}")
                if method:
                    bits.append(f"— {method}")
                if mats_txt:
                    bits.append(f"— Mats: {mats_txt}{tail}")
                lines.append(" ".join(bits))

        # Summary + fallback text
        if poi_count == 0 and farm_count == 0:
            self.intel_summary.setText("No offline intel for this system.")
            self.intel_box.setPlainText(
                "Optional files:\n"
                " - settings/external_pois.json (system POIs)\n"
                " - settings/elite_farming_locations.json (farming locations)\n"
            )
            return

        bits = []
        if poi_count:
            bits.append(f"{poi_count} external POIs")
        if farm_count:
            bits.append(f"{farm_count} farming locations")
        self.intel_summary.setText(f"{' | '.join(bits)} for this system (advisory only).")
        self.intel_box.setPlainText("\n".join(lines).strip() or "No usable intel entries.")

    def _refresh_combat(self):
        self.combat_panel.refresh(self.state)

    def _refresh_powerplay(self):
        self.powerplay_panel.refresh(self.state)

    def _refresh_exobiology(self):
        # Ensure FSS-only bio targets show even if handler refactors update
        # state.bio_signals without creating/updating the corresponding body record.
        try:
            if not isinstance(self.state.bodies, dict):
                self.state.bodies = {}

            bio_map = getattr(self.state, "bio_signals", {}) or {}
            genus_map = getattr(self.state, "bio_genuses", {}) or {}
            geo_map = getattr(self.state, "geo_signals", {}) or {}

            for body_name, bio_cnt in bio_map.items():
                if not isinstance(body_name, str) or not body_name.strip():
                    continue
                rec = self.state.bodies.get(body_name)
                if not isinstance(rec, dict):
                    rec = {"BodyName": body_name, "BodyID": None}
                if isinstance(bio_cnt, int):
                    rec["BioSignals"] = bio_cnt
                if body_name in genus_map:
                    rec["BioGenuses"] = genus_map.get(body_name, []) or []
                if body_name in geo_map:
                    rec["GeoSignals"] = geo_map.get(body_name, 0) or 0
                self.state.bodies[body_name] = rec
        except Exception:
            pass

        # Show Exobiology targets as soon as BioSignals exist (FSS), even before ScanOrganic.
        has_bio_targets = False
        for _b, _rec in (self.state.bodies or {}).items():
            if not isinstance(_rec, dict):
                continue
            bio = _rec.get("BioSignals", 0) or 0
            if isinstance(bio, int) and bio > 0:
                has_bio_targets = True
                break

        if not self.state.exo and not has_bio_targets:
            self.exo_table.setRowCount(0)
            self.exo_action.setText("🔬 Exobiology: no biological signals detected in this system yet.")
            self.exo_hint.setText("Tip: Use FSS to find Biological signals, then DSS a planet to reveal genus.")
            return

        rows = []
        try:
            exo_m = int(getattr(self.cfg, "exo_high_value_m", 2) or 2)
        except Exception:
            exo_m = 2
        exo_min = exo_m * 1_000_000
        try:
            self.exo_min_label.setText(f"{exo_m}M")
        except Exception:
            pass

        active = 0
        complete = 0
        high_value = 0
        targets = 0
        scanned_species = 0

        # Genus -> max known base value (from exo_values.json)
        genus_max = {}
        try:
            if self.exo_values:
                for _rec in self.exo_values.by_species.values():
                    g = getattr(_rec, "genus", None)
                    bv = getattr(_rec, "base_value", None)
                    if isinstance(g, str) and g.strip() and isinstance(bv, int):
                        gg = g.strip()
                        genus_max[gg] = max(int(genus_max.get(gg, 0) or 0), int(bv))
        except Exception:
            genus_max = {}

        def _norm_text(v):
            try:
                return " ".join(str(v).split())
            except Exception:
                return ""

        def _variant_color(v):
            """
            Normalize "Variant" display to the short color/name part.
            Examples:
            "Stratum Tectonicas - Green" -> "Green"
            "Bacterium Cerbrus - Teal"   -> "Teal"
            "Teal"                       -> "Teal"
            """
            if not isinstance(v, str):
                return ""
            s = _norm_text(v)
            if not s:
                return ""
            if " - " in s:
                try:
                    return s.split(" - ", 1)[1].strip()
                except Exception:
                    return s
            return s

        # Normalized body-name lookup to make Codex/DSS matching resilient to whitespace/name variants.
        body_key_by_norm = {}
        try:
            for _bn in (self.state.bodies or {}).keys():
                nk = _norm_text(_bn)
                if nk and nk not in body_key_by_norm:
                    body_key_by_norm[nk] = _bn
        except Exception:
            body_key_by_norm = {}

        # BodyID -> body-name key/record lookup to keep Exobiology matching reliable even if body_id_to_name is missing.
        body_key_by_id = {}
        body_rec_by_id = {}
        try:
            for _bn, _br in (self.state.bodies or {}).items():
                if not isinstance(_br, dict):
                    continue
                bid = _br.get("BodyID")
                if isinstance(bid, int) and bid not in body_key_by_id:
                    body_key_by_id[bid] = _bn
                    body_rec_by_id[bid] = _br
        except Exception:
            body_key_by_id = {}
            body_rec_by_id = {}

        # Track which (body, genus) already has a real ScanOrganic record so we can still show remaining DSS genuses.
        real_body_genus_name = set()  # (BodyName, Genus)
        real_body_genus_id = set()    # (BodyID, Genus)

        # Track which (body, genus) is already present via CODEX so we can suppress
        # CODEX duplicates when we already have a better "real" row (ScanOrganic) or DSS target row.
        # We track both BodyID and normalized BodyName keys for robustness.
        codex_body_genus_id = set()    # (BodyID, Genus)
        codex_body_genus_name = set()  # (BodyNameNorm, Genus)

        # Track which (body, genus) already has a row emitted (real ScanOrganic OR DSS target).
        # Used to suppress CODEX duplicates when we already have a better row to show.
        listed_body_genus_name = set()  # (BodyName, Genus)
        listed_body_genus_id = set()    # (BodyID, Genus)
        # CODEX hints: allow DSS genus rows to show Species/BaseValue without adding a duplicate CODEX row.
        codex_hint_name = {}            # (BodyName, Genus) -> Species text
        codex_hint_id = {}              # (BodyID, Genus) -> Species text
        codex_hint_var_name = {}        # (BodyName, Genus) -> Variant short text
        codex_hint_var_id = {}          # (BodyID, Genus) -> Variant short text
        codex_hint_base_name = {}       # (BodyName, Genus) -> Base value (int)
        codex_hint_base_id = {}         # (BodyID, Genus) -> Base value (int)
        codex_pending = []              # list of (body_txt, rec)

        for key, rec in (self.state.exo or {}).items():
            body_id = rec.get("BodyID")
            body_name = None
            if isinstance(body_id, int):
                body_name = self.state.body_id_to_name.get(body_id) or body_key_by_id.get(body_id)
            body_txt = body_name or (f"Body {body_id}" if body_id is not None else "Unknown Body")

            genus = rec.get("Genus", "")
            species = rec.get("Species", "")
            samples = int(rec.get("Samples", 0) or 0)
            last = (rec.get("LastScanType") or "").upper()
            if last == "CODEX":
                # CODEX hint: store species text so DSS rows can display it, but don't emit a row yet.
                gk = str(genus or "").strip()
                if not gk:
                    continue
                bn = _norm_text(body_name or body_txt)
                sp = species or rec.get("CodexName") or ""
                try:
                    sp = str(sp).strip()
                except Exception:
                    sp = ""
                vv = _variant_color(rec.get("Variant") or rec.get("CodexName") or "")
                if isinstance(body_id, int):
                    codex_hint_id[(body_id, gk)] = sp
                    if vv:
                        codex_hint_var_id[(body_id, gk)] = vv
                    # Mark CODEX presence for (BodyID, Genus)
                    codex_body_genus_id.add((body_id, gk))
                if bn:
                    codex_hint_name[(bn, gk)] = sp
                    if vv:
                        codex_hint_var_name[(bn, gk)] = vv
                    # Mark CODEX presence for (BodyNameNorm, Genus)
                    codex_body_genus_name.add((bn, gk))

                # Also capture best-known base/potential value from the CODEX record for DSS rows.
                bv = rec.get("BaseValue")
                if not isinstance(bv, int):
                    bv = rec.get("PotentialValue")
                # Journal does not provide an exobio "base value" for CodexEntry; derive from exo_values.json.
                if not isinstance(bv, int):
                    nm = rec.get("CodexName") or rec.get("Species") or ""
                    if isinstance(nm, str) and nm.strip() and getattr(self, "exo_values", None):
                        key = nm.strip()
                        exo_rec = self.exo_values.by_species.get(key)
                        if exo_rec is None and " - " in key:
                            exo_rec = self.exo_values.by_species.get(key.split(" - ", 1)[0].strip())
                        if exo_rec is not None and isinstance(getattr(exo_rec, "base_value", None), int):
                            bv = exo_rec.base_value
                if isinstance(bv, int) and bv > 0:
                    if isinstance(body_id, int):
                        codex_hint_base_id[(body_id, gk)] = bv
                    if bn:
                        codex_hint_base_name[(bn, gk)] = bv
                codex_pending.append((body_txt, rec))
                continue
            else:
                status = "COMPLETE" if rec.get("Complete") else (last or "IN PROGRESS")

            pot_v = rec.get("PotentialValue")
            pot_txt = f"{pot_v:,} cr" if isinstance(pot_v, int) else ""
            base_v = rec.get("BaseValue")

            # Journal does not provide a numeric base value for ScanOrganic; derive from exo_values.json.
            if not isinstance(base_v, int):
                nm = rec.get("Variant") or rec.get("Species") or rec.get("CodexName") or ""
                if isinstance(nm, str) and nm.strip() and getattr(self, "exo_values", None):
                    key = nm.strip()
                    exo_rec = self.exo_values.by_species.get(key)
                    if exo_rec is None and " - " in key:
                        exo_rec = self.exo_values.by_species.get(key.split(" - ", 1)[0].strip())
                    if exo_rec is not None and isinstance(getattr(exo_rec, "base_value", None), int):
                        base_v = exo_rec.base_value
            base_txt = f"{base_v:,} cr" if isinstance(base_v, int) else ""

            prog_txt = f"{samples}/3" if status != "CODEX" else "0/3"
            var_txt = _variant_color(rec.get("Variant") or "")

            # CCR column (show dist/required meters, e.g. 120/250m)
            status_txt = str(status)
            ccr_txt = ""
            try:
                req = rec.get("CCRRequiredM")
                dist = rec.get("CCRDistanceM")
                if isinstance(req, int) and req > 0:
                    if not isinstance(dist, int) or dist < 0:
                        dist = 0
                    ccr_txt = f"{dist}/{req}m"
            except Exception:
                ccr_txt = ""

            # CCR column (dist/required) for real ScanOrganic-derived rows
            ccr_txt = ""
            try:
                req = rec.get("CCRRequiredM")
                dist = rec.get("CCRDistanceM")
                if isinstance(req, int) and req > 0:
                    if not isinstance(dist, int) or dist < 0:
                        dist = 0
                    ccr_txt = f"{dist}/{req}m"
            except Exception:
                ccr_txt = ""

            rows.append((samples, status, body_txt, genus, species, var_txt, pot_txt, base_txt, prog_txt, ccr_txt, status))
            scanned_species += 1

            gk = str(genus or "").strip()
            if gk:
                if isinstance(body_id, int):
                    real_body_genus_id.add((body_id, gk))
                bn = _norm_text(body_name)
                if bn:
                    real_body_genus_name.add((bn, gk))
                if isinstance(body_id, int):
                    listed_body_genus_id.add((body_id, gk))
                if bn:
                    listed_body_genus_name.add((bn, gk))

            # Action counts (ignore CODEX placeholders for "active/complete")
            if status != "CODEX":
                active += 1
                if rec.get("Complete"):
                    complete += 1
                hv = None
                if isinstance(base_v, int):
                    hv = base_v
                elif isinstance(pot_v, int):
                    hv = pot_v
                if isinstance(hv, int) and hv >= exo_min:
                    high_value += 1

        # 2) Planet-level targets from FSS/DSS (BioSignals / BioGenuses), even before ScanOrganic exists
        for body, rec in (self.state.bodies or {}).items():
            if not isinstance(rec, dict):
                continue
            bio = rec.get("BioSignals", 0) or 0
            if not isinstance(bio, int) or bio <= 0:
                continue
            body_id = rec.get("BodyID")

            gen = rec.get("BioGenuses", []) or []
            if isinstance(gen, list) and gen:
                # One row per DSS-confirmed genus that is NOT yet scanned on this body.
                for g in gen:
                    gk = str(g or "").strip()
                    if not gk:
                        continue

                    # If CODEX already identified species/variant for this genus, we do NOT hide the DSS row.
                    # Instead, we enrich the DSS row below (Species/Variant/BaseValue) and mark it as CODEX.

                    if (isinstance(body_id, int) and (body_id, gk) in real_body_genus_id) or ((_norm_text(body), gk) in real_body_genus_name):
                        continue
                    pot = genus_max.get(gk)
                    sp = ""
                    vv = ""
                    try:
                        if isinstance(body_id, int):
                            sp = codex_hint_id.get((body_id, gk), "") or ""
                            vv = codex_hint_var_id.get((body_id, gk), "") or ""
                        if not sp:
                            sp = codex_hint_name.get((_norm_text(body), gk), "") or ""
                        if not vv:
                            vv = codex_hint_var_name.get((_norm_text(body), gk), "") or ""
                    except Exception:
                        sp = ""
                        vv = ""
                    pot_txt = "" if sp or vv else (f"{pot:,} cr" if isinstance(pot, int) and pot > 0 else "")
                    try:
                        sp = str(sp or "").strip()
                    except Exception:
                        sp = ""
                    try:
                        vv = str(vv or "").strip()
                    except Exception:
                        vv = ""
                    status_txt = "CODEX" if sp else "UNSCANNED"
                    base_txt = ""
                    try:
                        bv = None
                        if isinstance(body_id, int):
                            bv = codex_hint_base_id.get((body_id, gk))
                        if not isinstance(bv, int):
                            bv = codex_hint_base_name.get((_norm_text(body), gk))
                        # If we only know the species name (from Codex hint), derive base from exo_values.json.
                        if not isinstance(bv, int) and sp and getattr(self, "exo_values", None):
                            key = sp
                            exo_rec = self.exo_values.by_species.get(key)
                            if exo_rec is None and " - " in key:
                                exo_rec = self.exo_values.by_species.get(key.split(" - ", 1)[0].strip())
                            if exo_rec is not None and isinstance(getattr(exo_rec, "base_value", None), int):
                                bv = exo_rec.base_value
                        if isinstance(bv, int) and bv > 0:
                            base_txt = f"{bv:,} cr"
                    except Exception:
                        base_txt = ""
                    rows.append((0, status_txt, body, gk, sp, vv, pot_txt, base_txt, "0/3", status_txt))
                    targets += 1
                    if isinstance(pot, int) and pot >= exo_min:
                        high_value += 1
                    if isinstance(body_id, int):
                        listed_body_genus_id.add((body_id, gk))
                    if isinstance(body, str) and body.strip():
                        listed_body_genus_name.add((_norm_text(body), gk))
            else:
                # We know there are bio signals, but genus is unknown until DSS mapping reveals it.
                genus_txt = f"{bio} bio signals"
                status_txt = f"NEEDS DSS (Bio: {bio})"
                rows.append((0, status_txt, body, genus_txt, "", "", "", "", "0/3", status_txt))
                targets += 1

        # 3) Add CODEX placeholders only if no real ScanOrganic exists AND we did not already emit a DSS row for that genus.
        # NOTE: This MUST run after the DSS target rows above, otherwise we create duplicate "UNSCANNED" + "CODEX" rows.
        seen_codex = set()  # (body_key, genus)
        for body_txt, rec in (codex_pending or []):
            body_id = rec.get("BodyID")
            genus = str(rec.get("Genus", "") or "").strip()
            if not genus:
                continue
            body_name = None
            if isinstance(body_id, int):
                body_name = self.state.body_id_to_name.get(body_id) or body_key_by_id.get(body_id)
            body_key = body_id if isinstance(body_id, int) else (
                body_name.strip() if isinstance(body_name, str) and body_name.strip() else body_txt
            )
            dk = (body_key, genus)
            if dk in seen_codex:
                continue
            seen_codex.add(dk)

            # Strong suppression: if DSS already revealed this genus for this body, never emit a CODEX placeholder row.
            try:
                br = None
                if isinstance(body_id, int):
                    br = body_rec_by_id.get(body_id)
                bn = _norm_text(body_name or body_txt)
                if bn and bn in body_key_by_norm:
                    br = (self.state.bodies or {}).get(body_key_by_norm.get(bn))
                if br is None and isinstance(body_name, str) and body_name.strip():
                    br = (self.state.bodies or {}).get(body_name.strip())
                if br is None:
                    br = (self.state.bodies or {}).get(body_txt)
                if isinstance(br, dict):
                    dss_gen = br.get("BioGenuses", []) or []
                    if isinstance(dss_gen, list) and any(str(x or "").strip() == genus for x in dss_gen):
                        continue
            except Exception:
                pass

            # If we already have a better row (real ScanOrganic or DSS target), do not add a duplicate CODEX row.
            if (isinstance(body_id, int) and (body_id, genus) in listed_body_genus_id) or (
                (_norm_text(body_name or body_txt), genus) in listed_body_genus_name
            ):
                continue
            if (isinstance(body_id, int) and (body_id, genus) in real_body_genus_id) or (
                (_norm_text(body_name or body_txt), genus) in real_body_genus_name
            ):
                continue

            # Potential value is a DSS/genus concept; CODEX placeholders should not display it.
            pot_txt = ""
            base_v = rec.get("BaseValue")
            if not isinstance(base_v, int) and getattr(self, "exo_values", None):
                nm = rec.get("CodexName") or rec.get("Species") or ""
                if isinstance(nm, str) and nm.strip():
                    key = nm.strip()
                    exo_rec = self.exo_values.by_species.get(key)
                    if exo_rec is None and " - " in key:
                        exo_rec = self.exo_values.by_species.get(key.split(" - ", 1)[0].strip())
                    if exo_rec is not None and isinstance(getattr(exo_rec, "base_value", None), int):
                        base_v = exo_rec.base_value
            base_txt = f"{base_v:,} cr" if isinstance(base_v, int) else ""
            species_txt = rec.get("Species") or rec.get("CodexName") or ""
            if not isinstance(species_txt, str):
                species_txt = ""
            var_txt = _variant_color(rec.get("Variant") or rec.get("CodexName") or "")
            rows.append((0, "CODEX", body_txt, genus, species_txt.strip(), var_txt, pot_txt, base_txt, "0/3", "CODEX"))

        # Sort: actionable first. CODEX (species known, 0/3) should sit near UNSCANNED, not down with placeholders.
        def _status_rank(s):
            if not isinstance(s, str):
                return 99
            if s == "COMPLETE":
                return 50
            if s.startswith("NEEDS DSS"):
                return 10
            if s == "UNSCANNED":
                return 20
            if s == "CODEX":
                return 25
            return 30

        rows.sort(key=lambda x: (_status_rank(x[1]), -x[0]))

        shown = rows[:80]
        self.exo_table.setRowCount(len(shown))

        for r, row in enumerate(shown):
            # Backward/variant row shapes:
            # - Old shape (10): samples,status,body,genus,species,variant,potential,base,progress,status_txt
            # - New shape (11): samples,status,body,genus,species,variant,potential,base,progress,ccr_txt,status_txt
            if not isinstance(row, (list, tuple)):
                continue
            if len(row) == 10:
                _samples, _status, body_txt, genus, species, var_txt, pot_txt, base_txt, prog_txt, status_txt = row
                ccr_txt = ""
            else:
                _samples, _status, body_txt, genus, species, var_txt, pot_txt, base_txt, prog_txt, ccr_txt, status_txt = row

            self.exo_table.setItem(r, 0, QTableWidgetItem(str(body_txt)))
            self.exo_table.setItem(r, 1, QTableWidgetItem(str(genus)))
            self.exo_table.setItem(r, 2, QTableWidgetItem(str(species)))
            self.exo_table.setItem(r, 3, QTableWidgetItem(str(var_txt)))
            self.exo_table.setItem(r, 4, QTableWidgetItem(str(pot_txt)))
            self.exo_table.setItem(r, 5, QTableWidgetItem(str(base_txt)))
            self.exo_table.setItem(r, 6, QTableWidgetItem(str(prog_txt)))
            #self.exo_table.setItem(r, 7, QTableWidgetItem(str(ccr_txt)))

            # CCR column (dist/required)
            ccr_item = QTableWidgetItem(str(ccr_txt))

            self.exo_table.setItem(r, 7, ccr_item)
            self.exo_table.setItem(r, 8, QTableWidgetItem(str(status_txt)))

            # Highlight the full row for active in-progress scans:
            # samples > 0 and not yet COMPLETE.
            try:
                if isinstance(_samples, int) and _samples > 0 and str(_status).upper() != "COMPLETE":
                    for c in range(self.exo_table.columnCount()):
                        item = self.exo_table.item(r, c)
                        if item is not None:
                            item.setBackground(QColor(60, 90, 140))
                            item.setForeground(QColor(255, 255, 255))
            except Exception:
                pass

        if has_bio_targets:
            self.exo_action.setText(
                f"🔬 Exobiology: {targets} targets • {scanned_species} scanned • {complete} complete • {high_value} high-value (≥ {exo_m}M)"
            )
            if not self.state.exo:
                self.exo_hint.setText("Biological signals detected. DSS a body to reveal genus; land to start samples.")
        else:
            self.exo_action.setText(f"🔬 Exobiology: {active} active • {complete} complete • {high_value} high-value (≥ {exo_m}M)")

    def _refresh_exploration(self):
        min_100k = int(getattr(self.cfg, "min_planet_value_100k", 10) or 10)
        if min_100k < 0:
            min_100k = 0
        min_value = min_100k * 100_000
        # Display as "x.yM" (0.1M steps)
        self.min_value_label.setText(f"{min_100k / 10:.1f}M")

        # Show valuable bodies based on current Scan data
        if not self.state.bodies:
            hint = "No scan data yet. Tip: Do FSS / honk / nav beacon so Scan events appear."
            if not self.planet_values:
                hint += " (planet_values.json not loaded — copy it to .ed_companion or next to main.py)"
            self.exploration_table.setRowCount(0)
            self.exploration_action.setText("🌍 Exploration: no bodies resolved in this system yet.")
            self.exploration_hint.setText(hint)
            return

        rows = []  # (sort_val, body, class, ls_txt, bio_txt, geo_txt, bio_dss_txt, value_txt, prev_map_txt, dss_txt, flags_txt)
        best_below = None  # (value, line)
        bio_bodies = 0
        geo_bodies = 0
        tf_unmapped = 0
        hv_unmapped = 0
        for body, rec in self.state.bodies.items():
            est = rec.get("EstimatedValue")
            dist = rec.get("DistanceLS")
            pc = rec.get("PlanetClass") or ""
            # Normalize Frontier token-ish planet class strings for display
            pc_disp = self._norm_token(pc) or fmt.text(pc, default="")
            tf = rec.get("Terraformable", False)
            was_mapped = bool(rec.get("WasMapped", False))
            dss_mapped = bool(rec.get("DSSMapped", False)) or bool(rec.get("BioGenuses"))
            human_signals = int(rec.get("HumanSignals", 0) or 0)
            first = rec.get("FirstDiscovered", False)
            bio = rec.get("BioSignals", 0) or 0
            geo = rec.get("GeoSignals", 0) or 0
            gen = rec.get("BioGenuses", []) or []
            if isinstance(bio, int) and bio > 0:
                bio_bodies += 1
            if isinstance(geo, int) and geo > 0:
                geo_bodies += 1
            if tf and not dss_mapped:
                tf_unmapped += 1
            if isinstance(est, int) and est >= min_value and not dss_mapped:
                hv_unmapped += 1

            # Sort key: estimated value if present else 0
            sort_val = int(est) if isinstance(est, int) else 0

            # Track best candidate even if it doesn't pass the filter
            if isinstance(est, int):
                preview_tags = []
                if tf:
                    preview_tags.append("Terraformable")
                if first:
                    preview_tags.append("NEW")
                if was_mapped:
                    preview_tags.append("PREV MAPPED")
                if dss_mapped:
                    preview_tags.append("DSS MAPPED")
                if not was_mapped and not dss_mapped:
                    preview_tags.append("UNMAPPED")
                dist_txt = (fmt.int_commas(dist) + " LS") if isinstance(dist, (float, int)) else ""
                est_txt = fmt.credits(est, default="?")
                tag_txt = (" [" + ", ".join(preview_tags) + "]") if preview_tags else ""
                preview_line = f"{body} — {pc_disp} — {dist_txt} — {est_txt}{tag_txt}".strip()
                if (best_below is None) or (est > best_below[0]):
                    best_below = (est, preview_line)

            # Filter: Exploration tab shows high-value bodies AND any bodies with Geological signals
            # (Geological is useful for raw-material farming, even when the body is not valuable for credits.)
            pass

            tags = []
            if tf:
                tags.append("Terraformable")
            if first:
                tags.append("NEW")


            dist_txt = (fmt.int_commas(dist) + " LS") if isinstance(dist, (float, int)) else ""

            bio_txt = str(bio) if isinstance(bio, int) and bio > 0 else ""
            geo_txt = str(geo) if isinstance(geo, int) and geo > 0 else ""
            bio_dss_txt = "✔" if isinstance(gen, list) and len(gen) > 0 else ""
            est_txt = fmt.credits(est, default="?") if isinstance(est, int) else "?"
            prev_map_txt = "✔" if was_mapped else ""
            dss_txt = "✔" if dss_mapped else ""

            flags = []
            if tf:
                flags.append("Terra")
            if first:
                flags.append("NEW")
            if human_signals > 0:
                flags.append("Human")
            flags_txt = ", ".join(flags)

            rows.append(
                (
                    sort_val,
                    fmt.text(body, default=""),
                    pc_disp,
                    dist_txt,
                    bio_txt,
                    geo_txt,
                    bio_dss_txt,
                    est_txt,
                    prev_map_txt,
                    dss_txt,
                    flags_txt,
                )
            )

        rows.sort(key=lambda x: x[0], reverse=True)

        scanned = len(self.state.bodies)
        resolved = len(getattr(self.state, "resolved_body_ids", set()) or set())
        total = self.state.system_body_count
        fss_complete = bool(getattr(self.state, "fss_complete", False))
        header_bits = []
        if isinstance(total, int) and total > 0:
            if fss_complete:
                header_bits.append(
                    f"Bodies discovered: {total}/{total} • detailed records loaded: {scanned}"
                )
            else:
                remaining = max(0, total - resolved)
                header_bits.append(
                    f"Bodies resolved: {resolved}/{total} (detailed records loaded: {scanned}, unknown remaining: {remaining})"
                )
        else:
            header_bits.append(f"Bodies resolved: {scanned} (honk for total count)")

        nb = getattr(self.state, "non_body_count", None)
        if not fss_complete and isinstance(total, int) and total > scanned:
            header_bits.append(f"Unresolved bodies: {total - scanned}")

        sigs = getattr(self.state, "system_signals", None) or []
        if isinstance(sigs, list) and sigs:
            header_bits.append(f"Signals discovered: {len(sigs)}")

        # Fill table (top 50 is plenty)
        shown = rows[:50]
        self.exploration_table.setRowCount(len(shown))
        for r, (_sv, b, pc, ls_txt, bio_txt, geo_txt, bio_dss_txt, v_txt, prev_map_txt, dss_txt, flags_txt) in enumerate(shown):
            self.exploration_table.setItem(r, 0, QTableWidgetItem(str(b)))
            self.exploration_table.setItem(r, 1, QTableWidgetItem(str(pc)))
            # Ensure numeric sorting on the "LS" column (avoid lexicographic sort like "100" < "9")
            it_ls = QTableWidgetItem(str(ls_txt))
            try:
                s = str(ls_txt).replace("LS", "").strip()
                # Keep only digits/dot/minus (robust against "12,345 LS")
                s = s.replace(",", "")
                v = float(s) if s else None
                if v is not None:
                    it_ls.setData(Qt.ItemDataRole.UserRole, v)
            except Exception:
                pass
            self.exploration_table.setItem(r, 2, it_ls)
            self.exploration_table.setItem(r, 3, QTableWidgetItem(str(bio_txt)))
            self.exploration_table.setItem(r, 4, QTableWidgetItem(str(geo_txt)))
            self.exploration_table.setItem(r, 5, QTableWidgetItem(str(bio_dss_txt)))
            it_val = QTableWidgetItem(str(v_txt))

            # Numeric sort key: use the stored sort value directly
            try:
                it_val.setData(Qt.ItemDataRole.UserRole, int(_sv))
            except Exception:
                pass
            self.exploration_table.setItem(r, 6, it_val)
            self.exploration_table.setItem(r, 7, QTableWidgetItem(str(prev_map_txt)))
            self.exploration_table.setItem(r, 8, QTableWidgetItem(str(dss_txt)))
            self.exploration_table.setItem(r, 9, QTableWidgetItem(str(flags_txt)))

            # =========================================
            # Elite Exploration Row Intelligence Styling
            # =========================================
            try:
                est_value = row_data.get("EstValue") or row_data.get("EstimatedValue") or 0
                landable = row_data.get("Landable", False)
                geo = row_data.get("Geo", 0) or row_data.get("GeoSignals", 0) or 0

                try:
                    min_100k = int(getattr(self.cfg, "min_planet_value_100k", 10) or 10)
                except Exception:
                    min_100k = 10
                    min_value = min_100k * 100_000

                # Determine color
                row_color = None

                if isinstance(est_value, int) and est_value >= min_value:
                    # High value = Elite blue
                    row_color = "#102A43"

                    if landable:
                        # High + landable slightly stronger
                        row_color = "#0F3057"

                    elif landable and isinstance(geo, int) and geo > 0:
                        # Landable geo bodies = amber tint
                        row_color = "#2A1A00"

                else:
                    # Low value muted
                    row_color = "#111111"

                # Apply to entire row
                for c in range(self.exploration_table.columnCount()):
                    item = self.exploration_table.item(r, c)
                    if item:
                        item.setBackground(Qt.GlobalColor.transparent)
                        item.setBackground(QColor(row_color))

            except Exception:
                pass

        # Hint line under the table
        if not shown:
            hint = "No bodies above threshold (or with Geo signals) yet. Tip: lower the slider, or scan more bodies (FSS/nav beacon)."
            if best_below:
                hint += f"\nBest found so far (below threshold): {best_below[1]}"
            self.exploration_hint.setText("\n".join(header_bits) + "\n" + hint)
        else:
            self.exploration_hint.setText("\n".join(header_bits))

        self.exploration_action.setText(
            f"🌍 Exploration: {len(shown)} shown • {bio_bodies} bodies with bio • {geo_bodies} bodies with geo • {tf_unmapped} TF unmapped • {hv_unmapped} high-value unmapped"
        )

        # System signals box (FSSSignalDiscovered)
        try:
            sigs = getattr(self.state, "system_signals", None) or []
            if isinstance(sigs, list) and sigs:
                out_lines = []

                # Categorize
                cat_order = ["Phenomena", "Megaship", "TouristBeacon", "Station", "USS", "Other"]
                cats = {k: [] for k in cat_order}
                cat_counts = {k: 0 for k in cat_order}
                uss_counts = {}
                for s in sigs:
                    if not isinstance(s, dict):
                        continue
                    cat_raw = s.get("Category") if isinstance(s.get("Category"), str) else "Other"
                    cat = self._norm_token(cat_raw) or "Other"
                    if cat not in cats:
                        cat = "Other"
                    cats[cat].append(s)
                    cat_counts[cat] += 1
                    if cat == "USS":
                        u = self._norm_token(s.get("USSType") or "")
                        if u:
                            uss_counts[u] = uss_counts.get(u, 0) + 1

                # Summary line (low noise)
                out_lines.append(
                    "Summary: "
                    + " | ".join([f"{k} x{cat_counts[k]}" for k in cat_order if cat_counts.get(k, 0)])
                )

                # Optional USS breakdown (still compact)
                if uss_counts:
                    bits = []
                    for k, v in sorted(uss_counts.items(), key=lambda x: (-x[1], str(x[0]).lower()))[:8]:
                        bits.append(f"{k} x{v}")
                    out_lines.append("USS types: " + " | ".join(bits))

                out_lines.append("")

                # Detailed list (capped)
                max_lines = 30
                used = 0
                for cat in cat_order:
                    if not cats[cat]:
                        continue
                    out_lines.append(f"{cat}:")
                    for s in cats[cat]:
                        if used >= max_lines:
                            break
                        nm = self._norm_token(s.get("SignalName") or "Signal") or "Signal"
                        stype = self._norm_token(s.get("SignalType") or "")
                        uss = self._norm_token(s.get("USSType") or "")
                        tl = s.get("ThreatLevel")
                        tr = s.get("TimeRemaining")
                        bits = [str(nm)]
                        if cat == "USS" and uss:
                            bits.append(f"({uss})")
                        if cat == "Other" and stype:
                            bits.append(f"[{stype}]")
                        if isinstance(tl, int):
                            bits.append(f"Threat {tl}")
                        if isinstance(tr, (int, float)):
                            bits.append(f"TR {int(tr)}s")
                        out_lines.append(" | ".join(bits))
                        used += 1
                    out_lines.append("")
                    if used >= max_lines:
                        break

                self.system_signals_box.setPlainText("\n".join(out_lines).strip())
            else:
                total = getattr(self.state, "system_body_count", None)
                fss_complete = getattr(self.state, "fss_complete", False)
                resolved = len(getattr(self.state, "resolved_body_ids", set()) or set())
                if isinstance(total, int) and not fss_complete and total > resolved:
                    remaining = total - resolved
                    self.system_signals_box.setPlainText(
                        f"{remaining} bodies unresolved. Use FSS to discover them."
                    )
                else:
                    self.system_signals_box.setPlainText("")
        except Exception:
            self.system_signals_box.setPlainText("")

        self._refresh_materials_shortlist()

    def _refresh_materials_shortlist(self):
        """
        Ranks landable bodies with Geo signals for raw-material farming.
        Uses Scan-derived fields when available: Landable, Volcanism, Materials.
        """
        try:
            rare = {
                "polonium", "tellurium", "ruthenium", "yttrium", "antimony",
                "arsenic", "selenium", "zirconium", "niobium", "tin",
                "molybdenum", "technetium",
            }

            # Needs set (raw mats): low inventory threshold
            low_threshold = 25
            low_raw = set()
            inv_raw = getattr(self.state, "materials_raw", {}) or {}
            if isinstance(inv_raw, dict):
                for k, v in inv_raw.items():
                    if isinstance(k, str) and isinstance(v, int) and v <= low_threshold:
                        low_raw.add(k.strip().lower())

            need_raw = low_raw

            targets = []
            for body, rec in (self.state.bodies or {}).items():
                if not isinstance(rec, dict):
                    continue
                landable = rec.get("Landable")
                if landable is not True:
                    continue
                geo = rec.get("GeoSignals", 0) or 0
                if not (isinstance(geo, int) and geo > 0):
                    continue

                dist = rec.get("DistanceLS")
                dist_v = float(dist) if isinstance(dist, (int, float)) else None

                volcanism = rec.get("Volcanism") or ""
                volc_present = bool(
                    isinstance(volcanism, str)
                    and volcanism.strip()
                    and ("no volcanism" not in volcanism.strip().lower())
                )

                mats = rec.get("Materials") or {}
                if not isinstance(mats, dict):
                    mats = {}

                rare_score = 0.0
                need_score = 0.0
                for k, v in mats.items():
                    if not isinstance(v, (int, float)):
                        continue
                    nm = str(k).strip().lower()
                    if nm in rare:
                        rare_score += float(v)
                    if nm in need_raw:
                        need_score += float(v)

                # Score: Geo dominates, then volcanism, then "needed" mats, then rare mats, then distance.
                score = (
                    (geo * 1000)
                    + (120 if volc_present else 0)
                    + (need_score * 20.0)
                    + (rare_score * 8.0)
                    - ((dist_v or 0.0) * 0.10)
                )
                targets.append((score, body, geo, dist_v, volcanism, mats))

            targets.sort(key=lambda x: x[0], reverse=True)
            show = targets[:8]

            if not show:
                self.materials_box.setPlainText(
                    "No landable bodies with Geological signals yet.\n"
                    "Tip: resolve bodies (FSS/nav beacon) so Scan events populate Landable/Materials/Volcanism."
                )
                return

            out = []
            out.append("Ranked targets (landable + Geo):")
            out.append(f"(!) low inventory (≤{low_threshold}) | (*) rarer raw mats")
            out.append("")

            for i, (_score, body, geo, dist_v, volcanism, mats) in enumerate(show, 1):
                head = f"{i}. {body}"
                if isinstance(dist_v, float):
                    head += f" — {dist_v:.0f} LS"
                head += f" — Geo {geo}"
                if isinstance(volcanism, str) and volcanism.strip() and ("no volcanism" not in volcanism.lower()):
                    head += " — Volcanism"
                out.append(head)

                # Top materials by %
                items = []
                for k, v in mats.items():
                    if isinstance(v, (int, float)):
                        items.append((float(v), str(k)))
                items.sort(key=lambda x: x[0], reverse=True)

                if items:
                    parts = []
                    for pct, nm in items[:6]:
                        raw = (nm or "").strip()
                        if not raw:
                            continue
                        disp = raw.capitalize() if raw.islower() else raw
                        key = raw.strip().lower()
                        bang = "!" if key in need_raw else ""
                        star = "*" if key in rare else ""
                        parts.append(f"{disp}{bang}{star} {pct:.1f}%")
                    out.append("   " + " | ".join(parts))
                else:
                    out.append("   Materials: (not yet scanned)")

                if isinstance(volcanism, str) and volcanism.strip() and ("no volcanism" not in volcanism.lower()):
                    out.append(f"   Volcanism: {volcanism.strip()}")

            self.materials_box.setPlainText("\n".join(out).strip())
        except Exception:
            # Never break the UI refresh loop.
            self.materials_box.setPlainText("")

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
        if not self.state.system:
            self.system_card.setPlainText("No system data yet.")
            self.factions_table.setRowCount(0)
            return

        lines = []
        lines.append(f"System: {self.state.system}")
        if self.state.controlling_faction:
            lines.append(f"Controlling Faction: {self.state.controlling_faction}")

        meta = []
        allegiance = self._norm_token(getattr(self.state, "system_allegiance", None))
        government = self._norm_token(getattr(self.state, "system_government", None))
        security = self._norm_token(getattr(self.state, "system_security", None))
        economy = self._norm_token(getattr(self.state, "system_economy", None))
        population = fmt.int_commas(getattr(self.state, "population", None))

        if allegiance:
            meta.append(f"Allegiance: {allegiance}")
        if government:
            meta.append(f"Government: {government}")
        if security:
            meta.append(f"Security: {security}")
        if economy:
            meta.append(f"Economy: {economy}")
        if population:
            meta.append(f"Population: {population}")
        if meta:
            lines.append(" | ".join(meta))

        self.system_card.setPlainText("\n".join(lines))

        # Fill factions table (top by influence)
        facs = []
        controlling_name = fmt.text(self.state.controlling_faction, default="")

        for f in (self.state.factions or []):
            if not isinstance(f, dict):
                continue

            name = fmt.text(f.get("Name"), default="Unknown")

            infl = f.get("Influence")
            infl_val = float(infl) if isinstance(infl, (float, int)) else -1.0
            infl_txt = fmt.pct_1(infl_val, default="?") if infl_val >= 0 else "?"

            government = fmt.text(
                f.get("Government_Localised") or self._norm_token(f.get("Government")) or f.get("Government") or "",
                default="",
            )

            allegiance = fmt.text(
                f.get("Allegiance_Localised") or self._norm_token(f.get("Allegiance")) or f.get("Allegiance") or "",
                default="",
            )

            active_txt = ""
            active_states = f.get("ActiveStates") or []
            if isinstance(active_states, list) and active_states:
                vals = []
                for st in active_states:
                    if not isinstance(st, dict):
                        continue
                    val = fmt.text(
                        st.get("State_Localised") or self._norm_token(st.get("State")) or st.get("State") or "",
                        default="",
                    )
                    if val:
                        vals.append(val)
                active_txt = ", ".join(vals[:2])
            elif f.get("FactionState") and str(f.get("FactionState")).strip().lower() != "none":
                active_txt = fmt.text(self._norm_token(f.get("FactionState")) or f.get("FactionState"), default="")

            rep = f.get("MyReputation")
            if isinstance(rep, (float, int)):
                rep_f = float(rep)
                if -1.0 <= rep_f <= 1.0:
                    rep_txt = f"{(rep_f * 100):.1f}%"
                else:
                    rep_txt = f"{rep_f:.1f}"
            else:
                rep_txt = ""

            is_controller = bool(controlling_name and name == controlling_name)
            display_name = f"{name} ★" if is_controller else name
            facs.append((infl_val, display_name, government, allegiance, active_txt, infl_txt, rep_txt, is_controller))

        facs.sort(key=lambda x: x[0], reverse=True)
        top = facs[:12]
        self.factions_table.setRowCount(len(top))
        for r, (_infl_val, name, government, allegiance, active_txt, infl_txt, rep_txt, is_controller) in enumerate(top):
            items = [
                QTableWidgetItem(name),
                QTableWidgetItem(government),
                QTableWidgetItem(allegiance),
                QTableWidgetItem(active_txt),
                QTableWidgetItem(infl_txt),
                QTableWidgetItem(rep_txt),
            ]

            # Base styling rules
            row_bg = None
            row_fg = None

            active_l = (active_txt or "").strip().lower()

            # Controlling faction highlight
            if is_controller:
                row_bg = QColor(35, 55, 85)   # soft elite blue
                row_fg = QColor(255, 255, 255)

            # Conflict tint overrides controller tint if important enough
            if active_l in {"war", "civil war"}:
                row_bg = QColor(95, 35, 35)   # muted red
                row_fg = QColor(255, 235, 235)
            elif active_l == "election":
                row_bg = QColor(85, 70, 35)   # muted amber
                row_fg = QColor(255, 245, 220)

            # Rep text tint
            try:
                rep_val = None
                txt = (rep_txt or "").replace("%", "").strip()
                if txt:
                    rep_val = float(txt)
                if rep_val is not None:
                    if rep_val >= 50:
                        items[5].setForeground(QColor(140, 255, 180))
                    elif rep_val < 0:
                        items[5].setForeground(QColor(255, 160, 160))
            except Exception:
                pass

            # Active state cell badge tint
            if active_l in {"war", "civil war"}:
                items[3].setBackground(QColor(140, 60, 60))
                items[3].setForeground(QColor(255, 255, 255))
            elif active_l == "election":
                items[3].setBackground(QColor(140, 110, 50))
                items[3].setForeground(QColor(255, 255, 255))

            if row_bg is not None:
                for it in items:
                    # keep active-state badge cell stronger if already set
                    if it is not items[3]:
                        it.setBackground(row_bg)
                    if row_fg is not None and it is not items[5]:
                        it.setForeground(row_fg)

            for c, it in enumerate(items):
                self.factions_table.setItem(r, c, it)

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
