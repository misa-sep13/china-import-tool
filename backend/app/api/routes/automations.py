"""いま自動で動いているものの一覧。

機能が増えるほど「何が勝手に動いていて、何を自分でやるのか」が
分からなくなる。画面に並べて、切れるものは切れるようにしておく。

並びはサーバー側で持つ。画面に書くと、巡回に足したのに一覧へ
書き忘れる（逆も起きる）。
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.settings import OrderSettings

router = APIRouter(prefix="/automations", tags=["automations"])


# area: amazon / rakuten / both
# every: 動く間隔。画面にそのまま出す
_JOBS = [
    {
        "id": "rakuten_stock_sync", "area": "rakuten", "every": "1分",
        "name": "受注を見て在庫を減らす",
        "what": "楽天の受注を拾って単品在庫を減らし、セット在庫を組み直して"
                "RMSへ戻します。キャンセルは在庫を戻します。",
    },
    {
        "id": "rms_stock_pull", "area": "rakuten", "every": "1分",
        "name": "RMSから在庫を読み戻す",
        "what": "楽天側の在庫数をツールへ取り込みます。"
                "セットの構成品になっている単品は上書きしません。",
    },
    {
        "id": "delayed_cancel", "area": "rakuten", "every": "30分",
        "name": "遅れて入るキャンセルを拾う",
        "what": "受注が後から取り消されていないかRMSで確かめ、在庫を戻します。",
    },
    {
        "id": "month_end_inventory", "area": "both", "every": "1分（月末だけ）",
        "name": "月末の在庫を確定する",
        "what": "在庫はいまの値しか残らないので、月末に期末在庫として写し取ります。"
                "押し忘れるとその月の棚卸高が出せません。",
    },
    {
        "id": "send_order_watch", "area": "rakuten", "every": "10分",
        "name": "配送依頼の状態をチャットワークへ",
        "what": "「お支払い待ち」「出荷待ち」「出荷済み」に変わったら流します。"
                "支払いのお願いはメールで来るので、気づくのが遅れていました。",
    },
    {
        "id": "delivery_watch", "area": "rakuten", "every": "10分",
        "name": "配達が終わった便を入荷する",
        "what": "タオタロウの追跡が「配達完了」になったら、配送依頼を取り込んで"
                "在庫に入れ、LINEで知らせます。FBA宛の便は触りません。"
                "照合できない行があれば止めて理由を知らせます。",
        "switch": "auto_receive_on_delivery",
    },
    {
        "id": "permit_cost", "area": "rakuten", "every": "2時間",
        "name": "輸入許可書を拾って原価を出す",
        "what": "通関業者のメールから許可書を取り込み、どの便のものかを"
                "貨物重量と箱数で当て、インボイスをAPIで落として原価を計算・保存します。"
                "航空便と、SKUに当たらない行があるものは止めます。",
        "switch": "auto_cost_from_permit",
    },
    {
        "id": "fill_amazon_ids", "area": "amazon", "every": "6時間",
        "name": "ASIN・FNSKUを埋める",
        "what": "出品済みなのにASIN・FNSKUが空のSKUを、Amazonから読んで入れます。"
                "自己発送はFBA在庫の取り込みに出てこないので、ここが唯一の入り口です。",
    },
    {
        "id": "amazon_daily_sales", "area": "amazon", "every": "1日1回",
        "name": "日別の販売数をためる",
        "what": "季節商品の判定に去年の同じ時期と比べるため、今日の実績を残します。",
    },
    {
        "id": "product_images", "area": "amazon", "every": "商品マスタを開いたとき",
        "name": "商品画像を取り込む",
        "what": "画像が空のSKUのぶんだけ、AmazonのカタログからURLを拾って入れます。",
    },
    {
        "id": "secretary_line", "area": "both", "every": "毎朝1通",
        "name": "秘書の知らせ（LINE）",
        "what": "その日のやることと、期限を過ぎているものを1通にまとめて送ります。",
    },
    {
        "id": "taotaro_video", "area": "both", "every": "20分",
        "name": "タオタロウの動画をチャットワークへ",
        "what": "検品の動画がメールで届いたら、そのまま転送します。",
    },
    {
        "id": "rakuten_sales_sync", "area": "rakuten", "every": "毎日 3:00",
        "name": "楽天の売上を集計する",
        "what": "GitHub Actions が60日ぶんの受注を集計し、結果だけツールへ入れます"
                "（Renderのメモリに乗らないため外に出してあります）。",
    },
]


class SwitchIn(BaseModel):
    key: str
    enabled: bool


def _waiting(db: Session) -> dict:
    """止まっていて人の手が要る件数。"""
    out = {}
    try:
        from app.services import delivery_watch
        out["delivery_watch"] = len(delivery_watch.waiting_list(db))
    except Exception:
        pass
    try:
        from app.services import rakuten_cost_watch
        out["permit_cost"] = len(rakuten_cost_watch.waiting_list(db))
    except Exception:
        pass
    return out


@router.get("")
def list_automations(db: Session = Depends(get_db)):
    st = db.query(OrderSettings).first()
    waiting = _waiting(db)
    rows = []
    for j in _JOBS:
        row = dict(j)
        key = j.get("switch")
        row["enabled"] = (bool(getattr(st, key, True)) if (key and st)
                          else (True if key else None))
        row["waiting"] = waiting.get(j["id"], 0)
        rows.append(row)
    return rows


@router.put("/switch")
def set_switch(data: SwitchIn, db: Session = Depends(get_db)):
    """切れるものだけ切る。知らない名前は受け付けない。"""
    allowed = {j["switch"] for j in _JOBS if j.get("switch")}
    if data.key not in allowed:
        return {"ok": False, "message": "この項目は切り替えられません"}
    st = db.query(OrderSettings).first()
    if st is None:
        st = OrderSettings()
        db.add(st)
    setattr(st, data.key, bool(data.enabled))
    db.commit()
    return {"ok": True, "key": data.key, "enabled": bool(data.enabled)}
