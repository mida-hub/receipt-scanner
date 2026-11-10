import os
from pathlib import Path
from dotenv import load_dotenv

# プロジェクトルートの .env をロード
BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")

class Config:
    # Google Cloud & Vertex AI 設定
    PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "apps-466614")
    LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us")
    CREDENTIALS_PATH = Path(
        os.getenv("GOOGLE_APPLICATION_CREDENTIALS", BASE_DIR / "credentials/service_account.json")
    )

    # Gemini モデル & 画像最適化設定
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
    MAX_IMAGE_SIZE = int(os.getenv("MAX_IMAGE_SIZE", "1024"))
    JPEG_QUALITY = int(os.getenv("JPEG_QUALITY", "80"))

    # スプレッドシート設定
    SPREADSHEET_ID = os.getenv(
        "SPREADSHEET_ID",
        "1J630lKiHfl8xkWQhFu7yI_B3f2tSLs0jbOZ8nciKR-4"
    )
    WORKSHEET_NAME = os.getenv("WORKSHEET_NAME", "シート1")

    # レシート保存ディレクトリ
    INBOX_DIR = BASE_DIR / os.getenv("INBOX_DIR", "receipts/inbox")
    ARCHIVE_DIR = BASE_DIR / os.getenv("ARCHIVE_DIR", "receipts/archive")
    FAILED_DIR = BASE_DIR / os.getenv("FAILED_DIR", "receipts/failed")

    @classmethod
    def ensure_dirs(cls):
        cls.INBOX_DIR.mkdir(parents=True, exist_ok=True)
        cls.ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        cls.FAILED_DIR.mkdir(parents=True, exist_ok=True)
