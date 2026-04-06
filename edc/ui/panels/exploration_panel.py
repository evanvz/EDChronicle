import logging
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QSplitter,
    QAbstractScrollArea,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor

from edc.ui import formatting as fmt

log = logging.getLogger(__name__)


class ExplorationPanel(QWidget):
    """
    Owns all widgets and refresh logic for the Exploration tab.
    Includes the materials shortlist sub-panel.
    Receives state, cfg, and planet_values via refresh().

    Emits min_value_changed(str) so main_window can update
    the min_value_label in the Settings tab without this
    panel needing to know about the Settings tab.
    """

    min_value_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Header strip
        header_panel = QWidget()
        header_layout = QVBoxLayout(header_panel)
        header_layout.setContentsMargins(8, 8, 8, 4)
        header_layout.addWidget(
            QLabel("Exploration (scans → instant estimate)")
        )
        self.exploration_action = QLabel("")
        self.exploration_action.setWordWrap(True)
        header_layout.addWidget(self.exploration_action)
        layout.addWidget(header_panel, 0)

        # Main table
        self.exploration_table = QTableWidget()
        self.exploration_table.setColumnCount(10)
        self.exploration_table.setHorizontalHeaderLabels(
            ["Body", "Class", "LS", "Bio", "Geo",
             "Bio DSS", "Est. Value", "Prev Map", "DSS", "Flags"]
        )
        self.exploration_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.exploration_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.exploration_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.exploration_table.verticalHeader().setVisible(False)
        self.exploration_table.setSizeAdjustPolicy(
            QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored
        )
        self.exploration_table.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.exploration_table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.exploration_table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.exploration_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        for col in range(1, 10):
            self.exploration_table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents
            )
        self.exploration_table.setMinimumHeight(120)
        self.exploration_table.setSortingEnabled(False)

        # Right split — signals + materials shortlist
        self.system_signals_box = QTextEdit()
        self.system_signals_box.setReadOnly(True)
        self.system_signals_box.setMinimumHeight(120)

        self.materials_box = QTextEdit()
        self.materials_box.setReadOnly(True)
        self.materials_box.setMinimumHeight(80)

        signals_panel = QWidget()
        signals_layout = QVBoxLayout(signals_panel)
        signals_layout.setContentsMargins(8, 8, 8, 8)
        signals_layout.addWidget(QLabel("System signals (FSS)"))
        signals_layout.addWidget(self.system_signals_box)

        materials_panel = QWidget()
        materials_layout = QVBoxLayout(materials_panel)
        materials_layout.setContentsMargins(8, 8, 8, 8)
        materials_layout.addWidget(
            QLabel("Materials shortlist (landable + Geo signals)")
        )
        materials_layout.addWidget(self.materials_box)

        self.expl_right_split = QSplitter(Qt.Orientation.Vertical)
        self.expl_right_split.addWidget(signals_panel)
        self.expl_right_split.addWidget(materials_panel)
        self.expl_right_split.setStretchFactor(0, 1)
        self.expl_right_split.setStretchFactor(1, 1)
        self.expl_right_split.setChildrenCollapsible(False)

        self.expl_outer_split = QSplitter(Qt.Orientation.Horizontal)
        self.expl_outer_split.addWidget(self.exploration_table)
        self.expl_outer_split.addWidget(self.expl_right_split)
        self.expl_outer_split.setStretchFactor(0, 1)
        self.expl_outer_split.setStretchFactor(1, 1)
        self.expl_outer_split.setChildrenCollapsible(False)

        layout.addWidget(self.expl_outer_split, 1)

        # Footer hint
        self.exploration_hint = QLabel("")
        self.exploration_hint.setWordWrap(True)
        layout.addWidget(self.exploration_hint, 0)

    def _norm_token(self, val):
        if not isinstance(val, str):
            return ""
        return (
            val.replace("$", "")
            .replace(";", "")
            .replace("_", " ")
            .strip()
            .title()
        )

    def refresh(self, state, cfg, planet_values):
        self._refresh_exploration(state, cfg, planet_values)

    def _refresh_exploration(self, state, cfg, planet_values):
        min_100k = int(getattr(cfg, "min_planet_value_100k", 10) or 10)
        if min_100k < 0:
            min_100k = 0
        min_value = min_100k * 100_000

        self.min_value_changed.emit(f"{min_100k / 10:.1f}M")

        if not state.bodies:
            hint = (
                "No scan data yet. Tip: Do FSS / honk / nav beacon "
                "so Scan events appear."
            )
            if not planet_values:
                hint += (
                    " (planet_values.json not loaded — copy it to "
                    ".ed_companion or next to main.py)"
                )
            self.exploration_table.setRowCount(0)
            self.exploration_action.setText(
                "🌍 Exploration: no bodies resolved in this system yet."
            )
            self.exploration_hint.setText(hint)
            self._refresh_materials_shortlist(state)
            return

        rows = []
        best_below = None
        bio_bodies = 0
        geo_bodies = 0
        tf_unmapped = 0
        hv_unmapped = 0

        for body, rec in state.bodies.items():
            est = rec.get("EstimatedValue")
            dist = rec.get("DistanceLS")
            pc = rec.get("PlanetClass") or ""
            pc_disp = self._norm_token(pc) or fmt.text(pc, default="")
            tf = rec.get("Terraformable", False)
            was_mapped = bool(rec.get("WasMapped", False))
            dss_mapped = bool(rec.get("DSSMapped", False)) or bool(
                rec.get("BioGenuses")
            )
            human_signals = int(rec.get("HumanSignals", 0) or 0)
            first = rec.get("FirstDiscovered", False)
            bio = rec.get("BioSignals", 0) or 0
            geo = rec.get("GeoSignals", 0) or 0
            gen = rec.get("BioGenuses", []) or []
            landable = rec.get("Landable", False)

            if isinstance(bio, int) and bio > 0:
                bio_bodies += 1
            if isinstance(geo, int) and geo > 0:
                geo_bodies += 1
            if tf and not dss_mapped:
                tf_unmapped += 1
            if isinstance(est, int) and est >= min_value and not dss_mapped:
                hv_unmapped += 1

            sort_val = int(est) if isinstance(est, int) else 0

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
                dist_txt = (
                    (fmt.int_commas(dist) + " LS")
                    if isinstance(dist, (float, int))
                    else ""
                )
                est_txt = fmt.credits(est, default="?")
                tag_txt = (
                    (" [" + ", ".join(preview_tags) + "]")
                    if preview_tags
                    else ""
                )
                preview_line = (
                    f"{body} — {pc_disp} — {dist_txt} — {est_txt}{tag_txt}"
                ).strip()
                if best_below is None or est > best_below[0]:
                    best_below = (est, preview_line)

            dist_txt = (
                (fmt.int_commas(dist) + " LS")
                if isinstance(dist, (float, int))
                else ""
            )
            bio_txt = str(bio) if isinstance(bio, int) and bio > 0 else ""
            geo_txt = str(geo) if isinstance(geo, int) and geo > 0 else ""
            bio_dss_txt = (
                "✔" if isinstance(gen, list) and len(gen) > 0 else ""
            )
            est_txt = (
                fmt.credits(est, default="?") if isinstance(est, int) else "?"
            )
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

            rows.append((
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
                # extras for row styling
                est,
                landable,
                geo,
                min_value,
            ))

        rows.sort(key=lambda x: x[0], reverse=True)

        scanned = len(state.bodies)
        resolved = len(
            getattr(state, "resolved_body_ids", set()) or set()
        )
        total = state.system_body_count
        fss_complete = bool(getattr(state, "fss_complete", False))
        header_bits = []
        if isinstance(total, int) and total > 0:
            if fss_complete:
                header_bits.append(
                    f"Bodies discovered: {total}/{total} • "
                    f"detailed records loaded: {scanned}"
                )
            else:
                remaining = max(0, total - resolved)
                header_bits.append(
                    f"Bodies resolved: {resolved}/{total} "
                    f"(detailed records loaded: {scanned}, "
                    f"unknown remaining: {remaining})"
                )
        else:
            header_bits.append(
                f"Bodies resolved: {scanned} (honk for total count)"
            )

        if not fss_complete and isinstance(total, int) and total > scanned:
            header_bits.append(f"Unresolved bodies: {total - scanned}")

        sigs = getattr(state, "system_signals", None) or []
        if isinstance(sigs, list) and sigs:
            header_bits.append(f"Signals discovered: {len(sigs)}")

        shown = rows[:50]
        self.exploration_table.setRowCount(len(shown))

        for r, row_tuple in enumerate(shown):
            (
                _sv, b, pc, ls_txt, bio_txt, geo_txt, bio_dss_txt,
                v_txt, prev_map_txt, dss_txt, flags_txt,
                est_val, row_landable, row_geo, row_min_value,
            ) = row_tuple

            self.exploration_table.setItem(
                r, 0, QTableWidgetItem(str(b))
            )
            self.exploration_table.setItem(
                r, 1, QTableWidgetItem(str(pc))
            )

            it_ls = QTableWidgetItem(str(ls_txt))
            try:
                s = str(ls_txt).replace("LS", "").replace(",", "").strip()
                v = float(s) if s else None
                if v is not None:
                    it_ls.setData(Qt.ItemDataRole.UserRole, v)
            except Exception:
                pass
            self.exploration_table.setItem(r, 2, it_ls)

            self.exploration_table.setItem(
                r, 3, QTableWidgetItem(str(bio_txt))
            )
            self.exploration_table.setItem(
                r, 4, QTableWidgetItem(str(geo_txt))
            )
            self.exploration_table.setItem(
                r, 5, QTableWidgetItem(str(bio_dss_txt))
            )

            it_val = QTableWidgetItem(str(v_txt))
            try:
                it_val.setData(Qt.ItemDataRole.UserRole, int(_sv))
            except Exception:
                pass
            self.exploration_table.setItem(r, 6, it_val)

            self.exploration_table.setItem(
                r, 7, QTableWidgetItem(str(prev_map_txt))
            )
            self.exploration_table.setItem(
                r, 8, QTableWidgetItem(str(dss_txt))
            )
            self.exploration_table.setItem(
                r, 9, QTableWidgetItem(str(flags_txt))
            )

            # Row styling — fixed: use actual row data not undefined row_data
            try:
                row_color = None
                if isinstance(est_val, int) and est_val >= row_min_value:
                    if row_landable and isinstance(row_geo, int) and row_geo > 0:
                        row_color = "#2A1A00"  # landable geo — amber
                    elif row_landable:
                        row_color = "#0F3057"  # high value + landable — blue
                    else:
                        row_color = "#102A43"  # high value — elite blue
                if row_color:
                    for c in range(self.exploration_table.columnCount()):
                        item = self.exploration_table.item(r, c)
                        if item:
                            item.setBackground(QColor(row_color))
            except Exception:
                pass

        if not shown:
            hint = (
                "No bodies above threshold (or with Geo signals) yet. "
                "Tip: lower the slider, or scan more bodies "
                "(FSS/nav beacon)."
            )
            if best_below:
                hint += (
                    f"\nBest found so far (below threshold): {best_below[1]}"
                )
            self.exploration_hint.setText(
                "\n".join(header_bits) + "\n" + hint
            )
        else:
            self.exploration_hint.setText("\n".join(header_bits))

        self.exploration_action.setText(
            f"🌍 Exploration: {len(shown)} shown • "
            f"{bio_bodies} bodies with bio • "
            f"{geo_bodies} bodies with geo • "
            f"{tf_unmapped} TF unmapped • "
            f"{hv_unmapped} high-value unmapped"
        )

        # System signals box
        try:
            sigs = getattr(state, "system_signals", None) or []
            if isinstance(sigs, list) and sigs:
                out_lines = []
                cat_order = [
                    "Phenomena", "Megaship", "TouristBeacon",
                    "Station", "USS", "Other"
                ]
                cats = {k: [] for k in cat_order}
                cat_counts = {k: 0 for k in cat_order}
                uss_counts = {}
                for s in sigs:
                    if not isinstance(s, dict):
                        continue
                    cat_raw = (
                        s.get("Category")
                        if isinstance(s.get("Category"), str)
                        else "Other"
                    )
                    if cat_raw == "FleetCarrier":
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

                out_lines.append(
                    "Summary: "
                    + " | ".join([
                        f"{k} x{cat_counts[k]}"
                        for k in cat_order
                        if cat_counts.get(k, 0)
                    ])
                )
                if uss_counts:
                    bits = []
                    for k, v in sorted(
                        uss_counts.items(),
                        key=lambda x: (-x[1], str(x[0]).lower())
                    )[:8]:
                        bits.append(f"{k} x{v}")
                    out_lines.append("USS types: " + " | ".join(bits))
                out_lines.append("")

                max_lines = 30
                used = 0
                for cat in cat_order:
                    if not cats[cat]:
                        continue
                    out_lines.append(f"{cat}:")
                    for s in cats[cat]:
                        if used >= max_lines:
                            break
                        nm = (
                            self._norm_token(s.get("SignalName") or "Signal")
                            or "Signal"
                        )
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

                self.system_signals_box.setPlainText(
                    "\n".join(out_lines).strip()
                )
            else:
                fss_complete = getattr(state, "fss_complete", False)
                resolved = len(
                    getattr(state, "resolved_body_ids", set()) or set()
                )
                total = getattr(state, "system_body_count", None)
                if (
                    isinstance(total, int)
                    and not fss_complete
                    and total > resolved
                ):
                    remaining = total - resolved
                    self.system_signals_box.setPlainText(
                        f"{remaining} bodies unresolved. "
                        "Use FSS to discover them."
                    )
                else:
                    self.system_signals_box.setPlainText("")
        except Exception:
            self.system_signals_box.setPlainText("")

        self._refresh_materials_shortlist(state)

    def _refresh_materials_shortlist(self, state):
        try:
            rare = {
                "polonium", "tellurium", "ruthenium", "yttrium",
                "antimony", "arsenic", "selenium", "zirconium",
                "niobium", "tin", "molybdenum", "technetium",
            }
            low_threshold = 25
            low_raw = set()
            inv_raw = getattr(state, "materials_raw", {}) or {}
            if isinstance(inv_raw, dict):
                for k, v in inv_raw.items():
                    if (
                        isinstance(k, str)
                        and isinstance(v, int)
                        and v <= low_threshold
                    ):
                        low_raw.add(k.strip().lower())

            need_raw = low_raw
            targets = []

            for body, rec in (state.bodies or {}).items():
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
                    and "no volcanism" not in volcanism.strip().lower()
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
                    "Tip: resolve bodies (FSS/nav beacon) so Scan events "
                    "populate Landable/Materials/Volcanism."
                )
                return

            out = []
            out.append("Ranked targets (landable + Geo):")
            out.append(
                f"(!) low inventory (≤{low_threshold}) | (*) rarer raw mats"
            )
            out.append("")

            for i, (
                _score, body, geo, dist_v, volcanism, mats
            ) in enumerate(show, 1):
                head = f"{i}. {body}"
                if isinstance(dist_v, float):
                    head += f" — {dist_v:.0f} LS"
                head += f" — Geo {geo}"
                if (
                    isinstance(volcanism, str)
                    and volcanism.strip()
                    and "no volcanism" not in volcanism.lower()
                ):
                    head += " — Volcanism"
                out.append(head)

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

                if (
                    isinstance(volcanism, str)
                    and volcanism.strip()
                    and "no volcanism" not in volcanism.lower()
                ):
                    out.append(f"   Volcanism: {volcanism.strip()}")

            self.materials_box.setPlainText("\n".join(out).strip())
        except Exception:
            self.materials_box.setPlainText("")