"""Training-record normalization and daily summaries.

This module deliberately has no AWS dependency so its behavior can be tested
with ordinary dictionaries returned by DynamoDB.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable


# Japan has no daylight-saving time.  A fixed offset avoids requiring the
# optional tzdata package on Windows while still expressing Asia/Tokyo times.
JST = timezone(timedelta(hours=9), name="Asia/Tokyo")
LIGHT_ACTIVITY_KEYWORDS = ("ステッパー", "ストレッチ", "肩甲骨", "ウォーキング")
TIME_BASED_MENU_KEYWORDS = ("ステッパー", "バイク")
FULL_WORKOUT_MIN_SETS = 10


@dataclass(frozen=True)
class TrainingRecord:
    datetime: datetime
    date: date
    menu: str | None
    part: str | None
    weight: int | float | str | None
    weight_type: str | None
    reps: int | None
    sets: int | None
    duration_minutes: int | None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["datetime"] = self.datetime.isoformat()
        result["date"] = self.date.isoformat()
        return result


def parse_jst_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=JST)
    return parsed.astimezone(JST)


def local_date_from_raw_datetime(value: Any) -> date | None:
    parsed = parse_jst_datetime(value)
    return parsed.date() if parsed else None


def safe_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite() or number != number.to_integral_value():
        return None
    return int(number)


def normalize_weight(value: Any) -> tuple[int | float | str | None, str | None]:
    if value is None:
        return None, None
    text = str(value).strip()
    if not text:
        return None, None
    try:
        number = Decimal(text)
    except InvalidOperation:
        return text, "text"
    if not number.is_finite():
        return text, "text"
    if number == number.to_integral_value():
        return int(number), "numeric"
    return float(number), "numeric"


def normalize_training_record(raw: dict[str, Any]) -> TrainingRecord | None:
    occurred_at = parse_jst_datetime(raw.get("create_datetime"))
    if occurred_at is None:
        return None
    menu = _clean_text(raw.get("menu"))
    part = _clean_text(raw.get("part"))
    weight, weight_type = normalize_weight(raw.get("weight"))
    raw_rep = raw.get("rep")
    is_time_based = _is_time_based_menu(menu)
    return TrainingRecord(
        datetime=occurred_at,
        date=occurred_at.date(),
        menu=menu,
        part=part,
        weight=weight,
        weight_type=weight_type,
        reps=None if is_time_based else safe_int(raw_rep),
        sets=safe_int(raw.get("set")),
        duration_minutes=parse_duration_minutes(raw_rep) if is_time_based else None,
    )


def summarize_by_day(
    records: Iterable[TrainingRecord], start_date: date, end_date: date
) -> list[dict[str, Any]]:
    grouped: dict[date, list[TrainingRecord]] = {}
    for record in records:
        if start_date <= record.date <= end_date:
            grouped.setdefault(record.date, []).append(record)

    summaries = []
    current = start_date
    while current <= end_date:
        daily_records = grouped.get(current, [])
        menus = sorted({record.menu for record in daily_records if record.menu})
        parts = sorted({record.part for record in daily_records if record.part})
        strength_records = [
            record for record in daily_records if not _is_time_based_menu(record.menu)
        ]
        set_count = sum(record.sets or 0 for record in strength_records)
        duration_minutes_total = sum(record.duration_minutes or 0 for record in daily_records)
        summaries.append(
            {
                "date": current.isoformat(),
                "training": {
                    "performed": bool(daily_records),
                    "record_count": len(daily_records),
                    "set_count": set_count,
                    "duration_minutes_total": duration_minutes_total,
                    "parts": parts,
                    "menus": menus,
                    "activity_level": _activity_level(menus, set_count),
                    "exercises": _summarize_exercises(daily_records),
                },
            }
        )
        current += timedelta(days=1)
    return summaries


def format_training_for_prompt(summary: dict[str, Any]) -> str:
    training = summary["training"]
    if not training["performed"]:
        return "記録なし"
    details = [f"{training['set_count']}セット", training["activity_level"]]
    if training["duration_minutes_total"]:
        details.append(f"時間ベース活動 {training['duration_minutes_total']}分")
    if training["parts"]:
        details.append("・".join(training["parts"]))
    return "、".join(details)


def format_training_details_for_prompt(summary: dict[str, Any]) -> str:
    """Format one daily summary for training-only analysis without PII."""
    training = summary["training"]
    if not training["performed"]:
        return "記録なし"
    lines = [
        f"活動レベル: {training['activity_level']}",
        f"合計セット数: {training['set_count']}",
    ]
    for exercise in training["exercises"]:
        measurements = []
        for record in exercise["records"]:
            weight = record["weight"] if record["weight"] is not None else "重量記録なし"
            sets = record["sets"] if record["sets"] is not None else "セット数記録なし"
            if record["duration_minutes"] is not None:
                measurements.append(f"{record['duration_minutes']}分")
            else:
                reps = record["reps"] if record["reps"] is not None else "回数記録なし"
                measurements.append(f"{weight} / {reps}回 / {sets}セット")
        part = f"（{exercise['part']}）" if exercise["part"] else ""
        lines.append(f"- {exercise['menu'] or '種目記録なし'}{part}: {'; '.join(measurements)}")
    return "\n".join(lines)


def build_training_analysis_input(daily_summaries: Iterable[dict[str, Any]]) -> str:
    return "\n\n".join(
        f"## {daily['date']}\n{format_training_details_for_prompt(daily)}"
        for daily in daily_summaries
    )


def _activity_level(menus: list[str], set_count: int) -> str:
    if not menus:
        return "none"
    strength_menus = [
        menu for menu in menus if not any(keyword in menu for keyword in LIGHT_ACTIVITY_KEYWORDS)
    ]
    if len(strength_menus) >= 2 or set_count >= FULL_WORKOUT_MIN_SETS:
        return "full_workout"
    return "light"


def _summarize_exercises(records: list[TrainingRecord]) -> list[dict[str, Any]]:
    """Keep per-exercise measurements without making cross-exercise totals."""
    grouped: dict[tuple[str | None, str | None], list[TrainingRecord]] = {}
    for record in sorted(records, key=lambda item: item.datetime):
        grouped.setdefault((record.menu, record.part), []).append(record)

    return [
        {
            "menu": menu,
            "part": part,
            "records": [
                {
                    "weight": record.weight,
                    "weight_type": record.weight_type,
                    "reps": record.reps,
                    "sets": record.sets,
                    "duration_minutes": record.duration_minutes,
                }
                for record in exercise_records
            ],
        }
        for (menu, part), exercise_records in grouped.items()
    ]


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_duration_minutes(value: Any) -> int | None:
    """Convert the personal time formats used for stepper and bike records."""
    if isinstance(value, bool) or value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    numeric = safe_int(text)
    if numeric is not None:
        return numeric if numeric >= 0 else None

    hour_match = re.fullmatch(r"(?:(\d+)時間)?\s*(?:(\d+)分)?", text)
    if hour_match and (hour_match.group(1) or hour_match.group(2)):
        return int(hour_match.group(1) or 0) * 60 + int(hour_match.group(2) or 0)

    clock_match = re.fullmatch(r"(\d+):(\d{2})(?::\d{2})?", text)
    if clock_match:
        first, second = (int(value) for value in clock_match.groups())
        return first * 60 + second if ":" in text and text.count(":") == 2 else first
    return None


def _is_time_based_menu(menu: str | None) -> bool:
    return bool(menu and any(keyword in menu for keyword in TIME_BASED_MENU_KEYWORDS))
