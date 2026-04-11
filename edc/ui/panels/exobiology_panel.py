import logging
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QTextEdit,
)
from PyQt6.QtCore import pyqtSignal

log = logging.getLogger(__name__)


class ExobiologyPanel(QWidget):
    """
    Owns all widgets and refresh logic for the Exobiology tab.
    Receives state, cfg, and exo_values via refresh().

    Emits exo_min_value_changed(str) so main_window can update
    the exo_min_label in the Settings tab.
    """

    exo_min_value_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Exobiology"))

        self.exo_action = QLabel("")
        self.exo_action.setWordWrap(True)
        layout.addWidget(self.exo_action)

        self.exo_hint = QLabel("")
        self.exo_hint.setWordWrap(True)
        layout.addWidget(self.exo_hint)

        self.exo_display = QTextEdit()
        self.exo_display.setReadOnly(True)
        self.exo_display.setMinimumHeight(120)

        layout.addWidget(self.exo_display, 1)

    def _norm_text(self, v):
        try:
            return " ".join(str(v).split())
        except Exception:
            return ""

    def _variant_color(self, v):
        if not isinstance(v, str):
            return ""
        s = self._norm_text(v)
        if not s:
            return ""
        if " - " in s:
            try:
                return s.split(" - ", 1)[1].strip()
            except Exception:
                return s
        return s

    def refresh(self, state, cfg, exo_values):
        try:
            if not isinstance(state.bodies, dict):
                state.bodies = {}

            bio_map = getattr(state, "bio_signals", {}) or {}
            genus_map = getattr(state, "bio_genuses", {}) or {}
            geo_map = getattr(state, "geo_signals", {}) or {}

            for body_name, bio_cnt in bio_map.items():
                if not isinstance(body_name, str) or not body_name.strip():
                    continue
                rec = state.bodies.get(body_name)
                if not isinstance(rec, dict):
                    rec = {"BodyName": body_name, "BodyID": None}
                if isinstance(bio_cnt, int):
                    rec["BioSignals"] = bio_cnt
                if body_name in genus_map:
                    rec["BioGenuses"] = genus_map.get(body_name, []) or []
                if body_name in geo_map:
                    rec["GeoSignals"] = geo_map.get(body_name, 0) or 0
                state.bodies[body_name] = rec
        except Exception:
            pass

        has_bio_targets = False
        for _b, _rec in (state.bodies or {}).items():
            if not isinstance(_rec, dict):
                continue
            bio = _rec.get("BioSignals", 0) or 0
            if isinstance(bio, int) and bio > 0:
                has_bio_targets = True
                break

        if not state.exo and not has_bio_targets:
            self.exo_display.setHtml("")
            self.exo_action.setText(
                "🔬 Exobiology: no biological signals detected "
                "in this system yet."
            )
            self.exo_hint.setText(
                "Tip: Use FSS to find Biological signals, "
                "then DSS a planet to reveal genus."
            )
            return

        rows = []
        try:
            exo_m = int(getattr(cfg, "exo_high_value_m", 2) or 2)
        except Exception:
            exo_m = 2
        exo_min = exo_m * 1_000_000

        self.exo_min_value_changed.emit(f"{exo_m}M")

        active = 0
        complete = 0
        high_value = 0
        targets = 0
        scanned_species = 0

        genus_max = {}
        try:
            if exo_values:
                for _rec in exo_values.by_species.values():
                    g = getattr(_rec, "genus", None)
                    bv = getattr(_rec, "base_value", None)
                    if (
                        isinstance(g, str)
                        and g.strip()
                        and isinstance(bv, int)
                    ):
                        gg = g.strip()
                        genus_max[gg] = max(
                            int(genus_max.get(gg, 0) or 0), int(bv)
                        )
        except Exception:
            genus_max = {}

        body_key_by_norm = {}
        try:
            for _bn in (state.bodies or {}).keys():
                nk = self._norm_text(_bn)
                if nk and nk not in body_key_by_norm:
                    body_key_by_norm[nk] = _bn
        except Exception:
            body_key_by_norm = {}

        body_key_by_id = {}
        body_rec_by_id = {}
        try:
            for _bn, _br in (state.bodies or {}).items():
                if not isinstance(_br, dict):
                    continue
                bid = _br.get("BodyID")
                if isinstance(bid, int) and bid not in body_key_by_id:
                    body_key_by_id[bid] = _bn
                    body_rec_by_id[bid] = _br
        except Exception:
            body_key_by_id = {}
            body_rec_by_id = {}

        real_body_genus_name = set()
        real_body_genus_id = set()
        codex_body_genus_id = set()
        codex_body_genus_name = set()
        listed_body_genus_name = set()
        listed_body_genus_id = set()
        codex_hint_name = {}
        codex_hint_id = {}
        codex_hint_var_name = {}
        codex_hint_var_id = {}
        codex_hint_base_name = {}
        codex_hint_base_id = {}
        codex_pending = []

        for key, rec in (state.exo or {}).items():
            body_id = rec.get("BodyID")
            body_name = None
            if isinstance(body_id, int):
                body_name = (
                    state.body_id_to_name.get(body_id)
                    or body_key_by_id.get(body_id)
                )
            body_txt = body_name or (
                f"Body {body_id}" if body_id is not None else "Unknown Body"
            )

            genus = rec.get("Genus", "")
            species = rec.get("Species", "")
            samples = int(rec.get("Samples", 0) or 0)
            last = (rec.get("LastScanType") or "").upper()

            if last == "CODEX":
                gk = str(genus or "").strip()
                if not gk:
                    continue
                bn = self._norm_text(body_name or body_txt)
                sp = species or rec.get("CodexName") or ""
                try:
                    sp = str(sp).strip()
                except Exception:
                    sp = ""
                vv = self._variant_color(
                    rec.get("Variant") or rec.get("CodexName") or ""
                )
                if isinstance(body_id, int):
                    codex_hint_id[(body_id, gk)] = sp
                    if vv:
                        codex_hint_var_id[(body_id, gk)] = vv
                    codex_body_genus_id.add((body_id, gk))
                if bn:
                    codex_hint_name[(bn, gk)] = sp
                    if vv:
                        codex_hint_var_name[(bn, gk)] = vv
                    codex_body_genus_name.add((bn, gk))

                bv = rec.get("BaseValue")
                if not isinstance(bv, int):
                    bv = rec.get("PotentialValue")
                if not isinstance(bv, int):
                    nm = rec.get("CodexName") or rec.get("Species") or ""
                    if (
                        isinstance(nm, str)
                        and nm.strip()
                        and exo_values
                    ):
                        k2 = nm.strip()
                        exo_rec = exo_values.by_species.get(k2)
                        if exo_rec is None and " - " in k2:
                            exo_rec = exo_values.by_species.get(
                                k2.split(" - ", 1)[0].strip()
                            )
                        if exo_rec is not None and isinstance(
                            getattr(exo_rec, "base_value", None), int
                        ):
                            bv = exo_rec.base_value
                if isinstance(bv, int) and bv > 0:
                    if isinstance(body_id, int):
                        codex_hint_base_id[(body_id, gk)] = bv
                    if bn:
                        codex_hint_base_name[(bn, gk)] = bv
                codex_pending.append((body_txt, rec))
                continue
            else:
                status = (
                    "COMPLETE"
                    if rec.get("Complete")
                    else (last or "IN PROGRESS")
                )

            pot_v = rec.get("PotentialValue")
            pot_txt = f"{pot_v:,} cr" if isinstance(pot_v, int) else ""
            base_v = rec.get("BaseValue")

            if not isinstance(base_v, int):
                nm = (
                    rec.get("Variant")
                    or rec.get("Species")
                    or rec.get("CodexName")
                    or ""
                )
                if isinstance(nm, str) and nm.strip() and exo_values:
                    k2 = nm.strip()
                    exo_rec = exo_values.by_species.get(k2)
                    if exo_rec is None and " - " in k2:
                        exo_rec = exo_values.by_species.get(
                            k2.split(" - ", 1)[0].strip()
                        )
                    if exo_rec is not None and isinstance(
                        getattr(exo_rec, "base_value", None), int
                    ):
                        base_v = exo_rec.base_value
            base_txt = f"{base_v:,} cr" if isinstance(base_v, int) else ""

            prog_txt = f"{samples}/3" if status != "CODEX" else "0/3"
            var_txt = self._variant_color(rec.get("Variant") or "")

            ccr_txt = ""
            ccr_ok = False
            try:
                req = rec.get("CCRRequiredM")
                dist = rec.get("CCRDistanceM")
                if isinstance(req, int) and req > 0:
                    if not isinstance(dist, int) or dist < 0:
                        dist = 0
                    ccr_txt = f"{dist}/{req}m"
                    ccr_ok = dist >= req
            except Exception:
                ccr_txt = ""
                ccr_ok = False

            rows.append((
                samples, status, body_txt, genus, species,
                var_txt, pot_txt, base_txt, prog_txt, ccr_txt,
                ccr_ok, status
            ))
            scanned_species += 1

            gk = str(genus or "").strip()
            if gk:
                if isinstance(body_id, int):
                    real_body_genus_id.add((body_id, gk))
                bn = self._norm_text(body_name)
                if bn:
                    real_body_genus_name.add((bn, gk))
                if isinstance(body_id, int):
                    listed_body_genus_id.add((body_id, gk))
                if bn:
                    listed_body_genus_name.add((bn, gk))

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

        for body, rec in (state.bodies or {}).items():
            if not isinstance(rec, dict):
                continue
            bio = rec.get("BioSignals", 0) or 0
            if not isinstance(bio, int) or bio <= 0:
                continue
            body_id = rec.get("BodyID")

            gen = rec.get("BioGenuses", []) or []
            if isinstance(gen, list) and gen:
                for g in gen:
                    gk = str(g or "").strip()
                    if not gk:
                        continue
                    if (
                        isinstance(body_id, int)
                        and (body_id, gk) in real_body_genus_id
                    ) or (
                        (self._norm_text(body), gk) in real_body_genus_name
                    ):
                        continue
                    pot = genus_max.get(gk)
                    sp = ""
                    vv = ""
                    try:
                        if isinstance(body_id, int):
                            sp = codex_hint_id.get((body_id, gk), "") or ""
                            vv = codex_hint_var_id.get(
                                (body_id, gk), ""
                            ) or ""
                        if not sp:
                            sp = codex_hint_name.get(
                                (self._norm_text(body), gk), ""
                            ) or ""
                        if not vv:
                            vv = codex_hint_var_name.get(
                                (self._norm_text(body), gk), ""
                            ) or ""
                    except Exception:
                        sp = ""
                        vv = ""
                    pot_txt = "" if sp or vv else (
                        f"{pot:,} cr"
                        if isinstance(pot, int) and pot > 0
                        else ""
                    )
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
                            bv = codex_hint_base_name.get(
                                (self._norm_text(body), gk)
                            )
                        if not isinstance(bv, int) and sp and exo_values:
                            k2 = sp
                            exo_rec = exo_values.by_species.get(k2)
                            if exo_rec is None and " - " in k2:
                                exo_rec = exo_values.by_species.get(
                                    k2.split(" - ", 1)[0].strip()
                                )
                            if exo_rec is not None and isinstance(
                                getattr(exo_rec, "base_value", None), int
                            ):
                                bv = exo_rec.base_value
                        if isinstance(bv, int) and bv > 0:
                            base_txt = f"{bv:,} cr"
                    except Exception:
                        base_txt = ""
                    rows.append((
                        0, status_txt, body, gk, sp, vv,
                        pot_txt, base_txt, "0/3", status_txt
                    ))
                    targets += 1
                    if isinstance(pot, int) and pot >= exo_min:
                        high_value += 1
                    if isinstance(body_id, int):
                        listed_body_genus_id.add((body_id, gk))
                    if isinstance(body, str) and body.strip():
                        listed_body_genus_name.add(
                            (self._norm_text(body), gk)
                        )
            else:
                genus_txt = f"{bio} bio signals"
                status_txt = f"NEEDS DSS (Bio: {bio})"
                rows.append((
                    0, status_txt, body, genus_txt,
                    "", "", "", "", "0/3", status_txt
                ))
                targets += 1

        seen_codex = set()
        for body_txt, rec in (codex_pending or []):
            body_id = rec.get("BodyID")
            genus = str(rec.get("Genus", "") or "").strip()
            if not genus:
                continue
            body_name = None
            if isinstance(body_id, int):
                body_name = (
                    state.body_id_to_name.get(body_id)
                    or body_key_by_id.get(body_id)
                )
            body_key = body_id if isinstance(body_id, int) else (
                body_name.strip()
                if isinstance(body_name, str) and body_name.strip()
                else body_txt
            )
            dk = (body_key, genus)
            if dk in seen_codex:
                continue
            seen_codex.add(dk)

            try:
                br = None
                if isinstance(body_id, int):
                    br = body_rec_by_id.get(body_id)
                bn = self._norm_text(body_name or body_txt)
                if bn and bn in body_key_by_norm:
                    br = (state.bodies or {}).get(
                        body_key_by_norm.get(bn)
                    )
                if br is None and isinstance(body_name, str) and body_name.strip():
                    br = (state.bodies or {}).get(body_name.strip())
                if br is None:
                    br = (state.bodies or {}).get(body_txt)
                if isinstance(br, dict):
                    dss_gen = br.get("BioGenuses", []) or []
                    if isinstance(dss_gen, list) and any(
                        str(x or "").strip() == genus for x in dss_gen
                    ):
                        continue
            except Exception:
                pass

            if (
                isinstance(body_id, int)
                and (body_id, genus) in listed_body_genus_id
            ) or (
                (self._norm_text(body_name or body_txt), genus)
                in listed_body_genus_name
            ):
                continue
            if (
                isinstance(body_id, int)
                and (body_id, genus) in real_body_genus_id
            ) or (
                (self._norm_text(body_name or body_txt), genus)
                in real_body_genus_name
            ):
                continue

            pot_txt = ""
            base_v = rec.get("BaseValue")
            if not isinstance(base_v, int) and exo_values:
                nm = rec.get("CodexName") or rec.get("Species") or ""
                if isinstance(nm, str) and nm.strip():
                    k2 = nm.strip()
                    exo_rec = exo_values.by_species.get(k2)
                    if exo_rec is None and " - " in k2:
                        exo_rec = exo_values.by_species.get(
                            k2.split(" - ", 1)[0].strip()
                        )
                    if exo_rec is not None and isinstance(
                        getattr(exo_rec, "base_value", None), int
                    ):
                        base_v = exo_rec.base_value
            base_txt = f"{base_v:,} cr" if isinstance(base_v, int) else ""
            species_txt = rec.get("Species") or rec.get("CodexName") or ""
            if not isinstance(species_txt, str):
                species_txt = ""
            var_txt = self._variant_color(
                rec.get("Variant") or rec.get("CodexName") or ""
            )
            rows.append((
                0, "CODEX", body_txt, genus, species_txt.strip(),
                var_txt, pot_txt, base_txt, "0/3", "CODEX"
            ))

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

        # Group by body
        bodies_order = []
        bodies_data = {}
        for row in shown:
            if not isinstance(row, (list, tuple)):
                continue
            if len(row) == 10:
                _samples, _status, body_txt, genus, species, \
                    var_txt, pot_txt, base_txt, prog_txt, status_txt = row
                ccr_txt = ""
                ccr_ok = False
            elif len(row) == 11:
                _samples, _status, body_txt, genus, species, \
                    var_txt, pot_txt, base_txt, prog_txt, \
                    ccr_txt, status_txt = row
                ccr_ok = False
            else:
                _samples, _status, body_txt, genus, species, \
                    var_txt, pot_txt, base_txt, prog_txt, \
                    ccr_txt, ccr_ok, status_txt = row

            if body_txt not in bodies_data:
                bodies_order.append(body_txt)
                bodies_data[body_txt] = []
            bodies_data[body_txt].append({
                "genus":    genus,
                "species":  species,
                "variant":  var_txt,
                "base":     base_txt,
                "progress": prog_txt,
                "ccr":      ccr_txt,
                "ccr_ok":   ccr_ok,
                "status":   status_txt,
                "samples":  _samples,
            })

        status_colors = {
            "COMPLETE":    "#6BCB77",
            "IN PROGRESS": "#FFD93D",
            "ANALYSE":     "#FFD93D",
            "UNSCANNED":   "#AAAAAA",
            "CODEX":       "#C77DFF",
            "NEEDS DSS":   "#FF6B6B",
        }

        def _status_color(s):
            s = str(s or "").upper()
            for k, v in status_colors.items():
                if s.startswith(k):
                    return v
            return "#AAAAAA"

        def _esc(t):
            return str(t or "").replace(
                "&", "&amp;"
            ).replace("<", "&lt;").replace(">", "&gt;")

        html = []
        html.append(
            '<style>'
            '.bh { color: #4D96FF; font-weight: 700; '
            'font-size: 14px; margin-top: 8px; }'
            '.gr { margin-left: 16px; margin-top: 4px; }'
            '.st { font-weight: 700; }'
            '.dm { color: #888888; }'
            '</style>'
        )

        for body_txt in bodies_order:
            entries = bodies_data[body_txt]
            html.append(
                f'<div class="bh">🪐 {_esc(body_txt)}</div>'
            )
            for e in entries:
                sc = _status_color(e["status"])
                is_active = (
                    isinstance(e["samples"], int)
                    and e["samples"] > 0
                    and e["status"] != "COMPLETE"
                )
                if is_active:
                    line = (
                        '<div class="gr" style="'
                        'background-color:#1a3a5c;'
                        'border-left:3px solid #4D96FF;'
                        'padding:3px 6px;'
                        'border-radius:4px;'
                        'margin-top:4px;">'
                    )
                else:
                    line = '<div class="gr">'
                line += (
                    f'<span class="st" style="color:{sc};">'
                    f'{_esc(e["status"])}</span> '
                    f'<b>{_esc(e["genus"])}</b>'
                )

                if e["species"]:
                    line += f' — {_esc(e["species"])}'
                if e["variant"]:
                    line += (
                        f' <span class="dm">'
                        f'({_esc(e["variant"])})</span>'
                    )
                line += (
                    f' &nbsp;<span class="dm">'
                    f'{_esc(e["progress"])}</span>'
                )
                if e["base"]:
                    line += (
                        f' &nbsp;<span style="color:#FFD93D;">'
                        f'{_esc(e["base"])}</span>'
                    )
                if e["ccr"]:
                    ccr_color = e.get("ccr_ok") and "#6BCB77" or "#888888"
                    line += (
                        f' &nbsp;<span style="color:{ccr_color};'
                        f'font-weight:700;">'
                        f'CCR:{_esc(e["ccr"])}</span>'
                    )
                line += '</div>'
                html.append(line)

        self.exo_display.setHtml("".join(html))

        if has_bio_targets:
            self.exo_action.setText(
                f"🔬 Exobiology: {targets} targets • "
                f"{scanned_species} scanned • "
                f"{complete} complete • "
                f"{high_value} high-value (≥ {exo_m}M)"
            )
            if not state.exo:
                self.exo_hint.setText(
                    "Biological signals detected. DSS a body to "
                    "reveal genus; land to start samples."
                )
        else:
            self.exo_action.setText(
                f"🔬 Exobiology: {active} active • "
                f"{complete} complete • "
                f"{high_value} high-value (≥ {exo_m}M)"
            )
