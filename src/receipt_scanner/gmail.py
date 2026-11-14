import base64
from dataclasses import dataclass
from pathlib import Path
from typing import List

from bs4 import BeautifulSoup
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from receipt_scanner.config import Config

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


@dataclass
class GmailMessage:
    """取得したGmailメッセージの情報"""

    message_id: str
    subject: str
    sender: str
    date: str
    body: str


class GmailClient:
    """OAuth 2.0 を用いて Gmail API にアクセスするクライアント"""

    def __init__(
        self,
        credentials_path: Path | None = None,
        token_path: Path | None = None,
    ):
        self.credentials_path = credentials_path or Config.GMAIL_CREDENTIALS_PATH
        self.token_path = token_path or Config.GMAIL_TOKEN_PATH
        self.creds = self._authenticate()
        self.service = build("gmail", "v1", credentials=self.creds)

    def _authenticate(self) -> Credentials:
        """OAuth 2.0 認証を行い、トークンを保存・リフレッシュする"""
        creds: Credentials | None = None

        if self.token_path.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not self.credentials_path.exists():
                    raise FileNotFoundError(
                        f"Gmail OAuth クライアントシークレットが見つかりません: {self.credentials_path}\n"
                        "Google Cloud Console でデスクトップアプリ用 OAuth クライアント ID を作成し、"
                        "JSON をダウンロードして上記パスに配置してください。"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.credentials_path), SCOPES
                )
                creds = flow.run_local_server(port=0)

            self.token_path.parent.mkdir(parents=True, exist_ok=True)
            self.token_path.write_text(creds.to_json(), encoding="utf-8")

        return creds

    def get_or_create_label_id(self, label_name: str) -> str:
        """指定したラベル名のIDを取得し、存在しなければ作成する"""
        results = self.service.users().labels().list(userId="me").execute()
        for label in results.get("labels", []):
            if label.get("name") == label_name:
                return label["id"]

        created = (
            self.service.users()
            .labels()
            .create(
                userId="me",
                body={
                    "name": label_name,
                    "labelListVisibility": "labelShow",
                    "messageListVisibility": "show",
                },
            )
            .execute()
        )
        return created["id"]

    def fetch_unprocessed_messages(
        self,
        query: str | None = None,
        processed_label: str | None = None,
        max_results: int | None = None,
        days: int | None = None,
    ) -> List[GmailMessage]:
        """未処理のメールを検索して本文付きで取得する"""
        base_query = query or Config.GMAIL_QUERY
        label_name = processed_label or Config.GMAIL_PROCESSED_LABEL
        limit = max_results or Config.GMAIL_MAX_RESULTS
        lookback_days = Config.GMAIL_DAYS if days is None else days

        date_filter = f" newer_than:{lookback_days}d" if lookback_days > 0 else ""
        full_query = f"({base_query}){date_filter} -label:{label_name}"
        response = (
            self.service.users()
            .messages()
            .list(userId="me", q=full_query, maxResults=limit)
            .execute()
        )
        message_refs = response.get("messages", [])
        messages: List[GmailMessage] = []

        for ref in message_refs:
            msg_id = ref["id"]
            detail = (
                self.service.users()
                .messages()
                .get(userId="me", id=msg_id, format="full")
                .execute()
            )
            payload = detail.get("payload", {})
            headers = {
                h["name"].lower(): h["value"] for h in payload.get("headers", [])
            }
            body = self._extract_body(payload)
            messages.append(
                GmailMessage(
                    message_id=msg_id,
                    subject=headers.get("subject", "(件名なし)"),
                    sender=headers.get("from", ""),
                    date=headers.get("date", ""),
                    body=body,
                )
            )

        return messages

    def mark_as_processed(self, message_id: str, label_id: str) -> None:
        """メールに処理済みラベルを付与する"""
        self.service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"addLabelIds": [label_id]},
        ).execute()

    @classmethod
    def _extract_body(cls, payload: dict) -> str:
        """MIMEペイロードからテキスト本文を抽出する (text/plain 優先、なければ text/html)"""
        plain_parts: List[str] = []
        html_parts: List[str] = []
        cls._collect_parts(payload, plain_parts, html_parts)

        if plain_parts:
            return "\n".join(plain_parts).strip()
        if html_parts:
            soup = BeautifulSoup("\n".join(html_parts), "html.parser")
            for tag in soup(["script", "style"]):
                tag.decompose()
            lines = [line.strip() for line in soup.get_text("\n").splitlines()]
            return "\n".join(line for line in lines if line)
        return ""

    @classmethod
    def _collect_parts(
        cls, payload: dict, plain_parts: List[str], html_parts: List[str]
    ) -> None:
        mime_type = payload.get("mimeType", "")
        body_data = payload.get("body", {}).get("data")

        if body_data:
            decoded = base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")
            if mime_type == "text/plain":
                plain_parts.append(decoded)
            elif mime_type == "text/html":
                html_parts.append(decoded)

        for part in payload.get("parts", []):
            cls._collect_parts(part, plain_parts, html_parts)
