# レシート一括入力システム 実装仕様書 (spec.md)

## 1. システム概要
ローカルPC（Mac）環境で実行する、レシート画像の一括解析およびGoogleスプレッドシート自動記帳システム。
ユーザーおよび家族が撮影したレシート画像（JPEG, PNG, HEIC等）を所定フォルダ（`receipts/inbox/`）に投入し、スクリプトを実行することで、**Gemini 3.5 Flash (Vertex AI)** を用いて各画像から取引情報を高精度に構造化抽出し、**Google スプレッドシート** へ一括書き込みおよび画像のアーカイブを行う。

---

## 2. ディレクトリ構成
本リポジトリ直下の構成を以下のように定義する。

```text
receipt-scanner/
├── .env                  # 環境設定（GCPプロジェクトID, スプレッドシートID等 / git除外）
├── .env.example          # 環境設定サンプル
├── .gitignore            # 認証情報や仮想環境、画像ファイルの除外設定
├── credentials/          # 認証鍵格納ディレクトリ（git除外）
│   ├── .gitignore        # service_account.json 除外設定
│   └── service_account.json  # Terraformで自動発行されたサービスアカウント秘密鍵
├── pyproject.toml        # プロジェクト定義・uvパッケージ管理設定
├── uv.lock               # uv 依存関係ロックファイル
├── README.md             # プロジェクト説明書・セットアップ手順
├── spec.md               # 本仕様書
├── main.py               # メイン実行スクリプト（CLIエントリポイント）
├── src/receipt_scanner/  # コアモジュール
│   ├── __init__.py
│   ├── config.py         # 環境設定・ディレクトリパス管理
│   ├── extractor.py      # Gemini 3.5 Flash (Vertex AI) による画像構造化
│   ├── models.py         # Pydantic スキーマ・カテゴリ定義
│   └── sheets.py         # Google Sheets API (gspread) 連携モジュール
├── receipts/             # レシート画像保管ディレクトリ（git除外）
│   ├── inbox/            # 取り込み対象の未処理画像（.jpg, .jpeg, .png, .heic等）
│   ├── archive/          # 処理完了画像（年-月ごとにサブフォルダ移動）
│   └── failed/           # パース・処理失敗画像
└── terraform/            # GCP インフラ自動構築コード
    ├── main.tf
    ├── variables.tf
    ├── services.tf       # Sheets, Drive, Generative Language API
    ├── vertex_ai.tf      # Vertex AI API (aiplatform)
    ├── iam.tf            # サービスアカウント作成、ロール付与、鍵発行
    └── outputs.tf
```

---

## 3. 主要コンポーネント仕様

### 3.1 データスキーマ (`src/receipt_scanner/models.py`)
家計簿の目的である「支出総額の把握」と「特定カテゴリの支出急増時の振り返り」に特化したカテゴリおよび購入品メモを定義。
Gemini API の **Structured Outputs (JSON Schema / Pydantic)** により、型安全な抽出フォーマットを保証する。

```python
from typing import Literal
from pydantic import BaseModel, Field

# 実態に即した家計簿カテゴリ定義
CategoryType = Literal[
    "食費",               # スーパー・コンビニ・外食・カフェ等
    "家具/家電/日用品",    # ドラッグストア、ホームセンター、家具、家電等
    "医療費",             # 病院、クリニック、調剤薬局、医薬品等
    "自動車",             # ガソリンスタンド、コインパーキング、高速代等
    "被服費",             # 洋服、靴、服飾雑貨等
    "美容",               # 美容院、サロン、コスメ等
    "ジム",               # フィットネス、パーソナルジム等
    "その他",             # 上記に明確に該当しないもの
]

class ReceiptData(BaseModel):
    date: str = Field(description="購入日 (YYYY-MM-DD形式)。西暦が不明な場合は現在年を補完")
    store_name: str = Field(description="店舗名または会社名 (正式名称、または一般的な通称)")
    total_amount: int = Field(description="支払合計金額（税込）。値引き・ポイント利用後の実際の最終支払総額")
    category: CategoryType = Field(description="支出カテゴリ")
    memo: str = Field(default="", description="主要購入品目（例: 洗濯洗剤, ガソリン 35L 等、後から振り返れる具体的な品目）")
```

### 3.2 解析エンジン (`src/receipt_scanner/extractor.py`)
* **SDK**: `google-genai` (最新 Google GenAI SDK)
* **認証方式**: サービスアカウント認証 (`GOOGLE_APPLICATION_CREDENTIALS` 経由で Vertex AI に自動認証)
* **モデル**: `gemini-3.5-flash`
* **リージョン**: `us` (米国マルチリージョン)
* **対応画像形式**: JPEG, PNG, WEBP, **HEIC** (`pillow-heif` により iPhone カメラ写真の直接入力に対応)
* **コスト・速度最適化**:
  * **インメモリ画像リサイズ＆JPEG圧縮**: 元の高解像度HEIC（例: `3024×4032`, 約3MB、PNG変換時約12.7MB）をメモリ上でEXIF向き補正のうえ長辺最大 `1024px`・JPEG (`quality=80`, 約150〜200KB) に縮小してから送信し、画像タイル分割数および通信量を大幅削減（元ファイルは無変更でアーカイブ保存）。
  * **思考トークン抑制 & 解像度指定**: `ThinkingLevel.MINIMAL` および `MEDIA_RESOLUTION_MEDIUM` を指定し、不要な推論（出力トークン課金）をカット。
* **プロンプト方針**:
  * お預かり金額（受領額）やお釣りと混同せず、値引き適用後の「最終支払総額（税込）」を確実に抽出。
  * 明細から代表的な購入品目を抽出し、`memo` フィールドに要約。

### 3.3 スプレッドシート連携 (`src/receipt_scanner/sheets.py`)
* **ライブラリ**: `gspread` + `google-auth`
* **認証**: サービスアカウント秘密鍵 (`credentials/service_account.json`)
* **シート列定義**:
  | A列 | B列 | C列 | D列 | E列 | F列 | G列 |
  | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
  | 記帳日時 | 購入日 | 店舗名 | 金額 | カテゴリ | 購入品・内訳メモ | ファイル名 |
* **書き込み方式**:
  * 複数レシートの解析結果をバッファリングし、`append_rows` で一括書き込み（高速化 & API上限対策）。

### 3.4 ファイルライフサイクル管理 (`main.py`, `src/receipt_scanner/config.py`)
1. `receipts/inbox/` 内の画像ファイルを走査。
2. 1枚ずつ順次 Gemini 解析を実行。
3. 成功時:
   * スプレッドシート書き込み用バッファに追加。
   * 画像を `receipts/archive/YYYY-MM/` へ自動移動（同名ファイル衝突回避タイムスタンプ付き）。
4. 失敗時:
   * エラーログを出力し、画像を `receipts/failed/` へ移動。
5. 全件完了後、スプレッドシートへ一括追記してサマリーログを出力。

---

## 4. 実行インターフェース (CLI)

```bash
# 1. 基本実行 (inbox 内の全レシート画像を処理してスプレッドシートに追記)
uv run main.py

# 2. ドライランモード (スプレッドシート書き込み・ファイル移動を行わず解析結果のみ表示)
uv run main.py --dry-run
```

---

## 5. インフラ構成 (Terraform)

`terraform/` ディレクトリ配下のコードでインフラを一元管理する。

* **有効化される API**:
  * `aiplatform.googleapis.com` (Vertex AI API)
  * `sheets.googleapis.com` (Google Sheets API)
  * `drive.googleapis.com` (Google Drive API)
  * `generativelanguage.googleapis.com`
* **作成されるリソース**:
  * サービスアカウント: `receipt-scanner`
  * IAMロール: `roles/aiplatform.user` (Vertex AI 呼び出し権限)
  * 秘密鍵 JSON ファイル自動生成: `credentials/service_account.json` (権限 `0600`)

---

## 6. 実装完了ステータス

* [x] **Phase 1: 環境整備・uvプロジェクト化**
  * `.gitignore`, `pyproject.toml`, `uv.lock`, `.env.example` の作成
  * `src/receipt_scanner/models.py`, `config.py` の実装
* [x] **Phase 2: インフラ自動構築**
  * Terraform による API 有効化、サービスアカウント発行、Vertex AI 権限付与
* [x] **Phase 3: 解析 & スプレッドシート連携モジュール実装**
  * `extractor.py`（Gemini 3.5 Flash, Vertex AI, HEIC対応）
  * `sheets.py`（gspread, サービスアカウント認証, ヘッダー自動生成, 一括追記）
* [x] **Phase 4: メインパイプライン結合 & CLI実装**
  * `main.py`（ファイル移動、サマリー表示、`--dry-run` 対応）
  * 実際の iPhone レシート画像（HEIC）でのエンドツーエンド実稼働検証完了
