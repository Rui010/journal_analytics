from datetime import date
from decimal import Decimal
import unittest
from unittest.mock import patch

from journal_analytics.training import (
    build_training_analysis_input,
    format_training_details_for_prompt,
    normalize_training_record,
    summarize_by_day,
)
from journal_analytics.training_runner import build_daily_training_summary


class TrainingNormalizationTests(unittest.TestCase):
    def test_normalizes_numeric_and_text_weights_in_jst(self):
        numeric = normalize_training_record(
            {
                "create_datetime": "2026-08-28T16:30:00Z",
                "menu": "ダンベルプレス",
                "part": "胸",
                "weight": Decimal("12"),
                "rep": "15",
                "set": "4",
            }
        )
        text = normalize_training_record(
            {"create_datetime": "2026-08-29 07:00:00", "weight": "自重"}
        )
        empty = normalize_training_record(
            {"create_datetime": "2026-08-29 07:00:00", "weight": ""}
        )
        self.assertEqual(numeric.date.isoformat(), "2026-08-29")
        self.assertEqual((numeric.weight, numeric.weight_type), (12, "numeric"))
        self.assertEqual((text.weight, text.weight_type), ("自重", "text"))
        self.assertEqual((empty.weight, empty.weight_type), (None, None))

    def test_invalid_values_are_retained_as_missing(self):
        record = normalize_training_record(
            {"create_datetime": "2026-08-29 07:00:00", "rep": "many", "set": "1.5"}
        )
        self.assertIsNone(record.reps)
        self.assertIsNone(record.sets)
        self.assertIsNone(normalize_training_record({"create_datetime": "invalid"}))

    def test_daily_summary_includes_days_without_records(self):
        records = [
            normalize_training_record(
                {"create_datetime": "2026-08-29 07:00:00", "menu": "ステッパー", "set": "1"}
            ),
            normalize_training_record(
                {"create_datetime": "2026-08-29 08:00:00", "menu": "ダンベルプレス", "set": "10"}
            ),
        ]
        summaries = summarize_by_day(records, date(2026, 8, 29), date(2026, 8, 30))
        self.assertEqual(summaries[0]["training"]["activity_level"], "full_workout")
        self.assertEqual(summaries[0]["training"]["set_count"], 10)
        self.assertEqual(summaries[0]["training"]["duration_minutes_total"], 0)
        self.assertEqual(
            summaries[0]["training"]["exercises"],
            [
                {
                    "menu": "ステッパー",
                    "part": None,
                    "records": [
                        {
                            "weight": None,
                            "weight_type": None,
                            "reps": None,
                            "sets": 1,
                            "duration_minutes": None,
                        }
                    ],
                },
                {
                    "menu": "ダンベルプレス",
                    "part": None,
                    "records": [
                        {
                            "weight": None,
                            "weight_type": None,
                            "reps": None,
                            "sets": 10,
                            "duration_minutes": None,
                        }
                    ],
                },
            ],
        )
        self.assertEqual(summaries[1]["training"], {
            "performed": False,
            "record_count": 0,
            "set_count": 0,
            "duration_minutes_total": 0,
            "parts": [],
            "menus": [],
            "activity_level": "none",
            "exercises": [],
        })

    def test_normalized_data_never_contains_email(self):
        record = normalize_training_record(
            {
                "create_datetime": "2026-08-29 07:00:00",
                "email": "private@example.com",
            }
        )
        self.assertNotIn("email", record.to_dict())

    @patch("journal_analytics.training_runner.fetch_training_records")
    def test_runner_returns_only_daily_summary(self, fetch_records):
        fetch_records.return_value = [
            {
                "create_datetime": "2026-08-29 07:00:00",
                "menu": "ダンベルプレス",
                "set": "4",
                "email": "private@example.com",
            }
        ]
        summary = build_daily_training_summary(date(2026, 8, 29), date(2026, 8, 29))
        self.assertEqual(summary["period"]["start_date"], "2026-08-29")
        self.assertEqual(summary["days"][0]["training"]["set_count"], 4)
        self.assertEqual(
            summary["days"][0]["training"]["exercises"][0]["records"][0],
            {
                "weight": None,
                "weight_type": None,
                "reps": None,
                "sets": 4,
                "duration_minutes": None,
            },
        )
        self.assertNotIn("email", str(summary))

    def test_stepper_and_bike_reps_are_converted_to_minutes(self):
        records = [
            normalize_training_record(
                {"create_datetime": "2026-08-29 07:00:00", "menu": "ステッパー", "rep": "30分"}
            ),
            normalize_training_record(
                {"create_datetime": "2026-08-29 08:00:00", "menu": "エアロバイク", "rep": "1時間"}
            ),
        ]
        summary = summarize_by_day(records, date(2026, 8, 29), date(2026, 8, 29))[0]
        self.assertEqual(summary["training"]["set_count"], 0)
        self.assertEqual(summary["training"]["duration_minutes_total"], 90)
        self.assertEqual(
            [
                record["duration_minutes"]
                for exercise in summary["training"]["exercises"]
                for record in exercise["records"]
            ],
            [30, 60],
        )

    def test_training_prompt_keeps_weight_reps_and_sets(self):
        record = normalize_training_record(
            {
                "create_datetime": "2026-08-29 07:00:00",
                "menu": "ダンベルプレス",
                "weight": "12",
                "rep": "15",
                "set": "4",
            }
        )
        summary = summarize_by_day([record], date(2026, 8, 29), date(2026, 8, 29))[0]
        self.assertIn("ダンベルプレス", format_training_details_for_prompt(summary))
        self.assertIn("12 / 15回 / 4セット", format_training_details_for_prompt(summary))
        self.assertIn("## 2026-08-29", build_training_analysis_input([summary]))


if __name__ == "__main__":
    unittest.main()
