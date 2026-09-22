"""Shared training-summary workflow used by both command entry points."""

from __future__ import annotations

from datetime import date
from typing import Any

from .training import normalize_training_record, summarize_by_day
from .training_repository import fetch_training_records


def build_daily_training_summary(start_date: date, end_date: date) -> dict[str, Any]:
    raw_records = fetch_training_records(start_date, end_date)
    records = [
        record for raw in raw_records if (record := normalize_training_record(raw)) is not None
    ]
    return {
        "period": {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        "days": summarize_by_day(records, start_date, end_date),
    }
