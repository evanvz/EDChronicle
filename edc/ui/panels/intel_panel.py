import logging
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QTextEdit,
)

log = logging.getLogger(__name__)


class IntelPanel(QWidget):
    """
    Owns all widgets and refresh logic for the Intel tab.
    Receives state and farming_locations via refresh().
    Knows nothing about main_window or any other panel.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Intel (External, advisory only)"))

        self.intel_summary = QLabel("")
        self.intel_summary.setWordWrap(True)
        layout.addWidget(self.intel_summary)

        self.intel_box = QTextEdit()
        self.intel_box.setReadOnly(True)
        layout.addWidget(self.intel_box, 1)

    def refresh(self, state, farming_locations):
        pois = getattr(state, "external_pois", None) or []
        sys_name = getattr(state, "system", None) or ""
        farms = (
            farming_locations.get_for_system(sys_name)
            if sys_name
            else []
        )

        lines = []
        poi_count = 0
        farm_count = 0

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

        if isinstance(farms, list) and farms:
            farm_count = len(farms)
            if lines:
                lines.append("")
            lu = getattr(farming_locations, "last_updated", None)
            lu_txt = (
                f" (updated: {lu})"
                if isinstance(lu, str) and lu.strip()
                else ""
            )
            lines.append(
                f"Farming locations in-system (advisory){lu_txt}"
            )
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
                mats_txt = ", ".join([
                    str(x) for x in mats[:6]
                    if isinstance(x, str) and x.strip()
                ])
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

        if poi_count == 0 and farm_count == 0:
            self.intel_summary.setText(
                "No offline intel for this system."
            )
            self.intel_box.setPlainText(
                "Optional files:\n"
                " - settings/external_pois.json (system POIs)\n"
                " - settings/elite_farming_locations.json "
                "(farming locations)\n"
            )
            return

        bits = []
        if poi_count:
            bits.append(f"{poi_count} external POIs")
        if farm_count:
            bits.append(f"{farm_count} farming locations")
        self.intel_summary.setText(
            f"{' | '.join(bits)} for this system (advisory only)."
        )
        self.intel_box.setPlainText(
            "\n".join(lines).strip() or "No usable intel entries."
        )