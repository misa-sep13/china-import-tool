"""タオタロウの仕入を楽天とAmazonに分ける。

月次サマリーの売上原価は「期首在庫＋仕入−期末在庫」。在庫は販路ごとに
数えているのに、仕入を全部まとめて足すと、Amazon向けに買って
まだ売れていない商品が楽天の売上原価に入ってしまう。

  ・商品代       … 注文（oid）ごとに、配送依頼の画面と同じ判定で分ける
  ・便の費用     … その便に入った注文の金額の割合で配る
  ・関税         … その月のタオタロウ商品代の割合で配る
見分けがつかない注文は楽天にする（2026-11-20 ユーザー決定）。
"""
from collections import defaultdict
from typing import Dict


def _amount(o: dict) -> float:
    for k in ("bargain_total",):
        try:
            v = float(o.get(k) or 0)
            if v:
                return v
        except (TypeError, ValueError):
            pass
    try:
        return float(o.get("unit_price") or 0) * float(o.get("quantity") or 0)
    except (TypeError, ValueError):
        return 0.0


def sync(db, max_pages: int = 60) -> dict:
    """タオタロウの注文を読み、販路を決めて保存する。何度やっても増えない。"""
    from app.models.taotaro_order_channel import TaotaroOrderChannel
    from app.services import taotaro
    from app.services.restock_split import make_classifier

    *_rest, classify = make_classifier(db)
    seen = added = 0
    counts: Dict[str, int] = defaultdict(int)
    for page in range(1, max_pages + 1):
        d = taotaro.list_orders(page=page, limit=100)
        items = d.get("items") or []
        for o in items:
            oid = str(o.get("oid") or "").strip()
            if not oid:
                continue
            seen += 1
            kind, sku, info = classify(o)
            ch = info.get("channel") or ""
            if ch == "amazon":
                channel, how = "amazon", "master_or_mark"
            elif ch == "rakuten":
                channel, how = "rakuten", "master"
            else:
                # both（両方で使うSKUで印なし）・マスタに無い・管理番号なし → 楽天
                channel, how = "rakuten", f"default_{ch or kind}"
            counts[channel] += 1
            row = db.query(TaotaroOrderChannel).filter(TaotaroOrderChannel.oid == oid).first()
            if not row:
                row = TaotaroOrderChannel(oid=oid)
                db.add(row)
                added += 1
            row.sid = str(o.get("sid") or "") or None
            row.sku = sku or str(o.get("out_id") or "")
            row.channel = channel
            row.how = how
            row.amount_cny = _amount(o)
            row.ordered_at = (o.get("created_at") or "")[:10]
        db.commit()
        if not d.get("has_more_pages") or not items:
            break
    return {"ok": True, "seen": seen, "added": added, "by_channel": dict(counts)}


def maps(db) -> tuple:
    """(oid → 販路, sid → Amazon向けの割合)。"""
    from app.models.taotaro_order_channel import TaotaroOrderChannel
    ch: Dict[str, str] = {}
    amt: Dict[str, list] = defaultdict(lambda: [0.0, 0.0])     # sid → [amazon, 全体]
    for r in db.query(TaotaroOrderChannel).all():
        ch[r.oid] = r.channel or "rakuten"
        if r.sid:
            a = amt[r.sid]
            v = r.amount_cny or 0.0
            a[1] += v
            if r.channel == "amazon":
                a[0] += v
    share = {sid: (a[0] / a[1]) for sid, a in amt.items() if a[1] > 0}
    return ch, share
