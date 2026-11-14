# Receipt Scanner (レシート一括解析＆自動記帳システム)

スマホで撮影したレシート画像をフォルダに放り込み、コマンドを実行するだけで **Gemini 3.5 Flash (Vertex AI)** が高精度に構造化（店舗名・金額・日付・カテゴリ・振り返り用購入品メモ）し、**Google スプレッドシート** へ一括自動記帳するシステムです。
また、`--gmail` オプションを指定することで、**Gmail に届く Amazon・楽天市場の注文確認メール** もあわせて自動解析・記帳できます。

---

## 🌟 特徴

* **APIキー管理不要（サービスアカウント認証）**:
  * Google Cloud サービスアカウントの秘密鍵 1 つで、Vertex AI の Gemini モデル呼び出しと Google Sheets API への記帳の両方をセキュアに完結。
* **家計簿の振り返りに最適化されたカテゴリ設計**:
  * 食費、家具/家電/日用品、医療費、自動車、被服費、美容、ジム など実態に合わせた分類。
  * 「今月このカテゴリが増えたのはなぜか？」を振り返りやすいよう、レシート内の主要品目を自動でメモ列に記録。
* **iPhone (HEIC) 写真対応**:
  * iPhoneの標準カメラで撮影された `.HEIC` 形式、一般的な `.jpg`, `.jpeg`, `.png`, `.webp` をそのまま投入可能。
* **安全な2段階ファイルライフサイクル管理 & 自動リトライ**:
  * **Step 1（Gemini解析）**: 解析成功時に結果を `receipts/pending/` にJSON保存し、元画像は即座に `receipts/archive/YYYY-MM/` へ自動退避（失敗画像は `receipts/failed/` へ移動）。
  * **Step 2（スプレッドシート記帳）**: `receipts/pending/` 内のJSONデータを一括記帳（一時的な `503` エラー等に対する自動リトライ機能付き）。記帳完了後にJSONファイルを削除。万一記帳が失敗しても、次回実行時に Gemini 再解析なしで記帳のみ再実行可能。
  * 書き込み前に確認できる `--dry-run` モード搭載。
* **Gmail 注文メール自動取り込み（OAuth 2.0）**:
  * `--gmail` 指定時、Amazon (`auto-confirm@amazon.co.jp`) および楽天市場 (`order@rakuten.co.jp`) の未処理注文メールを機械的に解析（LLM 不使用で高速・API コストゼロ、カテゴリは空欄）。
  * Amazon は商品明細ごとに 1 行出力し、ポイント・割引等の差額がある場合は調整行を自動追加。
  * 処理済みメールには Gmail 側で `receipt-scanned` ラベルを付与し、2重取り込みを防止。

---

## 📁 ディレクトリ構成

```text
receipt-scanner/
├── .env                  # 環境設定（GCPプロジェクトID, スプレッドシートID等 / git除外）
├── .env.example          # 環境設定サンプル
├── credentials/          # 認証情報（git除外）
│   ├── service_account.json
│   ├── gmail_client_secret.json  # Gmail OAuth 2.0 クライアントシークレット
│   └── gmail_token.json          # Gmail OAuth 2.0 トークン（初回認証時に自動生成）
├── main.py               # 実行エントリポイント
├── receipts/             # レシート画像・中間データ保管場所（git除外）
│   ├── inbox/            # 取り込み対象の未処理画像置き場
│   ├── pending/          # Gemini解析済み・スプレッドシート未記帳のJSON置き場
│   ├── archive/          # 処理完了画像（年-月ごとにサブフォルダ分け）
│   └── failed/           # 処理失敗画像
├── src/receipt_scanner/  # コアモジュール
│   ├── config.py         # 環境設定・ディレクトリパス
│   ├── email_parser.py   # Gmail 注文メールの機械的パーサー (Amazon / 楽天市場)
│   ├── extractor.py      # Gemini 3.5 Flash による画像構造化
│   ├── gmail.py          # Gmail API クライアント (OAuth 2.0)
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

### 5. Gmail 連携（OAuth 2.0）※ `--gmail` 利用時のみ
1. Google Cloud Console で **Gmail API** を有効化します。
2. **「OAuth 同意画面」** のテストユーザーに、自分の Gmail アドレスを追加します。
3. **「認証情報」＞「+ 認証情報を作成」＞「OAuth クライアント ID」** から、種類を **「デスクトップ アプリ」** として作成し、JSON をダウンロードして `credentials/gmail_client_secret.json` に配置します。
4. 初回 `--gmail` 実行時にブラウザが開くのでログイン・許可すると、`credentials/gmail_token.json` が自動保存されます。

---

## 🚀 使い方（週末の運用ルーティン）

### Step 1: レシート画像を投入
撮影したレシート画像を `receipts/inbox/` フォルダへ配置します（AirDrop や Google ドライブ共有など）。

### Step 2: スキャナーを実行
```bash
uv run main.py
```

#### コマンド引数（オプション）

| 引数 | 説明 | デフォルト |
| :--- | :--- | :--- |
| `--gmail` | Gmail から注文確認メール（Amazon / 楽天市場）を取得して解析する（未指定時はレシート画像のみ処理） | `False` |
| `--days <日数>` | Gmail 検索の対象とする過去日数（`0` で日数制限なし） | `10` |
| `--gmail-query <クエリ>` | Gmail の検索クエリを上書きする | `from:auto-confirm@amazon.co.jp OR from:order@rakuten.co.jp` |
| `--workers <数>` | レシート画像解析時の Gemini API 並列実行数 | `5` |
| `--dry-run` | ファイル保存・移動・Gmail ラベル付与・スプレッドシートへの書き込みを行わず、解析結果のみ表示する | `False` |

```bash
# 事前プレビュー（ドライラン）
uv run main.py --dry-run

# Gmail の注文メールもあわせて取り込む（過去10日間）
uv run main.py --gmail

# Gmail の対象期間を過去30日間に広げてドライラン
uv run main.py --gmail --days 30 --dry-run

# 特定の送信元だけを対象にする
uv run main.py --gmail --gmail-query "from:order@rakuten.co.jp" --dry-run
```

### Step 3: スプレッドシートで確認
スプレッドシートを開き、金額やカテゴリが意図通り記録されているかサッと確認して完了です。
処理済みの画像は `receipts/archive/YYYY-MM/` に自動移動します。
