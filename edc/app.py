import argparse
import ctypes
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from pathlib import Path
import logging

from edc.config import ConfigStore, default_app_dir, detect_journal_dir
from edc.utils.log import setup_logging
from edc.core.journal_importer import JournalImporter
from edc.ui.main_window import MainWindow
from edc.ui.splash_screen import SplashScreen

def parse_args():
    parser = argparse.ArgumentParser(description="EDC Application")
    parser.add_argument('--settings', action='store_true', help='Display current settings')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose output')
    return parser.parse_args()

def run():
    args = parse_args()
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)
    if args.settings:
        cfg_store = ConfigStore(default_app_dir())
        cfg = cfg_store.load()
        print("Current Settings:")
        print(f"Journal Directory: {cfg.journal_dir}")
        print(f"Minimum Planet Value (100k credits): {cfg.min_planet_value_100k}")
        print(f"Exobiology High Value Multiplier: {cfg.exo_high_value_m}")
        return
    base_dir = default_app_dir()          # project root
    cfg_store = ConfigStore(base_dir)     # exposes cfg_store.settings_dir
    setup_logging(cfg_store.settings_dir) # logs live under <project_root>/settings

    log = logging.getLogger("edc.app")
    log.info("Startup paths: app_dir=%s settings_dir=%s settings_path=%s",
            str(cfg_store.app_dir), str(cfg_store.settings_dir), str(cfg_store.settings_path))

    cfg = cfg_store.load()

    if not cfg.journal_dir:
        detected = detect_journal_dir()
        if detected:
            cfg.journal_dir = detected
            cfg_store.save(cfg)
            log.info("Auto-detected journal directory: %s", detected)
        else:
            log.warning("Could not auto-detect journal directory. Set it manually in Settings.")

    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("EDChronicle")
    app = QApplication([])
    app.setWindowIcon(QIcon("assets/edc_icon.ico"))

    app.setStyle("Fusion")

    app.setStyleSheet(app.styleSheet() + """
    QMainWindow {
        background-color: #0A0A0A;
    }

    /* ============================= */
    /* GLOBAL TEXT COLOR FIX        */
    /* ============================= */

    QWidget {
        color: #E6E6E6;
    }

    QListWidget {
        background-color: #111111;
        border: none;
        color: #E6E6E6;
        font-size: 13px;
    }

    QListWidget::item {
        padding: 12px;
        border-radius: 0px;
    }

    QListWidget::item:selected {
        background-color: #FF8C00;
        color: #000000;
    }

    QListWidget::item:hover {
        background-color: #1F1F1F;
    }

    QPushButton {
        background-color: #FF8C00;
        border-radius: 6px;
        padding: 6px 12px;
        color: #000000;
    }

    QPushButton:hover {
        background-color: #FFA733;
    }

    QTableWidget {
        background-color: #101010;
        gridline-color: #2A2A2A;
        color: #E6E6E6;
        alternate-background-color: #141414;
        selection-background-color: #FF8C00;
        selection-color: #000000;
    }

    QTableWidget::item {
        color: #E6E6E6;
    }

    QTableView {
        background-color: #101010;
        alternate-background-color: #141414;
        selection-background-color: #FF8C00;
        selection-color: #000000;
    }

    QListWidget {
        alternate-background-color: #141414;
        selection-background-color: #FF8C00;
        selection-color: #000000;
    }

    QHeaderView::section {
        background-color: #151515;
        border: none;
        padding: 6px;
        color: #E6E6E6;
    }

    QTextEdit {
        background-color: #101010;
        border: 1px solid #2A2A2A;
        border-radius: 4px;
        color: #E6E6E6;
    }

    QLineEdit, QComboBox, QSpinBox {
        background-color: #101010;
        color: #E6E6E6;
        border: 1px solid #2A2A2A;
        border-radius: 4px;
        padding: 4px;
    }

    QComboBox QAbstractItemView {
        background-color: #1a1a1a;
        color: #E6E6E6;
        selection-background-color: #FF8C00;
        selection-color: #000000;
        border: 1px solid #333333;
        outline: none;
    }

    QSplitter::handle {
        background-color: #1E1E1E;
        width: 3px;
        height: 3px;
    }

    QSplitter::handle:hover {
        background-color: #FF8C00;
    }

    QLabel {
        font-size: 12px;
    }

    QLabel a {
        color: #6EC1FF;
        text-decoration: none;
        font-weight: 500;
    }

    QLabel a:hover {
        color: #FF8C00;
        text-decoration: underline;
    }

    """)
    def launch():
        win = MainWindow(cfg_store, cfg, auto_start=False)

        try:
            journal_dir = Path(cfg.journal_dir)
            importer = JournalImporter(journal_dir, win.repo)
            importer.import_all()
        except Exception:
            log.exception("Historical system hydration failed")

        win.show()
        QTimer.singleShot(0, win.refresh_from_state)
        QTimer.singleShot(0, win.start_auto_watch)

    splash = SplashScreen(on_done=launch)
    splash.show()

    app.exec()
