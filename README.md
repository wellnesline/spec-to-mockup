# spec-to-mockup

Turns a screen-definition file (`screens.yaml`) into a sitemap diagram and a set of clickable HTML mockups, with automated link and layout audits.

画面定義の YAML（`screens.yaml`）から、サイトマップ図とクリックできる HTML モックを生成し、リンク切れ・到達不能画面・レイアウト崩れを自動検査するスクリプト群です。公開用に整理したサンプル実装です。

## 概要

Web アプリの画面構成を、仕様の段階で発注者と合意するためのツールです。画面の ID・階層・遷移・配置のヒントを 1 つの YAML に集約し、そこから図とモックを機械的に作ります。人の目視だけに頼らず、遷移の抜けや表示の崩れをスクリプトで検出します。

## 主な機能・設計のポイント

- **単一の定義から複数の成果物を生成**: `screens.yaml` から、Excalidraw 形式のサイトマップ（`render.py`）、Mermaid 形式のサイトマップ（`render_mermaid.py`）、モックが読む `screens-data.js`（`build_screens_data.py`）を作ります。
- **共通シェル方式**: 各 HTML は本体だけを持ち、サイドバー・パンくず・サブナビは共通の `shell.js` が実行時に注入します（`refactor_to_shell.py`）。画面ごとのナビの不整合が構造的に起きません。`file://` でも動くよう、データは JSON を fetch せず `window.SCREENS_DATA` として読み込みます。
- **静的検査**（`check_html_full.py`、`check_html_links.py`）: リンク先の HTML が存在するか（dead link）、起点画面から辿れない画面（orphan）がないか、`data-screen-id` が定義に登録されているか、必要な 3 点セットが揃っているかを検査します。
- **視覚検査**（`check_html_visual.py`）: ヘッドレス Chromium（Playwright）で各画面を開き、サイドバーとサブナビの位置、横スクロールの有無、スタイルシートの読み込みを検査し、失敗した画面のスクリーンショットだけを保存します。失敗があれば終了コード 1 です。
- **オーケストレーション**: `run_all.py` が 4 工程（データ生成 → シェル化 → 静的検査 → 視覚検査）を順に実行し、どれかが失敗したら全体を失敗にします。`run.py` は人間の確認ゲートを挟む半自律パイプラインの管理役で、状態を `state.json` に保存し、各段階の前提ファイルを機械検証します。AI エージェントの起動自体は行いません（呼び出し側が行う想定）。

## ディレクトリ構成

```
run_all.py               4 工程を 1 コマンドで実行
run.py                   人間ゲート付きパイプラインの状態管理
build_screens_data.py    screens.yaml -> screens-data.js
build_html_mockups.py    共通テンプレートから全画面の HTML モックを生成
refactor_to_shell.py     HTML を「本体 + shell.js」の形式に縮約
render.py / render_mermaid.py   サイトマップ図の生成
check_html_full.py / check_html_links.py / check_html_visual.py   各種検査
mockups/screens.yaml     画面定義の最小サンプル（合成）
```

## 動かし方

必要なもの: Python 3.10 以上、`pyyaml`、視覚検査には `playwright`（と Chromium）。

```powershell
pip install pyyaml playwright
python -m playwright install chromium
python run_all.py                        # 4 工程を順に実行（このディレクトリで）
python render_mermaid.py mockups/screens.yaml sitemap.md
```

環境変数・外部サービスの鍵は使いません。

## 制限事項（閉包）

- **同梱していない依存**（2 件）: `yaml`（PyYAML）、`playwright`。`requirements` ファイルは同梱していません。
- **合成サンプル**: `mockups/screens.yaml` は、架空のアプリを想定したスキーマ例（最小）です。実在の製品や画面とは無関係です。
- 次のファイルは同梱していません: 共通シェル（`mockups/clickable/shell.js`）、生成済みの `screens-data.js`、画面のモック画像、生成済み HTML。これらが無いと `run_all.py` の後半の工程は通りません。`shell.js` は自前で用意してください。
- 生成した HTML は CSS フレームワーク（Tailwind、daisyUI）と Web フォントを CDN から読み込みます。オフラインでは見た目が崩れ、視覚検査も失敗します。
- 画面定義の作成（architect）と図のレビューは AI エージェントが行う前提の工程です。そのエージェント定義の例は `claude-code-agent-patterns` にあります。
- Excalidraw 版の図は、矢印の交差を完全には最適化しません（目視で許容を判断する前提）。

## ライセンス

All rights reserved. 閲覧目的で公開しています。詳細は LICENSE を参照。
