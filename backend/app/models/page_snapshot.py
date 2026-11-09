from sqlalchemy import Column, String, Text, DateTime
from app.core.database import Base


class PageSnapshot(Base):
    """画面に出す計算結果の最後の1回ぶん。

    全在庫一覧は開くたびにAmazonから在庫・売上を取り直していて、
    数分待たされていた。サーバーの手元の覚え（メモリ）は更新のたびに
    消えるので、最後に取れた結果をDBに残し、開いたらまずそれを出す。
    新しい値は裏で取り、取れたら差し替える。
    """
    __tablename__ = "page_snapshots"

    key = Column(String, primary_key=True)      # 例: "amazon_stock"
    data = Column(Text)                          # JSON
    fetched_at = Column(DateTime(timezone=True))
