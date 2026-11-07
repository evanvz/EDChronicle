import fnmatch
import json
from pathlib import Path

HERE = Path(__file__).parent
AREAS_PATH = HERE / "areas.json"
BASELINES_PATH = HERE / "baselines.json"
LIVE_CONFIRMED_PATH = HERE / "live_confirmed.json"

AREA_ORDER = [
    "Overview/HUD", "BGS & factions", "Powerplay", "Colonisation & system planner",
    "Exploration & exobiology", "Trade, markets & routes", "Mining", "Missions",
    "Megaships", "Engineering & materials", "Combat scanners", "Squadron",
    "EDDN sending", "EDDataHub link", "Raven Colonial & EDSM push", "Voice", "Other",
]


def load_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _matches(rel_path: str, kind: str, areas: dict) -> list[str]:
    key = "modules" if kind == "module" else "tests"
    return [name for name, a in areas.items()
            if any(fnmatch.fnmatchcase(rel_path, g) for g in a.get(key, []))]


def area_of(rel_path: str, kind: str, areas: dict) -> str:
    hits = _matches(rel_path, kind, areas)
    return hits[0] if hits else "Other"


def mapping_problems(repo_root: Path, areas: dict) -> dict:
    repo_root = Path(repo_root)
    files = [(p, "module") for pat in ("edc/**/*.py", "persistence/*.py")
             for p in repo_root.glob(pat)]
    files += [(p, "test") for p in repo_root.glob("tests/test_*.py")]
    unmapped, ambiguous = [], []
    for p, kind in sorted(files):
        if p.name == "__init__.py" or "__pycache__" in p.parts:
            continue
        rel = p.relative_to(repo_root).as_posix()
        hits = _matches(rel, kind, areas)
        if not hits:
            unmapped.append(rel)
        elif len(hits) > 1:
            ambiguous.append(rel)
    return {"unmapped": unmapped, "ambiguous": ambiguous}


def area_of_logger(name: str, repo_root: Path, areas: dict) -> str:
    if not name.startswith("edc."):
        return "Other"
    rel = name.replace(".", "/")
    rel += "/__init__.py" if (Path(repo_root) / rel).is_dir() else ".py"
    return area_of(rel, "module", areas)
