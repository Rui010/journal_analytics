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