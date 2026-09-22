import json
import re
import time
from bs4 import BeautifulSoup
from datetime import date, datetime, timedelta
import os
from dotenv import load_dotenv
from google import genai
from google.genai.errors import APIError
from typing import Any, Dict, Optional
from pathlib import Path

from .training import build_training_analysis_input, format_training_for_prompt
from .training_runner import build_daily_training_summary

load_dotenv()


def read_journal_entry(input_path: Path) -> tuple[date, str] | None:
    """Return one exported journal entry, keyed by the ISO date in its filename."""
    match = re.match(r"(\d{4}-\d{2}-\d{2})", input_path.name)
    if not match:
        return None
    entry_date = date.fromisoformat(match.group(1))
    with input_path.open("r", encoding="utf-8") as file:
        soup = BeautifulSoup(file, "html.parser")
    header = soup.find("div", class_="pageHeader")
    title = soup.find("div", class_="title")
    body_texts = [p.text.strip() for p in soup.find_all("p", class_="p2")]
    markdown = f"# {header.text.strip() if header else entry_date.isoformat()}\n\n"
    if title and title.text.strip():
        markdown += f"## {title.text.strip()}\n\n"
    markdown += "\n".join(text for text in body_texts if text)
    return entry_date, markdown.strip()


def build_combined_markdown(
    journal_entries: dict[date, list[str]], daily_summaries: list[dict[str, Any]]
) -> str:
    sections = []
    for summary in daily_summaries:
        entry_date = date.fromisoformat(summary["date"])
        journal_text = "\n\n".join(journal_entries.get(entry_date, [])) or "記録なし"
        training_text = format_training_for_prompt(summary)
        sections.append(
            f"## {entry_date.isoformat()}\n\n### ジャーナル記録\n{journal_text}"
            f"\n\n### トレーニング実績\n{training_text}"
        )
    return "\n\n".join(sections)


def parse_text_by_llm(content: str, prompt_filename: str) -> Optional[Dict[str, Any]]:
    """
    Gemini APIを使ってJSONデータを辞書で返す。

    Returns:
        dict: パース済みのデータ（辞書形式）。失敗時は None。
    """
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise ValueError("GEMINI_API_KEYが設定されていません")

    prompt = load_prompt_template(prompt_filename, content=content)

    max_retries = 3
    retry_delay = 60  # 秒

    for attempt in range(1, max_retries + 1):
        try:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model="gemini-2.5-flash-lite",
                contents=prompt,
            )
            time.sleep(1)  # レート制限対策のためのスリープ
            # Markdownコードブロック（```json ～ ```）を除去
            cleaned_text = re.sub(
                r"^```json\s*|\s*```$", "", response.text.strip(), flags=re.DOTALL
            )
            return json.loads(cleaned_text)

        except APIError as e:  # API制限エラー
            if e.code in {502, 503, 504}:
                # logger.info(
                #     f"サーバーエラー {e.code}が発生しました。リトライ {attempt}/{max_retries}"
                # )
                if attempt < max_retries:
                    time.sleep(retry_delay)
                    continue
                else:
                    # logger.error(f"リトライ回数を超えました: {e}")
                    raise SystemExit(
                        "Gemini APIのサーバエラーにより、プログラムを終了します。"
                    ) < e
            else:
                # logger.error(f"Gemini APIの制限に達しました: {e}")
                print(f"Gemini APIの制限に達しました: {e}")
                raise SystemExit(
                    "Gemini APIの制限に達したため、プログラムを終了します。"
                )

        except json.JSONDecodeError as e:
            # logger.error(f"[JSON ERROR] パース失敗: {e}")
            # logger.error(f"[RAW OUTPUT] {response.text}")
            return None

        except Exception as e:
            # logger.error(f"予期しないエラーが発生しました: {e}")
            return None


def load_prompt_template(filename: str, **kwargs) -> str:
    """
    指定されたテンプレートファイルを読み込み、変数を埋め込んで返す
    """
    base_dir = Path(__file__).resolve().parents[1]  # プロジェクトルート
    prompt_path = base_dir / "journal_analytics" / "prompts" / filename

    with open(prompt_path, encoding="utf-8") as f:
        template = f.read()
    return template.format(**kwargs)


def save_data(file_path: str, data: Dict[str, Any]) -> None:
    """
    分析データをJSONファイルとして保存する

    Args:
        file_path (str): 保存先のファイルパス
        data (Dict[str, Any]): 保存するデータ（辞書形式）
    """
    try:
        # 出力ディレクトリがない場合は作成
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        # JSONファイルとして保存
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"分析データを保存しました: {file_path}")

    except IOError as e:
        print(f"エラー: ファイルの保存に失敗しました: {str(e)}")
    except TypeError as e:
        print(f"エラー: データ形式が不正です: {str(e)}")
    except Exception as e:
        print(f"エラー: 予期せぬエラーが発生しました: {str(e)}")


def main():
    try:
        input_dir = Path("./journal_analytics/input")
        output_dir = Path("./journal_analytics/output")
        today_str = datetime.now().strftime("%Y-%m-%d")
        output_journal_path = output_dir / today_str / "journal.md"
        output_analysis_path = output_dir / today_str / "output.txt"
        output_training_path = output_dir / today_str / "daily_training_summary.json"

        entries = [
            entry
            for path in input_dir.glob("*.html")
            if (entry := read_journal_entry(path)) is not None
        ]
        entries.sort(key=lambda entry: entry[0], reverse=True)
        entries = entries[:60]
        if not entries:
            print(f"エラー: ジャーナルHTMLが見つかりません: {input_dir}")
            return

        lookback_days = int(os.getenv("TRAINING_LOOKBACK_DAYS", "30"))
        if lookback_days < 1:
            raise ValueError("TRAINING_LOOKBACK_DAYSは1以上にしてください")
        end_date = entries[0][0]
        start_date = end_date - timedelta(days=lookback_days - 1)
        selected_entries = [entry for entry in entries if start_date <= entry[0] <= end_date]
        journal_by_date: dict[date, list[str]] = {}
        for entry_date, markdown in selected_entries:
            journal_by_date.setdefault(entry_date, []).append(markdown)

        training_summary = build_daily_training_summary(start_date, end_date)
        daily_summaries = training_summary["days"]
        markdown_content = build_combined_markdown(journal_by_date, daily_summaries)

        output_journal_path.parent.mkdir(parents=True, exist_ok=True)
        output_journal_path.write_text(markdown_content, encoding="utf-8")
        save_data(
            str(output_training_path),
            training_summary,
        )
        print(f"ジャーナルとトレーニングを結合しました: {output_journal_path}")

        journal_analysis = parse_text_by_llm(markdown_content, "analysis.md")
        training_analysis = parse_text_by_llm(
            build_training_analysis_input(daily_summaries), "training_analysis.md"
        )
        combined_analysis = {
            "period": training_summary["period"],
            "journal_analysis": journal_analysis,
            "training_analysis": training_analysis,
        }
        print("ジャーナル分析とトレーニング分析を行いました")
        save_data(str(output_analysis_path), combined_analysis)

    except Exception as e:
        print(f"エラーが発生しました: {str(e)}")


if __name__ == "__main__":

    main()
