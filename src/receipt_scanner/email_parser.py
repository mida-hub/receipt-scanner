from email.utils import parsedate_to_datetime
import re
from typing import List

from receipt_scanner.gmail import GmailMessage
from receipt_scanner.models import ReceiptData

# 金額抽出用の正規表現パターン（優先度順）
AMOUNT_PATTERNS = [
    r"(?:ご請求額|請求額|お支払い合計|お支払い金額|支払い金額|注文合計|合計金額|支払合計|合計)\s*[：:\s]+\s*[￥¥]?\s*([\d,]+)\s*(?:JPY|円)?",
    r"[￥¥]\s*([\d,]+)\s*(?:税込|円)?",
    r"([\d,]+)\s*(?:JPY|円)",
]


def _parse_date(date_header: str) -> str:
    """メールの Date ヘッダーから YYYY-MM-DD を抽出する"""
    if not date_header:
        return ""
    try:
        dt = parsedate_to_datetime(date_header)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return ""


def _parse_store_name(sender: str, subject: str) -> str:
    """送信元や件名から店舗・サービス名を判定する"""
    lower_sender = sender.lower()
    lower_subject = subject.lower()
    if "amazon.co.jp" in lower_sender or "amazon" in lower_subject:
        return "Amazon.co.jp"
    if "rakuten.co.jp" in lower_sender or "楽天" in subject:
        return "楽天市場"
    if "yodobashi.com" in lower_sender or "ヨドバシ" in subject:
        return "ヨドバシ.com"
    if "yoshikei.gr.jp" in lower_sender or "ヨシケイ" in subject:
        return "ヨシケイ"

    # "表示名 <addr@example.com>" から表示名を抽出
    match = re.match(r'^"?([^"<]+)"?\s*<', sender.strip())
    if match:
        return match.group(1).strip()
    return sender.strip() or "不明"


def _parse_amount(body: str) -> int:
    """メール本文から合計金額を抽出する"""
    for pattern in AMOUNT_PATTERNS:
        match = re.search(pattern, body)
        if match:
            amount_str = match.group(1).replace(",", "")
            if amount_str.isdigit():
                return int(amount_str)
    raise ValueError("メール本文から合計金額を抽出できませんでした")


def _parse_memo(body: str, subject: str) -> str:
    """メール本文や件名から購入品メモを抽出する"""
    # Amazon の注文確認メール等で商品名が書かれやすい行を抽出
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    items: list[str] = []
    for i, line in enumerate(lines):
        # "数量:" や "￥" の直前行に商品名が来ることが多い
        if re.match(r"^(?:数量|Qty)\s*[：:]", line) and i > 0:
            candidate = lines[i - 1]
            if len(candidate) > 2 and not candidate.startswith(("http", "￥", "¥")):
                items.append(candidate[:40])
        if len(items) >= 3:
            break

    if items:
        return ", ".join(items)
    return subject[:50]


def _parse_amazon_items(body: str) -> List[tuple[str, int]]:
    """Amazon 注文確認メールから (商品名, 金額) のリストを抽出する"""
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    items: List[tuple[str, int]] = []

    for i, line in enumerate(lines):
        # "数量: 1" や "Qty: 1" の直前行が商品名、近くの後続行に価格があるパターン
        if re.match(r"^(?:数量|Qty)\s*[：:]\s*\d+", line) and i > 0:
            name = lines[i - 1].lstrip("* ").strip()
            if len(name) <= 2 or name.startswith(("http", "￥", "¥")):
                continue

            # 直後数行から価格を探す
            price = None
            for j in range(i + 1, min(i + 5, len(lines))):
                m = re.match(r"^(?:[￥¥]\s*)?([\d,]+)(?:\s*(?:JPY|円))?$", lines[j])
                if m:
                    price = int(m.group(1).replace(",", ""))
                    break
            if price is not None:
                items.append((name[:50], price))

    return items


def _parse_rakuten_items(body: str) -> List[tuple[str, int]]:
    """楽天市場の注文確認メールから (商品名, 金額) のリストを抽出する"""
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    items: List[tuple[str, int]] = []

    for i, line in enumerate(lines):
        # 例: "572円 x 1個 = 572円" の直前行が商品名
        m = re.match(r"^[\d,]+円\s*[x×]\s*\d+個\s*=\s*([\d,]+)円$", line)
        if m and i > 0:
            name = lines[i - 1].strip()
            price = int(m.group(1).replace(",", ""))
            if len(name) > 1:
                items.append((name[:50], price))

    return items


def parse_email_to_receipts(msg: GmailMessage) -> List[ReceiptData]:
    """Gmail メッセージを機械的に解析して ReceiptData のリストに変換する（LLM不使用）"""
    date_str = _parse_date(msg.date)
    if not date_str:
        raise ValueError(f"メール日時を解析できませんでした: {msg.date}")

    store_name = _parse_store_name(msg.sender, msg.subject)
    total_amount = _parse_amount(msg.body)

    items: List[tuple[str, int]] = []
    if store_name == "Amazon.co.jp":
        items = _parse_amazon_items(msg.body)
    elif store_name == "楽天市場":
        items = _parse_rakuten_items(msg.body)

    if items:
        receipts = [
            ReceiptData(
                date=date_str,
                store_name=store_name,
                total_amount=price,
                category="",
                memo=name,
            )
            for name, price in items
        ]
        items_sum = sum(price for _, price in items)
        diff = total_amount - items_sum
        if diff != 0:
            receipts.append(
                ReceiptData(
                    date=date_str,
                    store_name=store_name,
                    total_amount=diff,
                    category="",
                    memo="ポイント・割引・送料等調整",
                )
            )
        return receipts

    memo = _parse_memo(msg.body, msg.subject)
    category = "食費" if store_name == "ヨシケイ" else ""
    return [
        ReceiptData(
            date=date_str,
            store_name=store_name,
            total_amount=total_amount,
            category=category,
            memo=memo,
        )
    ]
