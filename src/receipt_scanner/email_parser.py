from dataclasses import dataclass
from email.utils import parsedate_to_datetime
import re
from typing import TYPE_CHECKING, Callable, List

if TYPE_CHECKING:
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


def _match_shop_rule(sender: str, subject: str) -> "EmailShopRule | None":
    """送信元や件名から一致するショップルールを検索する"""
    lower_sender = sender.lower()
    lower_subject = subject.lower()
    for rule in SHOP_RULES:
        if any(kw in lower_sender for kw in rule.sender_keywords) or any(
            kw in lower_subject for kw in rule.subject_keywords
        ):
            return rule
    return None


def _parse_store_name(sender: str, rule: "EmailShopRule | None") -> str:
    """ルールまたは送信元ヘッダーから店舗・サービス名を判定する"""
    if rule is not None:
        return rule.store_name

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


@dataclass(frozen=True)
class EmailShopRule:
    """メール取り込み対象ショップの定義"""

    store_name: str
    query: str = ""
    sender_keywords: tuple[str, ...] = ()
    subject_keywords: tuple[str, ...] = ()
    default_category: str = ""
    item_parser: Callable[[str], List[tuple[str, int]]] | None = None


SHOP_RULES: List[EmailShopRule] = [
    EmailShopRule(
        store_name="Amazon.co.jp",
        query="from:auto-confirm@amazon.co.jp",
        sender_keywords=("amazon.co.jp",),
        subject_keywords=("amazon",),
        item_parser=_parse_amazon_items,
    ),
    EmailShopRule(
        store_name="楽天市場",
        query="from:order@rakuten.co.jp",
        sender_keywords=("rakuten.co.jp",),
        subject_keywords=("楽天",),
        item_parser=_parse_rakuten_items,
    ),
    EmailShopRule(
        store_name="ヨシケイ",
        query="from:cib-jyuchu@yoshikei.gr.jp",
        sender_keywords=("yoshikei.gr.jp",),
        subject_keywords=("ヨシケイ",),
        default_category="食費",
    ),
    EmailShopRule(
        store_name="Hulu",
        query="(from:info@hulu.jp subject:ご請求のご連絡)",
        sender_keywords=("hulu.jp",),
        subject_keywords=("hulu",),
        default_category="その他",
    ),
    EmailShopRule(
        store_name="ヨドバシ.com",
        sender_keywords=("yodobashi.com",),
        subject_keywords=("ヨドバシ",),
    ),
]

DEFAULT_GMAIL_QUERY = " OR ".join(rule.query for rule in SHOP_RULES if rule.query)


def parse_email_to_receipts(msg: "GmailMessage") -> List[ReceiptData]:
    """Gmail メッセージを機械的に解析して ReceiptData のリストに変換する（LLM不使用）"""
    date_str = _parse_date(msg.date)
    if not date_str:
        raise ValueError(f"メール日時を解析できませんでした: {msg.date}")

    rule = _match_shop_rule(msg.sender, msg.subject)
    store_name = _parse_store_name(msg.sender, rule)
    total_amount = _parse_amount(msg.body)
    default_category = rule.default_category if rule else ""

    items: List[tuple[str, int]] = (
        rule.item_parser(msg.body) if rule and rule.item_parser else []
    )

    if items:
        receipts = [
            ReceiptData.model_construct(
                date=date_str,
                store_name=store_name,
                total_amount=price,
                category=default_category,
                memo=name,
            )
            for name, price in items
        ]
        items_sum = sum(price for _, price in items)
        diff = total_amount - items_sum
        if diff != 0:
            receipts.append(
                ReceiptData.model_construct(
                    date=date_str,
                    store_name=store_name,
                    total_amount=diff,
                    category=default_category,
                    memo="ポイント・割引・送料等調整",
                )
            )
        return receipts

    memo = _parse_memo(msg.body, msg.subject)
    return [
        ReceiptData.model_construct(
            date=date_str,
            store_name=store_name,
            total_amount=total_amount,
            category=default_category,
            memo=memo,
        )
    ]
