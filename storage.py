import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

MATCHES_JSONL = DATA_DIR / "matches.jsonl"
SUMMONERS_JSON = DATA_DIR / "summoners.json"


def append_jsonl(filepath: Path, records: Iterable[Dict[str, Any]]) -> None:
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with filepath.open("a", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_summoners() -> List[Dict[str, Any]]:
    if not SUMMONERS_JSON.exists():
        return []
    with SUMMONERS_JSON.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_summoners(items: List[Dict[str, Any]]) -> None:
    SUMMONERS_JSON.parent.mkdir(parents=True, exist_ok=True)
    with SUMMONERS_JSON.open("w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2) 