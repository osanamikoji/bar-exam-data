# bar-exam-data

法務省サイトから収集した司法試験・予備試験の全年度データ。

## 収録内容

| 試験種別 | 年度 | ドキュメント種別 |
|---------|------|---------------|
| 予備試験（yobi） | 平成23年〜令和8年 | 試験問題・出題の趣旨・採点実感・正答配点 |
| 本試験（honshiken） | 平成18年〜令和8年 | 試験問題・出題の趣旨・採点実感・正答配点 |

## ディレクトリ構造

```
data/
  yobi/
    reiwa_05/
      mondai/       # 試験問題 PDF + TXT
      seito/        # 正答・配点
      shuppaitsushi/ # 出題の趣旨
      saitenjikkan/ # 採点実感
  honshiken/
    reiwa_05/
      ...
manifest.json       # 全ファイルのメタデータ
```

## スクレイパーの実行

```bash
pip install pdfplumber requests beautifulsoup4
python3 scraper.py
```

## データソース

- 予備試験: https://www.moj.go.jp/jinji/shihoushiken/jinji07_00026.html
- 本試験: https://www.moj.go.jp/jinji/shihoushiken/jinji08_00025.html

著作権は法務省に帰属します。研究・学習目的での利用に限ります。
