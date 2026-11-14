import io
import os
from pathlib import Path
from PIL import Image, ImageOps
import pillow_heif
from google import genai
from google.genai import types

from receipt_scanner.config import Config
from receipt_scanner.models import ReceiptData

# HEIC 形式の登録 (iPhone写真対応)
pillow_heif.register_heif_opener()

SYSTEM_INSTRUCTION = """
あなたは家計簿のレシート・領収書解析のアシスタントです。
家計簿の主な目的は「月の支出総額の把握」と「特定カテゴリが急増したときに何を買ったかを振り返ること」です。
画像を読み取り、指定されたスキーマに従って正確にJSON形式で抽出してください。

【抽出ルール】
1. 日付 (date):
   - YYYY-MM-DD 形式。西暦が省略されている場合は妥当な西暦を補完してください。
2. 店舗名 (store_name):
   - 店舗名や屋号、サービス名を抽出してください。
3. 金額 (total_amount):
   - 税込の最終支払総額（値引きやポイント利用がある場合はその適用後）を数値のみで抽出してください。
4. カテゴリ (category):
   - 以下のいずれか1つを厳密に選択してください:
     * 食費 (スーパー、コンビニ、飲食店、カフェ等)
     * 家具/家電/日用品 (ドラッグストア、ホームセンター、家具店、家電量販店等)
     * 医療費 (病院、クリニック、調剤薬局、医薬品等)
     * 自動車 (ガソリンスタンド、コインパーキング、高速代、整備等)
     * 被服費 (衣服、靴、服飾雑貨等)
     * 美容 (美容院、ネイル、コスメ、エステ等)
     * ジム (フィットネス、トレーニングジム等)
     * その他
5. メモ (memo):
   - 「何を購入したか」が後から一目で振り返れるように、目立つ購入品や高額品目、内訳を簡潔に記載してください。
   - 例: "シャンプー, 洗剤, ティッシュ", "ガソリン 35L", "焼肉ディナー", "スニーカー"
"""

class ReceiptExtractor:
    def __init__(self):
        # GEMINI_API_KEY が設定されている場合は Google AI Studio API を使用
        # 未設定の場合は Vertex AI サービスアカウント認証にフォールバック
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            self.client = genai.Client(api_key=api_key)
        else:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(Config.CREDENTIALS_PATH)
            self.client = genai.Client(
                vertexai=True,
                project=Config.PROJECT_ID,
                location=Config.LOCATION,
            )

    @staticmethod
    def _prepare_image_bytes(image_path: Path) -> bytes:
        """
        画像をメモリ上でリサイズ＆JPEG圧縮し、API送信用のバイト列を生成する。
        （元の画像ファイルは一切変更しない）
        """
        with Image.open(image_path) as img:
            # スマホ写真のEXIF回転情報を適用して正しい向きに補正
            img = ImageOps.exif_transpose(img)
            rgb_img = img.convert("RGB")
            # アスペクト比を維持したまま長辺を MAX_IMAGE_SIZE (デフォルト1024px) に縮小
            rgb_img.thumbnail(
                (Config.MAX_IMAGE_SIZE, Config.MAX_IMAGE_SIZE),
                Image.Resampling.LANCZOS,
            )
            buf = io.BytesIO()
            rgb_img.save(buf, format="JPEG", quality=Config.JPEG_QUALITY, optimize=True)
            return buf.getvalue()

    def extract_from_image(self, image_path: Path) -> ReceiptData:
        """レシート画像から構造化データを抽出する"""
        jpeg_bytes = self._prepare_image_bytes(image_path)

        response = self.client.models.generate_content(
            model=Config.GEMINI_MODEL,
            contents=[
                types.Part.from_bytes(data=jpeg_bytes, mime_type="image/jpeg"),
                "このレシート画像から支払日・店舗名・支払総額・カテゴリ・振り返り用購入品メモを抽出してください。",
            ],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=ReceiptData,
                temperature=0.1,
                thinking_config=types.ThinkingConfig(
                    thinking_level=types.ThinkingLevel.MINIMAL
                ),
                media_resolution=types.MediaResolution.MEDIA_RESOLUTION_MEDIUM,
            ),
        )

        return ReceiptData.model_validate_json(response.text)

    def extract_from_text(
        self, text: str, subject: str = "", sender: str = "", date: str = ""
    ) -> ReceiptData:
        """メール本文などのテキストから構造化データを抽出する"""
        prompt = (
            "以下の注文確認・領収書メールのテキストから、支払日・店舗名（サービス名）・"
            "支払総額・カテゴリ・振り返り用購入品メモを抽出してください。\n"
            "※本文中に明確な注文日・支払日の記載がない場合や西暦が省略されている場合は、"
            "以下の「メール受信日時」を基準に日付を補完してください。\n\n"
            f"件名: {subject}\n"
            f"送信元: {sender}\n"
            f"メール受信日時: {date}\n"
            "---\n"
            f"{text}"
        )

        response = self.client.models.generate_content(
            model=Config.GEMINI_MODEL,
            contents=[prompt],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=ReceiptData,
                temperature=0.1,
                thinking_config=types.ThinkingConfig(
                    thinking_level=types.ThinkingLevel.MINIMAL
                ),
            ),
        )

        return ReceiptData.model_validate_json(response.text)
