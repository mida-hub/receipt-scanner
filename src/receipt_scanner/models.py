from typing import Literal
from pydantic import BaseModel, Field

# ユーザー指定のカテゴリ定義
CategoryType = Literal[
    "食費",               # スーパー・レストランなどの外食
    "家具/家電/日用品",    # ドラッグストア、家具、家電
    "医療費",             # 病院、薬局、医療関連
    "自動車",             # ガソリン、駐車代、車関連費用
    "被服費",             # 洋服、靴、衣料品
    "美容",               # 美容室、コスメ、エステなど
    "ジム",               # フィットネス、パーソナルジムなど
    "その他",             # 上記に明確に該当しないもの
]

class ReceiptData(BaseModel):
    """レシートから抽出された構造化データ"""
    date: str = Field(
        description="購入日 (YYYY-MM-DD形式)。西暦が不明な場合は現在年を補完してください"
    )
    store_name: str = Field(
        description="店舗名または会社名 (正式名称、または一般的な通称)"
    )
    total_amount: int = Field(
        description="支払合計金額（税込）。値引き・ポイント利用後の実際の最終支払金額を数値のみで抽出"
    )
    category: CategoryType = Field(
        description="""支出カテゴリ。以下のルールで分類してください:
- 食費: スーパー・コンビニ・外食・カフェなど
- 家具/家電/日用品: ドラッグストア、ホームセンター、家具、家電など
- 医療費: 病院、クリニック、調剤薬局、医療関連
- 自動車: ガソリンスタンド、コインパーキング、高速代、車検など
- 被服費: 洋服、靴、衣料品店
- 美容: 美容院、サロン、コスメショップなど
- ジム: フィットネス、パーソナルジム、スポーツ施設
- その他: 上記に当てはまらない支出
"""
    )
    memo: str = Field(
        default="",
        description="振り返り用の主要購入品目（例: 洗濯機, ガソリン, 外食ランチ, 日用品まとめ買い 等）。後の振り返りで「何を買ったか」が分かるように具体的に記載してください"
    )

class PendingReceipt(BaseModel):
    """Gemini解析完了後、スプレッドシート記帳待ちの中間保存データ"""
    filename: str = Field(description="元のレシート画像ファイル名")
    data: ReceiptData = Field(description="抽出されたレシートデータ")
