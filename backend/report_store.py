import json
import time
import uuid
from collections import OrderedDict
from pathlib import Path

from models import BlastRadiusReport

_store: OrderedDict[str, tuple[dict, float]] = OrderedDict()
_MAX_REPORTS = 200
_TTL_SECONDS = 3600

STATIC_REPORTS_DIR = Path(__file__).parent / "static_reports"
STATIC_REPORTS_DIR.mkdir(exist_ok=True)


async def store_report(report: BlastRadiusReport) -> str:
    report_id = str(uuid.uuid4())
    _store[report_id] = (report.model_dump(), time.monotonic())
    if len(_store) > _MAX_REPORTS:
        _store.popitem(last=False)
    return report_id


async def get_report(report_id: str) -> dict | None:
    # Check in-memory store first
    entry = _store.get(report_id)
    if entry:
        data, created_at = entry
        if time.monotonic() - created_at <= _TTL_SECONDS:
            return data
        del _store[report_id]

    # Fall back to static file
    path = STATIC_REPORTS_DIR / f"{report_id}.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    return None


async def save_static_report(report_id: str, report: dict) -> None:
    path = STATIC_REPORTS_DIR / f"{report_id}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f)
