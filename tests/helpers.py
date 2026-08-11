"""Gemensamt för testerna."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kvittokoll.storage import Store  # noqa: E402


def temp_store(tmp_path, sources=None, settings=None):
    """Ett Store i en tom katalog, med projektets profiler tillgängliga."""
    root = Path(tmp_path)
    (root / "profiles").mkdir(parents=True, exist_ok=True)
    for profile in (ROOT / "profiles").glob("*.json"):
        (root / "profiles" / profile.name).write_bytes(profile.read_bytes())

    store = Store(root, settings=settings or {})
    if sources:
        store.data_dir.mkdir(parents=True, exist_ok=True)
        with (store.data_dir / "sources.json").open("w", encoding="utf-8") as stream:
            json.dump(sources, stream, ensure_ascii=False)
    return store


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()
