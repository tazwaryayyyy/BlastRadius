import time
import uuid
from collections import OrderedDict

from models import BlastRadiusReport

_store: OrderedDict[str, tuple[dict, float]] = OrderedDict()
_MAX_REPORTS = 200
_TTL_SECONDS = 3600


async def store_report(report: BlastRadiusReport) -> str:
    report_id = str(uuid.uuid4())
    _store[report_id] = (report.model_dump(), time.monotonic())
    if len(_store) > _MAX_REPORTS:
        _store.popitem(last=False)
    return report_id


async def get_report(report_id: str) -> dict | None:
    entry = _store.get(report_id)
    if not entry:
        return None
    data, created_at = entry
    if time.monotonic() - created_at > _TTL_SECONDS:
        del _store[report_id]
        return None
    return data
