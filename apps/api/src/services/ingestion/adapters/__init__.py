"""Adapter registry. Order matters only in that the first match wins."""

from src.services.ingestion.adapters.ashby import AshbyAdapter
from src.services.ingestion.adapters.base import AdapterError, ATSAdapter
from src.services.ingestion.adapters.greenhouse import GreenhouseAdapter
from src.services.ingestion.adapters.lever import LeverAdapter
from src.services.ingestion.adapters.smartrecruiters import SmartRecruitersAdapter
from src.services.ingestion.adapters.workday import WorkdayAdapter

ADAPTERS: list[ATSAdapter] = [
    GreenhouseAdapter(),
    LeverAdapter(),
    AshbyAdapter(),
    SmartRecruitersAdapter(),
    WorkdayAdapter(),
]


def find_adapter(url: str) -> ATSAdapter | None:
    for adapter in ADAPTERS:
        try:
            if adapter.matches(url):
                return adapter
        except ValueError:
            continue
    return None


__all__ = ["ADAPTERS", "ATSAdapter", "AdapterError", "find_adapter"]
