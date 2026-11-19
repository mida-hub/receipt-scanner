import unittest
from typing import get_args

from receipt_scanner.email_parser import parse_email_to_receipts
from receipt_scanner.gmail import GmailMessage
from receipt_scanner.models import CategoryType, GeminiReceiptData, PendingReceipt


class TestEmailParserAndModels(unittest.TestCase):
    def test_amazon_itemized_with_point_adjustment_and_pending_roundtrip(self):
        msg = GmailMessage(
            message_id="msg_amazon_1",
            subject="注文済み: サントリー 天然水",
            sender="Amazon.co.jp <auto-confirm@amazon.co.jp>",
            date="Sat, 07 Nov 2026 10:00:00 +0900",
            body=(
                "* サントリー 天然水 ラベルレス 2L ×9本\n"
                "  数量: 1\n"
                "  1476 JPY\n\n"
                "合計\n"
                "1450 JPY\n"
            ),
        )
        receipts = parse_email_to_receipts(msg)
        self.assertEqual(len(receipts), 2)
        self.assertEqual(receipts[0].store_name, "Amazon.co.jp")
        self.assertEqual(receipts[0].total_amount, 1476)
        self.assertEqual(receipts[0].category, "")
        self.assertEqual(receipts[1].total_amount, -26)
        self.assertEqual(receipts[1].memo, "ポイント・割引・送料等調整")

        # PendingReceipt の JSON 保存・読み込みでバリデーションエラーにならないこと
        for r in receipts:
            pending = PendingReceipt(filename="gmail_test.json", data=r)
            restored = PendingReceipt.model_validate_json(pending.model_dump_json())
            self.assertEqual(restored.data.category, "")

    def test_rakuten_payment_amount(self):
        msg = GmailMessage(
            message_id="msg_rakuten_1",
            subject="【楽天市場】注文内容ご確認（自動配信メール）",
            sender="楽天市場 <order@rakuten.co.jp>",
            date="Fri, 13 Nov 2026 12:00:00 +0900",
            body=(
                "小計     572円\n"
                "クーポン利用     -100円\n"
                "支払い金額   472円\n"
            ),
        )
        receipts = parse_email_to_receipts(msg)
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0].store_name, "楽天市場")
        self.assertEqual(receipts[0].total_amount, 472)
        self.assertEqual(receipts[0].category, "")

    def test_yoshikei_category_is_food(self):
        msg = GmailMessage(
            message_id="msg_yoshikei_1",
            subject="[ヨシケイ]11月23日週のご注文を承りました。",
            sender="cib-jyuchu@yoshikei.gr.jp",
            date="Sat, 14 Nov 2026 09:00:00 +0900",
            body="ご請求額：4,900円\n",
        )
        receipts = parse_email_to_receipts(msg)
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0].store_name, "ヨシケイ")
        self.assertEqual(receipts[0].total_amount, 4900)
        self.assertEqual(receipts[0].category, "食費")

    def test_hulu_category_is_other(self):
        msg = GmailMessage(
            message_id="msg_hulu_1",
            subject="[Hulu] Hulu | Disney+ セットプラン ご請求のご連絡",
            sender="Hulu <info@hulu.jp>",
            date="Wed, 18 Nov 2026 08:00:00 +0900",
            body="ご請求金額: 2,150円\n",
        )
        receipts = parse_email_to_receipts(msg)
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0].store_name, "Hulu")
        self.assertEqual(receipts[0].total_amount, 2150)
        self.assertEqual(receipts[0].category, "その他")

    def test_gemini_schema_has_no_empty_category(self):
        categories = get_args(CategoryType)
        self.assertNotIn("", categories)
        schema = GeminiReceiptData.model_json_schema()
        self.assertIn("category", schema["properties"])


if __name__ == "__main__":
    unittest.main()
