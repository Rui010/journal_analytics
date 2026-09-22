"""Create a daily training summary without journal or Gemini processing."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

from .main import parse_text_by_llm
from .training_runner import build_daily_training_summary
from .training import JST, build_training_analysis_input


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DynamoDBのトレーニング記録を日別集計します")
    parser.add_argument("--start-date", type=date.fromisoformat, help="開始日 (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=date.fromisoformat, help="終了日 (YYYY-MM-DD)")
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="トレーニング専用プロンプトでGemini分析も保存する",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    end_date = args.end_date or datetime.now(JST).date()
    lookback_days = int(os.getenv("TRAINING_LOOKBACK_DAYS", "30"))
    if lookback_days < 1:
        raise ValueError("TRAINING_LOOKBACK_DAYSは1以上にしてください")
    start_date = args.start_date or end_date - timedelta(days=lookback_days - 1)
    if start_date > end_date:
        raise ValueError("start-dateはend-date以前にしてください")

    summary = build_daily_training_summary(start_date, end_date)
    output_path = Path("journal_analytics/output") / end_date.isoformat() / "daily_training_summary.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"日別トレーニングサマリーを保存しました: {output_path}")

    if args.analyze:
        prompt_content = build_training_analysis_input(summary["days"])
        analysis = parse_text_by_llm(prompt_content, "training_analysis.md")
        analysis_path = output_path.with_name("training_analysis.json")
        analysis_path.write_text(
            json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"トレーニング分析を保存しました: {analysis_path}")


if __name__ == "__main__":
    main()
