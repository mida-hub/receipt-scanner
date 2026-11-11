from datetime import datetime
from typing import List, Tuple
import gspread
from gspread.exceptions import APIError
from google.oauth2.service_account import Credentials
import requests.exceptions
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from receipt_scanner.config import Config
from receipt_scanner.models import ReceiptData

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# 支払方法を削除し、振り返りに特化した列構成
HEADER_ROW = [
    "記帳日時",
    "購入日",
    "店舗名",
    "金額",
    "カテゴリ",
    "購入品・内訳メモ",
    "ファイル名",
]

def _is_retryable_sheets_error(exc: BaseException) -> bool:
    """Google Sheets API の一時エラー (429, 500, 502, 503, 504) や通信エラーかを判定"""
    if isinstance(exc, APIError):
        status_code = getattr(exc.response, "status_code", None) or getattr(exc, "code", None)
        return status_code in (429, 500, 502, 503, 504)
    if isinstance(exc, requests.exceptions.RequestException):
        return True
    return False

def _log_retry(retry_state):
    attempt = retry_state.attempt_number
    exc = retry_state.outcome.exception()
    wait_sec = retry_state.next_action.sleep
    print(f"⚠️  Google Sheets API 一時エラー (試行 {attempt} 回目: {exc})。{wait_sec:.1f}秒後にリトライします...")

sheets_retry = retry(
    retry=retry_if_exception(_is_retryable_sheets_error),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    stop=stop_after_attempt(5),
    before_sleep=_log_retry,
    reraise=True,
)

class SheetsClient:
    @sheets_retry
    def __init__(self):
        credentials = Credentials.from_service_account_file(
            str(Config.CREDENTIALS_PATH),
            scopes=SCOPES,
        )
        self.client = gspread.authorize(credentials)
        self.sheet = self.client.open_by_key(Config.SPREADSHEET_ID)
        self.worksheet = self._get_or_create_worksheet(Config.WORKSHEET_NAME)

    def _get_or_create_worksheet(self, title: str):
        try:
            ws = self.sheet.worksheet(title)
        except gspread.WorksheetNotFound:
            ws = self.sheet.add_worksheet(title=title, rows=1000, cols=10)
        
        # 1行目が空ならヘッダーを挿入
        existing_rows = ws.get_all_values()
        if not existing_rows or not existing_rows[0]:
            ws.insert_row(HEADER_ROW, 1)
        elif existing_rows[0] != HEADER_ROW:
            # 既存のヘッダーが空、あるいは初期状態の場合上書き
            if all(cell == "" for cell in existing_rows[0]) or len(existing_rows) == 1:
                ws.update("A1:G1", [HEADER_ROW])
        return ws

    @sheets_retry
    def append_receipts(self, receipts: List[Tuple[ReceiptData, str]]) -> int:
        """
        レシートのリストを一括追記する。
        receipts: List of (ReceiptData, original_filename)
        """
        if not receipts:
            return 0

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rows_to_append = []

        for receipt, filename in receipts:
            row = [
                now_str,
                receipt.date,
                receipt.store_name,
                receipt.total_amount,
                receipt.category,
                receipt.memo,
                filename,
            ]
            rows_to_append.append(row)

        self.worksheet.append_rows(rows_to_append, value_input_option="USER_ENTERED")
        return len(rows_to_append)
