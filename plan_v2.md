# ローカルPC × Antigravity (agy) レシート一括入力システム設計書

## 1. 概要
週末に自分と家族から集めたレシートを一括でPCへ取り込み、ローカルPC環境で **Antigravity CLI (`agy`) / Python ＋ Gemini Vision API** を活用して高精度に構造化（日付・店名・金額・カテゴリ）。**Google Sheets API** 経由で Google スプレッドシートに一括自動記帳するシステム構成です。

---

## 2. システムの強みと前提条件

### 前提条件
* **作業スタイル**: 週末にPCを起動し、まとめて一括処理（バッチ処理）。
* **契約環境**: Antigravity 有料プラン（Google AI Pro 等の5時間ごとの高レート上限を活用）。
* **入力ソース**: 自分と奥様から回収した紙のレシート群。

### 本構成のメリット
1. **圧倒的な処理スピード**: スマホで1枚ずつLINE送信する手間がなく、フォルダに画像をまとめてドロップしてコマンド一発で完了。
2. **高い認識精度**: 最新のビジョンモデル（Gemini 1.5 Pro / 2.0等）を無制限に近い感覚で利用でき、誤読が大幅に減少。
3. **確認・修正の容易さ**: 週末にPCの前にいるため、スプレッドシートを開いた状態での修正・確認が最もスムーズ。
4. **メンテナンスフリー**: サーバーやWebhookの運用・保守が不要で、ローカル環境のみで完結。

---

## 3. システム構成とデータフロー

```
[ 紙のレシート（自分＋妻） ]
           │
           ▼ (スマホでまとめて撮影 / AirDrop / ドライブ共有)
[ ローカルPCの受信フォルダ ] (例: ~/receipts/inbox/)
           │
           ▼ (Antigravity CLI または 自作Pythonスクリプト実行)
[ 高精度 Vision AI (Gemini等) ] ── (店名・日付・金額・カテゴリを抽出)
           │
           ▼ (Google Sheets API / gspread)
[ Google スプレッドシート ] ── (一括追記)
           │
           ▼
[ 処理済みフォルダへ自動移動 ] (例: ~/receipts/archive/2026-11/)
```

---

## 4. 運用の全体フロー（週末のステップ）

### Step 1: レシートの集約・取り込み
* 1週間分のレシートをスマホのカメラで連続撮影（またはスキャナーで一元化）。
* Mac/PCの `~/receipts/inbox/` フォルダへ一括転送（AirDropやGoogleドライブ等の同期フォルダを活用）。

### Step 2: バッチ処理の実行
ターミナルを開き、以下のいずれかの方法で一括処理を実行。

* **パターンA: 自作スクリプトを `agy` 経由または直接叩く**
  ```bash
  python process_receipts.py
  ```
* **パターンB: `agy` CLI エージェントに自然言語で指示を出す**
  ```bash
  agy "inbox フォルダ内にあるレシート画像を全て読み込んで parse し、Google スプレッドシートに追記して inbox から archive へ移動させて"
  ```

### Step 3: 確認と微修正
* スプレッドシートが開く（または確認用ログが出力される）ので、金額の読み取りミスがないか一目チェック。
* 必要に応じてスプレッドシート上で数秒で手修正して完了。

---

## 5. スクリプト構成案（Python + gspread + Gemini API）

ローカル処理を支えるコードの基本設計例です。

```python
import os
import glob
import shutil
import gspread
import google.generativeai as genai
from PIL import Image

# 1. API・認証設定
genai.configure(api_key=os.environ["GEMINI_API_KEY"])
gc = gspread.service_account(filename="credentials.json")
sheet = gc.open("家計簿2026").sheet1

INBOX_DIR = "./receipts/inbox"
ARCHIVE_DIR = "./receipts/archive"

def process_single_receipt(image_path):
    img = Image.open(image_path)
    
    # Vision AI への指示（プロンプト）
    model = genai.GenerativeModel('gemini-1.5-pro')
    prompt = """
    このレシート画像から以下の情報を抽出し、カンマ区切りのCSV形式で出力してください。
    余計な解説は不要です。
    日付(YYYY-MM-DD), 店舗名, 金額(数値のみ), カテゴリ(食費/日用品/交通費/娯楽/その他)
    """
    
    response = model.generate_content([prompt, img])
    data = response.text.strip().split(',')
    return data  # [日付, 店舗名, 金額, カテゴリ]

def main():
    images = glob.glob(f"{INBOX_DIR}/*.jpg") + glob.glob(f"{INBOX_DIR}/*.png")
    rows_to_append = []

    for img_path in images:
        try:
            row = process_single_receipt(img_path)
            rows_to_append.append(row)
            # 処理済み画像を移動
            shutil.move(img_path, os.path.join(ARCHIVE_DIR, os.path.basename(img_path)))
        except Exception as e:
            print(f"Error processing {img_path}: {e}")

    if rows_to_append:
        # スプレッドシートへ一括書き込み
        sheet.append_rows(rows_to_append)
        print(f"Successfully processed {len(rows_to_append)} receipts!")

if __name__ == "__main__":
    main()
```

---

## 6. まとめ・今後のステップ

* **コスト対効果**: Antigravity 有料プランの枠を活用することで、高精度の画像解析をコストやレート制限を気にせず並列運用可能。
* **拡張性**: 将来的に「特定の店名は自動で『固定費』にする」「PDF形式の領収書も混ぜて一括処理する」などのルール追加もローカルスクリプト修正だけで自由自在に実現。

今後は、ローカル環境でのGoogle API認証（`credentials.json`）の準備や、`agy` でのスクリプト自動生成から始めるのがおすすめです。