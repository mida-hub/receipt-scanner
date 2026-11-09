# レシート一括入力システム 実装仕様書 (spec.md)

## 1. システム概要
ローカルPC（Mac）環境で実行する、レシート画像の一括解析およびGoogleスプレッドシート自動記帳システム。
ユーザーおよび家族が撮影したレシート画像を所定フォルダ（`inbox`）に投入し、スクリプトを実行することで、Gemini APIを用いて各画像から取引情報を高精度に構造化抽出し、Googleスプレッドシートへ一括書き込みおよび画像のアーカイブを行う。

---

## 2. ディレクトリ構成
本リポジトリ直下の構成を以下のように定義する。

```text
receipt-scanner/
├── .env                  # 環境変数（GEMINI_API_KEY, SPREADSHEET_ID等、git除外）
├── .env.example          # 環境変数のサンプル
├── .gitignore            # 認証情報や仮想環境、画像ファイルの除外設定
├── credentials.json      # Google Cloud サービスアカウント鍵（git除外）
├── requirements.txt      # 依存Pythonライブラリ一覧
├── main.py               # メイン実行スクリプト（CLIエントリポイント）
├── src/
│   ├── __init__.py
│   ├── config.py         # 環境設定・ディレクトリパス読み込み
│   ├── extractor.py      # Gemini API による画像解析・構造化データ抽出
│   ├── models.py         # Pydantic によるレシートデータスキーマ定義
│   └── sheets.py         # Google Sheets API (gspread) 連携モジュール
├── receipts/             # レシート画像保管ディレクトリ（git除外）
│   ├── inbox/            # 取り込み対象の未処理画像（.jpg, .jpeg, .png, .heic等）
│   ├── archive/          # 処理完了画像（年-月ごとにサブフォルダ移動）
│   └── failed/           # パース・処理失敗画像
├── plan.md               # 検討用ドキュメント (LINE + GAS案)
├── plan_v2.md            # 検討用ドキュメント (ローカルバッチ案)
└── spec.md               # 本実装仕様書
```

---

## 3. 主要コンポーネント仕様

### 3.1 データスキーマ (`src/models.py`)
Gemini API の **Structured Outputs (JSON Schema / Pydantic)** を使用して、抽出フォーマットを厳密に固定する。

```python
from pydantic import BaseModel, Field
from typing import Literal

CategoryType = Literal[
    "食費",
    "日用品",
    "住居・光熱費",
    "交通費",
    "交際費・娯楽",
    "衣服・美容",
    "健康・医療",
    "教育・教養",
    "その他"
]

class ReceiptData(BaseModel):
    date: str = Field(description="購入日 (YYYY-MM-DD形式)。西暦が不明な場合は現在年を補完")
    store_name: str = Field(description="店舗名または会社名 (正式名または一般的な略称)")
    total_amount: int = Field(description="支払合計金額（税込）。数値のみ")
    category: CategoryType = Field(description="店舗や購入内容から推測される最適な支出カテゴリ")
    payment_method: str = Field(default="不明", description="支払方法（現金, クレジットカード, PayPay, 交通系IC等）")
    memo: str = Field(default="", description="主要品目や特筆事項の簡単なメモ")
```

### 3.2 解析エンジン (`src/extractor.py`)
* **SDK**: `google-genai` (Google GenAI SDK) または `google-generativeai`
* **モデル**: `gemini-2.5-flash` または `gemini-1.5-pro` (速度と精度のバランスで設定可能にする)
* **対応画像形式**: JPEG, PNG, HEIC (iPhone撮影を考慮し `pillow-heif` で自動変換対応)
* **プロンプト方針**:
  * レシートの歪み・印字かすれ・合計金額と小計/お預かり金額の混同を防ぐためのガイドラインを明記。
  * `response_schema=ReceiptData` による 100% JSON 保証。

### 3.3 スプレッドシート連携 (`src/sheets.py`)
* **ライブラリ**: `gspread`
* **認証**: Google Cloud サービスアカウント (`credentials.json`)
* **シート列定義**:
  | A列 | B列 | C列 | D列 | E列 | F列 | G列 |
  | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
  | 記帳日時 | 購入日 | 店舗名 | 金額 | カテゴリ | 支払方法 | 元画像ファイル名 / メモ |
* **書き込み方式**:
  * 1枚ごとに都度書き込まず、複数レシートの解析結果をバッファリングし、`append_rows` で一括書き込み（APIリクエスト数の削減と高速化）。

### 3.4 ファイルライフサイクル管理 (`src/config.py`, `main.py`)
1. `receipts/inbox/` 内の画像ファイルを走査。
2. 1枚ずつ順次（または並列）で Gemini 解析。
3. 成功時:
   * スプレッドシート書き込み用リストに追加。
   * 画像を `receipts/archive/YYYY-MM/` へ移動。
4. 失敗時:
   * エラーログを出力し、画像を `receipts/failed/` へ移動（リカバリ容易化）。
5. 全件完了後、スプレッドシートへ一括追記してサマリーログを出力。

---

## 4. 実行インターフェース (CLI)

```bash
# 1. 基本実行 (inbox の全画像を処理)
python main.py

# 2. オプション (例: プレビュー・ドライランモード)
python main.py --dry-run   # スプレッドシートやファイル移動を行わず、解析結果のみ標準出力
```

---

## 5. セットアップ・必要な前提条件

### 5.1 Google Cloud プロジェクト設定
1. Google Cloud Console で新規プロジェクト作成。
2. **Google Drive API** および **Google Sheets API** を有効化。
3. サービスアカウントを作成し、キー（JSON）をダウンロードして `credentials.json` として配置。
4. 記録先のスプレッドシートを作成し、サービスアカウントのメールアドレス（`xxx@xxx.iam.gserviceaccount.com`）に**編集権限**を付与。

### 5.2 Gemini API キー
1. Google AI Studio または Google Cloud で APIキーを取得。
2. `.env` ファイルに `GEMINI_API_KEY` として設定。

### 5.3 依存ライブラリ
```text
google-generativeai>=0.8.0
pydantic>=2.0.0
gspread>=6.0.0
Pillow>=10.0.0
pillow-heif>=0.18.0
python-dotenv>=1.0.0
```

---

## 6. 実装フェーズ

* [ ] **Phase 1: 環境整備・モデル定義**
  * `.gitignore`, `requirements.txt`, `.env.example` の作成
  * `src/models.py`, `src/config.py` の実装
* [ ] **Phase 2: Gemini OCR/解析モジュールの実装**
  * `src/extractor.py` の実装（HEIC変換・Pydantic構造化出力）
  * サンプル画像を用いたパース単体テスト
* [ ] **Phase 3: スプレッドシート連携モジュール実装**
  * `src/sheets.py` の実装（サービスアカウント認証・一括追記）
* [ ] **Phase 4: メインパイプライン結合 & CLI作成**
  * `main.py` の実装（inbox走査・移動・ドライランオプション対応）
