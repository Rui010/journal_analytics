import json
import re
import time
from bs4 import BeautifulSoup
from datetime import datetime
import os
from dotenv import load_dotenv
from google import genai
from google.genai.errors import APIError
from typing import Any, Dict, Optional
from pathlib import Path


load_dotenv()


def post_html_to_md(input_path, output_path):
    try:
        # 出力ディレクトリがない場合は作成
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # HTMLファイルを読み込み
        with open(input_path, "r", encoding="utf-8") as file:
            soup = BeautifulSoup(file, "html.parser")

        # 必要な要素を抽出
        header = soup.find("div", class_="pageHeader").text.strip()
        title = soup.find("div", class_="title").text.strip()
        body_texts = [p.text.strip() for p in soup.find_all("p", class_="p2")]

        # マークダウン形式でテキストを構築
        markdown_content = f"""# {header}

## {title}

{chr(10).join(body_texts)}
"""

        # ファイルに書き込み（追記モード）
        with open(output_path, "a", encoding="utf-8") as file:
            file.write(markdown_content + "\n\n")

    except FileNotFoundError:
        print(f"エラー: ファイルが見つかりません: {input_path}")
    except Exception as e:
        print(f"エラー: HTMLの変換に失敗しました: {str(e)}")


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
                model="gemini-2.0-flash-lite",
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
        input_dir = "./journal_analytics/input"
        output_dir = "./journal_analytics/output"
        today_str = datetime.now().strftime("%Y-%m-%d")
        output_journal_path = os.path.join(output_dir, today_str, "journal.md")
        output_analysis_path = os.path.join(output_dir, today_str, "output.txt")

        # HTMLファイルの変換
        html_files = [f for f in os.listdir(input_dir) if f.endswith(".html")]
        html_files.sort(reverse=True)  # 日付が先頭にある場合はこれで降順ソート

        for filename in html_files:
            input_path = os.path.join(input_dir, filename)
            post_html_to_md(input_path, output_journal_path)
            print(
                f"ジャーナルのデータをマークダウンに変換しました: {output_journal_path}"
            )

        # マークダウンファイルの読み込み
        if os.path.exists(output_journal_path):
            with open(output_journal_path, "r", encoding="utf-8") as f:
                markdown_content = f.read()

            # LLMによる分析
            analysis_data = parse_text_by_llm(markdown_content, "analysis.md")
            print(f"LLMで分析を行いました: {analysis_data}")
            save_data(output_analysis_path, analysis_data)
        else:
            print(
                f"エラー: マークダウンファイルが見つかりません: {output_journal_path}"
            )

    except Exception as e:
        print(f"エラーが発生しました: {str(e)}")


if __name__ == "__main__":

    main()
