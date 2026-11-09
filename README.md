# Receipt Scanner (レシート一括解析＆自動記帳システム)

スマホで撮影したレシート画像をフォルダに放り込み、コマンドを実行するだけで **Gemini 3.5 Flash (Vertex AI)** が高精度に構造化（店舗名・金額・日付・カテゴリ・振り返り用購入品メモ）し、**Google スプレッドシート** へ一括自動記帳するシステムです。

---

## 🌟 特徴

* **APIキー管理不要（サービスアカウント認証）**:
  * Google Cloud サービスアカウントの秘密鍵 1 つで、Vertex AI の Gemini モデル呼び出しと Google Sheets API への記帳の両方をセキュアに完結。
* **家計簿の振り返りに最適化されたカテゴリ設計**:
  * 食費、家具/家電/日用品、医療費、自動車、被服費、美容、ジム など実態に合わせた分類。
  * 「今月このカテゴリが増えたのはなぜか？」を振り返りやすいよう、レシート内の主要品目を自動でメモ列に記録。
* **iPhone (HEIC) 写真対応**:
  * iPhoneの標準カメラで撮影された `.HEIC` 形式、一般的な `.jpg`, `.jpeg`, `.png`, `.webp` をそのまま投入可能。
* **安全なファイルライフサイクル管理**:
  * 処理完了画像は `receipts/archive/YYYY-MM/` へ自動退避。
  * 失敗画像は `receipts/failed/` に移動するため、再試行や手動確認が容易。
  * 書き込み前に確認できる `--dry-run` モード搭載。

---

## 📁 ディレクトリ構成

```text
receipt-scanner/
├── .env                  # 環境設定（GCPプロジェクトID, スプレッドシートID等 / git除外）
├── .env.example          # 環境設定サンプル
├── credentials/          # サービスアカウント鍵（git除外）
│   └── service_account.json
├── main.py               # 実行エントリポイント
├── receipts/             # レシート画像保管場所（git除外）
│   ├── inbox/            # 取り込み対象の未処理画像置き場
│   ├── archive/          # 処理完了画像（年-月ごとにサブフォルダ分け）
│   └── failed/           # 処理失敗画像
├── src/receipt_scanner/  # コアモジュール
│   ├── config.py         # 環境設定・ディレクトリパス
│   ├── extractor.py      # Gemini 3.5 Flash による画像構造化
│   ├── models.py         # Pydantic スキーマ定義 (カテゴリ等)
│   └── sheets.py         # Google スプレッドシート連携
└── terraform/            # GCP インフラ定義 (API有効化 & サービスアカウント)
```

---

## 🛠️ セットアップ

### 1. 動作要件
* Python 3.12+
* [uv](https://docs.astral.sh/uv/)（パッケージマネージャー）
* Google Cloud プロジェクト & スプレッドシート

### 2. インストール
```bash
git clone https://github.com/mida-hub/receipt-scanner.git
cd receipt-scanner
uv sync
```

### 3. 環境設定
`.env.example` をコピーして `.env` を作成します：

```bash
cp .env.example .env
```

`.env` の内容を確認・設定：
```env
GOOGLE_CLOUD_PROJECT=apps-466614
GOOGLE_CLOUD_LOCATION=us
GOOGLE_APPLICATION_CREDENTIALS=credentials/service_account.json

GEMINI_MODEL=gemini-3.5-flash
SPREADSHEET_ID=your_spreadsheet_id_here
WORKSHEET_NAME=シート1
```

### 4. Google Cloud & サービスアカウント
1. `terraform/` にて Google Cloud の必要 API 有効化およびサービスアカウントを発行：
   ```bash
   cd terraform
   terraform init
   terraform apply
   ```
2. 発行された `credentials/service_account.json` のメールアドレス（`receipt-scanner@<PROJECT_ID>.iam.gserviceaccount.com`）を、記帳先 Google スプレッドシートの「共有」から **編集者** として追加してください。

---

## 🚀 使い方（週末の運用ルーティン）

### Step 1: レシート画像を投入
撮影したレシート画像を `receipts/inbox/` フォルダへ配置します（AirDrop や Google ドライブ共有など）。

### Step 2: スキャナーを実行
```bash
uv run main.py
```

#### オプション: 事前プレビュー（ドライラン）
スプレッドシートへの書き込みやファイルのアーカイブ移動を行わず、コンソール上で解析結果だけを確認したい場合：
```bash
uv run main.py --dry-run
```

### Step 3: スプレッドシートで確認
スプレッドシートを開き、金額やカテゴリが意図通り記録されているかサッと確認して完了です。
処理済みの画像は `receipts/archive/YYYY-MM/` に自動移動します。
