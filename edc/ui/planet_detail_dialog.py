from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame, QApplication,
)
from PyQt6.QtCore import Qt

RARE = {
    "polonium", "tellurium", "ruthenium", "yttrium",
    "antimony", "arsenic", "selenium", "zirconium",
    "niobium", "tin", "molybdenum", "technetium",
}


def _esc(t):
    return str(t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _divider():
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet("background: #1e2a3a; border: none; max-height: 1px; margin: 4px 0;")
    return line


def _section_header(text):
    lbl = QLabel(text)
    lbl.setStyleSheet(
        "color: #555555; font-size: 10px; font-weight: bold; "
        "letter-spacing: 1px; background: transparent; border: none;"
    )
    return lbl


def _stat_label(text):
    lbl = QLabel(text)
    lbl.setStyleSheet("color: #555555; font-size: 10px; background: transparent; border: none;")
    return lbl


def _stat_value(text):
    lbl = QLabel(text)
    lbl.setStyleSheet("color: #CCCCCC; font-size: 11px; background: transparent; border: none;")
    lbl.setWordWrap(True)
    return lbl


def _badge(text, bg, fg, bold=False):
    weight = "font-weight:700;" if bold else ""
    return (
        f'<span style="background:{bg};color:{fg};font-size:10px;{weight}'
        f'padding:1px 6px;border-radius:3px;">{_esc(text)}</span>'
    )


class PlanetDetailDialog(QDialog):

    def __init__(self, body_name: str, rec: dict, state, parent=None):
        super().__init__(parent)
        self.setWindowTitle(body_name)
        self.setFixedWidth(660)
        self.setStyleSheet("QDialog { background: #0d1015; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        g_sig = int((getattr(state, "guardian_signals", {}) or {}).get(body_name, 0) or rec.get("GuardianSignals", 0) or 0)
        t_sig = int((getattr(state, "thargoid_signals", {}) or {}).get(body_name, 0) or rec.get("ThargoidSignals", 0) or 0)
        bio   = int(rec.get("BioSignals", 0) or 0)
        geo   = int(rec.get("GeoSignals", 0) or 0)

        if t_sig:
            accent = "#FF6B6B"
        elif g_sig:
            accent = "#FF8888"
        elif bio:
            accent = "#6BCB77"
        elif geo:
            accent = "#FFB347"
        else:
            accent = "#4D96FF"

        # ── Header ───────────────────────────────────────────────────────────
        hdr_row = QHBoxLayout()
        hdr_row.setSpacing(8)

        name_lbl = QLabel(
            f'<span style="color:{accent};font-weight:700;font-size:14px;">'
            f'{_esc(body_name)}</span>'
        )
        name_lbl.setTextFormat(Qt.TextFormat.RichText)
        name_lbl.setStyleSheet("background: transparent; border: none;")
        hdr_row.addWidget(name_lbl)

        pc = str(rec.get("PlanetClass") or "")
        if pc:
            pc_lbl = QLabel(
                f'<span style="color:#888888;font-size:11px;">— {_esc(pc)}</span>'
            )
            pc_lbl.setTextFormat(Qt.TextFormat.RichText)
            pc_lbl.setStyleSheet("background: transparent; border: none;")
            hdr_row.addWidget(pc_lbl)

        hdr_row.addStretch(1)

        badges = []
        if rec.get("Landable"):
            badges.append(_badge("Landable", "#1a3a1a", "#6BCB77", bold=True))
        if rec.get("Terraformable"):
            badges.append(_badge("Terraformable", "#2a1a3a", "#C77DFF", bold=True))
        if rec.get("FirstDiscovered"):
            badges.append(_badge("First Discovery", "#2a1a00", "#FFB347", bold=True))
        if rec.get("DSSMapped"):
            badges.append(_badge("DSS Mapped", "#1a2a3a", "#4D96FF"))
        elif rec.get("WasMapped"):
            badges.append(_badge("Prev Mapped", "#1a1a2a", "#888888"))
        if rec.get("TidalLock"):
            badges.append(_badge("Tidal Lock", "#1a1a2a", "#888888"))
        if rec.get("FirstFootfall"):
            badges.append(_badge("First Footfall", "#2a1500", "#FFD700", bold=True))
        elif rec.get("HasFootfall"):
            badges.append(_badge("Footfall", "#1a1a1a", "#AAAAAA"))

        if badges:
            badge_lbl = QLabel(" ".join(badges))
            badge_lbl.setTextFormat(Qt.TextFormat.RichText)
            badge_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            badge_lbl.setStyleSheet("background: transparent; border: none;")
            hdr_row.addWidget(badge_lbl)

        layout.addLayout(hdr_row)
        layout.addWidget(_divider())

        # ── Stats grid ────────────────────────────────────────────────────────
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(6)

        def _fmt_dist(v):
            try:
                return f"{float(v):,.0f} Ls"
            except (TypeError, ValueError):
                return "—"

        def _fmt_mass(v):
            try:
                return f"{float(v):.4f}"
            except (TypeError, ValueError):
                return "—"

        def _fmt_radius(v):
            try:
                return f"{float(v) / 1000:,.0f} km"
            except (TypeError, ValueError):
                return "—"

        def _fmt_gravity(v):
            try:
                return f"{float(v) / 9.80665:.2f} g"
            except (TypeError, ValueError):
                return "—"

        def _fmt_temp(v):
            try:
                k = float(v)
                c = k - 273.15
                f = c * 9 / 5 + 32
                return f"{k:.0f} K ({c:.0f}°C / {f:.0f}°F)"
            except (TypeError, ValueError):
                return "—"

        def _fmt_pressure(v):
            try:
                atm = float(v) / 101325
                if atm < 0.01:
                    return "< 0.01 atm"
                return f"{atm:.2f} atm"
            except (TypeError, ValueError):
                return "—"

        left = [
            ("BODY DISTANCE", _fmt_dist(rec.get("DistanceLS"))),
            ("EARTH MASSES",  _fmt_mass(rec.get("MassEM"))),
            ("RADIUS",        _fmt_radius(rec.get("Radius"))),
            ("GRAVITY",       _fmt_gravity(rec.get("SurfaceGravity"))),
        ]
        def _fmt_composition(comp):
            if not isinstance(comp, dict) or not comp:
                return "—"
            parts = []
            for key in ("Rock", "Metal", "Ice"):
                v = comp.get(key)
                if v is not None:
                    try:
                        parts.append(f"{key}: {float(v)*100:.1f}%")
                    except (TypeError, ValueError):
                        pass
            return "  ".join(parts) if parts else "—"

        def _fmt_atmo_composition(ac):
            if not isinstance(ac, list) or not ac:
                return ""
            sorted_ac = sorted(ac, key=lambda x: float(x.get("Percent") or 0), reverse=True)
            return "  ".join(
                f"{e.get('Name','?')}: {float(e.get('Percent',0)):.1f}%"
                for e in sorted_ac if e.get("Name")
            )

        right = [
            ("SURFACE TEMPERATURE", _fmt_temp(rec.get("SurfaceTemperature"))),
            ("SURFACE PRESSURE",    _fmt_pressure(rec.get("SurfacePressure"))),
            ("VOLCANISM",           str(rec.get("Volcanism") or "") or "None"),
            ("ATMOSPHERE",          str(rec.get("Atmosphere") or rec.get("AtmosphereType") or "") or "None"),
            ("COMPOSITION",         _fmt_composition(rec.get("Composition"))),
            ("TERRAFORMING",        "Terraformable" if rec.get("Terraformable") else "—"),
        ]

        for row, (label, value) in enumerate(left):
            grid.addWidget(_stat_label(label), row, 0)
            grid.addWidget(_stat_value(value), row, 1)

        for row, (label, value) in enumerate(right):
            grid.addWidget(_stat_label(label), row, 2)
            grid.addWidget(_stat_value(value), row, 3)

        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        layout.addLayout(grid)

        atmo_comp_str = _fmt_atmo_composition(rec.get("AtmosphereComposition") or [])
        if atmo_comp_str:
            ac_lbl = QLabel(
                f'<span style="color:#555555;font-size:10px;">ATMOSPHERE COMPOSITION&nbsp;&nbsp;</span>'
                f'<span style="color:#AAAAAA;font-size:10px;">{_esc(atmo_comp_str)}</span>'
            )
            ac_lbl.setTextFormat(Qt.TextFormat.RichText)
            ac_lbl.setWordWrap(True)
            ac_lbl.setStyleSheet("background: transparent; border: none;")
            layout.addWidget(ac_lbl)

        # ── Materials ─────────────────────────────────────────────────────────
        materials = rec.get("Materials") or {}
        if rec.get("Landable") and isinstance(materials, dict) and materials:
            layout.addWidget(_divider())
            layout.addWidget(_section_header("MATERIALS"))

            sorted_mats = sorted(materials.items(), key=lambda x: float(x[1] or 0), reverse=True)
            mat_parts = []
            for name, pct in sorted_mats:
                try:
                    pct_f = float(pct)
                except (TypeError, ValueError):
                    pct_f = 0.0
                is_rare = name.lower() in RARE
                colour = "#FFD93D" if is_rare else "#AAAAAA"
                bg = "#2a2200" if is_rare else "#1a1a1a"
                display = name.title()
                mat_parts.append(
                    f'<span style="background:{bg};color:{colour};font-size:10px;'
                    f'padding:1px 6px;border-radius:3px;">'
                    f'{_esc(display)}: {pct_f:.1f}%</span>'
                )

            mat_lbl = QLabel("&nbsp; ".join(mat_parts))
            mat_lbl.setTextFormat(Qt.TextFormat.RichText)
            mat_lbl.setWordWrap(True)
            mat_lbl.setStyleSheet("background: transparent; border: none;")
            layout.addWidget(mat_lbl)

        # ── Signals ───────────────────────────────────────────────────────────
        human     = int(rec.get("HumanSignals", 0) or 0)
        other_sig = int(rec.get("OtherSignals", 0) or 0)
        genuses   = rec.get("BioGenuses") or []
        any_sig   = bio or geo or human or g_sig or t_sig or other_sig
        if any_sig:
            layout.addWidget(_divider())
            layout.addWidget(_section_header("SIGNALS"))

            sig_parts = []
            if t_sig:
                sig_parts.append(f'<span style="color:#FF6B6B;">☣ Thargoid: {t_sig}</span>')
            if g_sig:
                sig_parts.append(f'<span style="color:#FF8888;">🔺 Guardian: {g_sig}</span>')
            if bio:
                genus_inline = ""
                if isinstance(genuses, list) and genuses:
                    genus_inline = (
                        f' <span style="color:#4a7a50;font-size:10px;">'
                        f'({_esc(", ".join(genuses))})</span>'
                    )
                sig_parts.append(
                    f'<span style="color:#6BCB77;">🌿 Biological: {bio}</span>'
                    f'{genus_inline}'
                )
            if geo:
                sig_parts.append(f'<span style="color:#FFB347;">🌋 Geological: {geo}</span>')
            if human:
                human_cats = {"Station", "Installation", "NavBeacon", "USS", "Megaship", "Wreckage"}
                sys_sigs = getattr(state, "system_signals", []) or []
                human_named = []
                seen_names = set()
                for s in sys_sigs:
                    if not isinstance(s, dict) or s.get("Category") not in human_cats:
                        continue
                    nm = (s.get("SignalName") or "").strip()
                    if nm and nm not in seen_names:
                        seen_names.add(nm)
                        human_named.append(nm)
                human_detail = ""
                if human_named:
                    human_detail = (
                        f'<br><span style="color:#3a6a99;font-size:10px;">'
                        f'&nbsp;&nbsp;{_esc(", ".join(human_named[:10]))}</span>'
                    )
                sig_parts.append(
                    f'<span style="color:#4D96FF;">⚠ Human: {human}</span>{human_detail}'
                )
            if other_sig:
                sig_parts.append(
                    f'<span style="color:#888888;">◈ Other: {other_sig}</span>'
                    f' <span style="color:#555555;font-size:10px;">'
                    f'(crash sites / guarded installations)</span>'
                )

            sig_lbl = QLabel("<br>".join(sig_parts))
            sig_lbl.setTextFormat(Qt.TextFormat.RichText)
            sig_lbl.setWordWrap(True)
            sig_lbl.setStyleSheet("background: transparent; border: none;")
            layout.addWidget(sig_lbl)

            if other_sig:
                tip_lbl = QLabel(
                    f'<span style="color:#FFD93D;font-size:10px;font-weight:700;">⚠ Crash Site Advisory</span><br>'
                    f'<span style="color:#888888;font-size:10px;">'
                    f'Scan skimmers before engaging — attack only if Wanted to avoid faction rep loss.<br>'
                    f'Cargo canisters (rebel transmissions, technical components) may be scoopable and sold on the black market.'
                    f'</span>'
                )
                tip_lbl.setTextFormat(Qt.TextFormat.RichText)
                tip_lbl.setWordWrap(True)
                tip_lbl.setStyleSheet(
                    "background: #1a1500; border: 1px solid #3a3000; "
                    "border-radius: 4px; padding: 5px 8px;"
                )
                layout.addWidget(tip_lbl)

        # ── Value & mapping ───────────────────────────────────────────────────
        layout.addWidget(_divider())
        val_row = QHBoxLayout()

        est = rec.get("EstimatedValue")
        try:
            est_i = int(est)
        except (TypeError, ValueError):
            est_i = 0

        if est_i > 0:
            val_lbl = QLabel(
                f'<span style="color:#555555;font-size:10px;">ESTIMATED VALUE&nbsp;&nbsp;</span>'
                f'<span style="color:#FFD93D;font-size:12px;font-weight:700;">'
                f'{est_i:,} Cr</span>'
            )
            val_lbl.setTextFormat(Qt.TextFormat.RichText)
            val_lbl.setStyleSheet("background: transparent; border: none;")
            val_row.addWidget(val_lbl)

        val_row.addStretch(1)

        mapping_parts = []
        if rec.get("FirstMapped"):
            mapping_parts.append(_badge("First Mapped", "#1a2a00", "#6BCB77", bold=True))
        if rec.get("DSSMapped"):
            mapping_parts.append(_badge("DSS Mapped", "#1a2a3a", "#4D96FF"))
        elif rec.get("WasMapped"):
            mapping_parts.append(_badge("Previously Mapped", "#1a1a2a", "#888888"))

        if mapping_parts:
            map_lbl = QLabel(" ".join(mapping_parts))
            map_lbl.setTextFormat(Qt.TextFormat.RichText)
            map_lbl.setStyleSheet("background: transparent; border: none;")
            val_row.addWidget(map_lbl)

        layout.addLayout(val_row)

        # ── Close button ──────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(80)
        close_btn.setStyleSheet(
            "QPushButton { background: #0d1015; color: #CCCCCC; border: 1px solid #4D96FF; "
            "border-radius: 4px; padding: 4px 12px; font-size: 11px; }"
            "QPushButton:hover { background: #1a2a3a; }"
        )
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self.adjustSize()
        screen = QApplication.primaryScreen()
        if screen:
            max_h = int(screen.availableGeometry().height() * 0.88)
            if self.height() > max_h:
                self.setFixedHeight(max_h)
