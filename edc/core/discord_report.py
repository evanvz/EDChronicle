# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
# See the LICENSE file in the project root for full terms.

"""
Session BGS activity as Discord text in BGS-Tally's default layout
(aussig/BGS-Tally, MIT; see THIRD_PARTY_NOTICES.md), so squad members get the
format they already know. The text is copied to the clipboard for the user to
paste; nothing is posted anywhere.

One ```ansi block per system (name bold white), one line per faction with
activity (name bold yellow), non-zero items only, each a coloured label and a
green value. INF here is our own signed total (primary and secondary effects),
matching the Session BGS Activity Report.
"""

_FG = {"red": 31, "green": 32, "yellow": 33, "blue": 34, "cyan": 36, "white": 37}


def _c(s, fg: str, bold: bool = False) -> str:
    return f"\x1b[{_FG[fg]}{';1' if bold else ''}m{s}\x1b[0m"


def human_format(num: int) -> str:
    """1300 -> 1.3K, as BGS-Tally's utils.human_format."""
    abbrs = ["", "K", "M", "B", "T"]
    fnum = float("{:.3g}".format(num))
    magnitude = 0
    while abs(fnum) >= 1000 and magnitude < len(abbrs) - 1:
        magnitude += 1
        fnum /= 1000.0
    return "{}{}".format("{:f}".format(fnum).rstrip("0").rstrip("."), abbrs[magnitude])


def _merge_days(report: dict) -> dict:
    """{system: {faction: totals}} summed over the dates in the tick window."""
    out: dict = {}
    for systems in report.values():
        for system, factions in systems.items():
            for faction, e in factions.items():
                t = out.setdefault(system, {}).setdefault(faction, {
                    "inf": 0, "bvs": 0, "cbs": 0, "buy": 0, "profit": 0, "expl": 0,
                    "cz": {k: 0 for k in ("space_l", "space_m", "space_h", "ground_l", "ground_m", "ground_h")}})
                t["inf"] += e["missions"]["weighted"]
                t["bvs"] += e["bounties_total"]
                t["cbs"] += e["combat_bonds_total"]
                t["buy"] += e["trade_sold"].get("purchase", 0)
                t["profit"] += e["trade_sold"].get("commodity", 0)
                t["expl"] += e["trade_sold"].get("exploration", 0)
                for k in t["cz"]:
                    t["cz"][k] += e["cz_kills"].get(k, 0)
    return out


def _cz(t: dict, kind: str, label: str) -> str:
    text = "".join(f"{size.upper()} x {_c(t['cz'][f'{kind}_{size}'], 'green')} "
                   for size in "lmh" if t["cz"][f"{kind}_{size}"])
    return f"{_c(label, 'red')} {text} " if text else ""


def _faction_line(name: str, t: dict) -> str:
    items = ""
    if t["inf"]:
        items += f"{_c('INF', 'blue')} {_c(('+' if t['inf'] > 0 else '') + str(t['inf']), 'green')} "
    for label, key, fg in (("BVs", "bvs", "red"), ("CBs", "cbs", "red"), ("TrdBuy", "buy", "cyan"),
                           ("TrdProfit", "profit", "cyan"), ("Expl", "expl", "white")):
        if t[key]:
            items += f"{_c(label, fg)} {_c(human_format(t[key]), 'green')} "
    items += _cz(t, "space", "SpaceCZs") + _cz(t, "ground", "GroundCZs")
    return f"{_c(name, 'yellow', bold=True)} {items}\n" if items else ""


def bgs_tally_text(report: dict, system: str = None, merits: dict = None) -> str:
    """Repository.get_session_activity_report() output as Discord text, for one
    system (all days of the tick window summed) or, without `system`, all of them.
    merits ({date: {system: {power: merits}}}, Repository.get_session_merits) adds
    a merits line per power for the report's systems."""
    merged = _merge_days(report)
    in_report = {s for systems in report.values() for s in systems}
    pp: dict = {}
    for systems in (merits or {}).values():
        for name, powers in systems.items():
            if name in in_report:
                for power, n in powers.items():
                    pp.setdefault(name, {})[power] = pp.get(name, {}).get(power, 0) + n
    text = ""
    for name in sorted(set(merged) | set(pp)):
        if system is not None and name != system:
            continue
        lines = "".join(f"{_c(p, 'yellow', bold=True)} {_c('Merits', 'cyan')} {_c(human_format(n), 'green')} \n"
                        for p, n in sorted(pp.get(name, {}).items()) if n)
        lines += "".join(_faction_line(f, t) for f, t in sorted(merged.get(name, {}).items()))
        if lines:
            text += f"```ansi\n{_c(name, 'white', bold=True)}\n{lines}```"
    return text.replace("'", "")  # as BGS-Tally does
