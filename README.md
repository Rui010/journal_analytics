# JOURNAL ANALYTICS

## 概要

- iOS標準アプリのジャーナルのデータを書き出し、LLMで分析を行う
    - 直近の心の状態の分析
    - 過去の心の状態の推移

## 使い方

1. ジャーナルアプリからデータを書き出す
2. icloudのファイルからデータをダウンロード
3. inputフォルダに格納する
4. 実行する

```
python -m journal_analytics.main
```

## トレーニング記録の統合

実行時に、ジャーナルHTMLの最新日を終点とする直近30日分を対象に、
DynamoDBのトレーニング記録を日別サマリーとして結合します。DynamoDBへの書き込みは行いません。

事前に依存関係をインストールし、AWSの標準credential chain（AWS profile、環境変数、IAM roleなど）で
`Trainings` テーブルを読み取れる認証を設定してください。

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m journal_analytics.main
```

任意の環境変数です。

```text
TRAINING_AWS_REGION=ap-northeast-1
TRAINING_DYNAMODB_TABLE=Trainings
TRAINING_LOOKBACK_DAYS=30
```

出力先の実行日ディレクトリには、結合済みの `journal.md`、
日別集計の `daily_training_summary.json`、LLM分析結果の `output.txt` を保存します。
`output.txt` には `journal_analysis` と `training_analysis` を別々に保存します。前者はジャーナルと活動記録の併記、後者は種目ごとの記録を分析します。
トレーニングの生レコードや `email` は出力・LLM入力に含めません。
日別集計JSONには、種目ごとの重量・回数・セットを記録順に残します。種目間の重量や回数は合算しません。
ステッパー・バイクは回数欄を時間として分へ変換し、`duration_minutes` と日別の `duration_minutes_total` に保存します。時間はセット数・回数・重量と合算しません。

トレーニング集計だけを行う場合は、こちらを実行します。ジャーナルHTMLとGeminiは使いません。

```powershell
.\.venv\Scripts\python.exe -m journal_analytics.training_main
```

期間を指定する場合:

```powershell
.\.venv\Scripts\python.exe -m journal_analytics.training_main --start-date 2026-08-23 --end-date 2026-09-21
```

トレーニング専用のGemini分析も保存する場合は `--analyze` を付けます。
この分析はジャーナルや気分を扱わず、種目ごとの記録、継続状況、記録上の注意点だけを対象にします。

```powershell
.\.venv\Scripts\python.exe -m journal_analytics.training_main --analyze
```
