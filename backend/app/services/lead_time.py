"""発注から入荷までに実際どれだけかかっているかを、実績から出す。

発注数は「入荷するまでに売れる数」を見込んで決めるので、リードタイムが
勘だと在庫が足りなくなるか、余る。これまでは設定に手で入れた日数を
使っていたが、実績と合っているか確かめる手立てが無かった。

4つの区間に分けて数える:
  買付   発注 → 中国倉庫に入るまで（仕入先の速さ。商品ごとに差が出る）
  滞留   中国倉庫 → 出荷まで（配送依頼をいつ出すか。こちらの都合）
  輸送   出荷 → 日本入荷まで（船便か航空便かで倍以上ちがう）
  合計   発注 → 日本入荷まで

日本に着いた日はタオタロウには無い。便の状態が「出荷済み」で止まり、
「受け取り済み」を使っていないため。こちらの配送依頼の入荷日を使う。

タオタロウのAPIは1分100回までなので、便の明細を毎回引き直さないよう
結果を持っておく。
"""

import re
import threading
import time
from datetime import datetime

_CACHE: dict = {}
_CACHE_LOCK = threading.Lock()
_TTL_SEC = 12 * 3600

# 「同梱でお願いします」のように、送り状番号の欄に文章が入っている便は
# 別の便にまとめられている。日数を数えると実態とずれるので外す
_MERGED = ("同梱", "同捆", "梱包", "入れて", "まとめ")


def _median(v: list):
    if not v:
        return None
    s = sorted(v)
    return s[len(s) // 2]


def _day(s) -> datetime | None:
    t = str(s or "")[:10]
    try:
        return datetime.fromisoformat(t)
    except ValueError:
        return None


def _mode_of(delivery_name: str) -> str:
    """配送方法の名前から、船便か航空便かを見分ける。

    タオタロウの delivery_name をそのまま見る。重さで推し量ると、
    重い航空便や軽い船便を取り違える。
    """
    n = str(delivery_name or "")
    if "船便" in n:
        return "sea"
    if any(k in n for k in ("EMS", "OCS", "航空", "DHL", "FedEx", "UPS")):
        return "air"
    return ""


def _is_merged(sn: str) -> bool:
    s = str(sn or "").strip()
    if not s:
        return True
    return any(k in s for k in _MERGED)


def _offer_id(url: str) -> str:
    m = re.search(r"/offer/(\d+)", str(url or ""))
    return m.group(1) if m else ""


def _stats(rows: list, key: str) -> dict:
    v = [r[key] for r in rows if r.get(key) is not None]
    if not v:
        return {"n": 0, "median": None, "min": None, "max": None}
    return {"n": len(v), "median": _median(v), "min": min(v), "max": max(v)}


def compute(db, pages: int = 3, slow_days: int = 8, slow_min_n: int = 3) -> dict:
    """実績を集計する。戻り値はそのまま画面に出せる形。"""
    from app.models.shipment_order import ShipmentOrder
    from app.models.rakuten_product import RakutenProduct
    from app.services import taotaro

    # こちらの記録。入荷した便だけが日数を数えられる
    ours = (db.query(ShipmentOrder)
            .filter(ShipmentOrder.received_at.isnot(None))
            .order_by(ShipmentOrder.received_at.desc()).all())
    by_key: dict = {}
    for o in ours:
        for k in (str(o.order_no or ""), str(o.tracking_no or "")):
            if k:
                by_key.setdefault(k, o)

    # タオタロウの便。配送方法と sid を引くために一覧を見る
    send: list = []
    for page in range(1, max(1, pages) + 1):
        d = taotaro.list_send_orders(page=page, limit=20)
        send.extend(d.get("items") or [])
        if not d.get("has_more_pages"):
            break

    prods = db.query(RakutenProduct).all()
    by_offer: dict = {}
    for p in prods:
        oid = _offer_id(p.buy_url)
        if oid:
            by_offer.setdefault(oid, p)
    by_sku = {p.sku: p for p in prods if p.sku}

    shipments: list = []
    buy_by_product: dict = {}

    for x in send:
        sid = x.get("sid")
        sn = str(x.get("sn") or "")
        mine = by_key.get(str(sid)) or by_key.get(sn)
        mode = _mode_of(x.get("delivery_name"))
        if not mine or _is_merged(sn):
            continue
        shipped = _day(mine.shipped_date)
        received = _day(mine.received_at)
        if not shipped or not received:
            continue

        try:
            d = taotaro.get_send_order(sid)
        except taotaro.TaotaroError:
            continue

        buys, totals, arrived = [], [], []
        for o in d.get("orders") or []:
            c, a = _day(o.get("created_at")), _day(o.get("arrived_at"))
            if not c:
                continue
            totals.append((received - c).days)
            if a:
                buys.append((a - c).days)
                arrived.append(a)
                # 商品ごとの買付日数。管理番号が入っていれば確実、
                # 入れずに出した古い注文はURLで引く（色ちがいはまとまる）
                p = by_sku.get(str(o.get("out_id") or "").strip()) \
                    or by_offer.get(_offer_id(o.get("url")))
                if p:
                    buy_by_product.setdefault(
                        p.sku, {"name": p.name or p.sku, "days": []}
                    )["days"].append((a - c).days)

        mid_arrived = _median(arrived)
        shipments.append({
            "sid": sid,
            "order_no": sn or str(sid),
            "delivery_name": x.get("delivery_name") or "",
            "mode": mode,
            "weight_kg": float(x.get("count_weight") or 0),
            "shipped_date": str(mine.shipped_date or "")[:10],
            "received_at": str(mine.received_at)[:10],
            "buy": _median(buys),
            "wait": (shipped - mid_arrived).days if mid_arrived else None,
            "transit": (received - shipped).days,
            "total": _median(totals),
        })

    def summary(rows: list) -> dict:
        return {
            "shipments": len(rows),
            "buy": _stats(rows, "buy"),
            "wait": _stats(rows, "wait"),
            "transit": _stats(rows, "transit"),
            "total": _stats(rows, "total"),
        }

    slow = []
    for sku, v in buy_by_product.items():
        m = _median(v["days"])
        if m is not None and len(v["days"]) >= slow_min_n and m >= slow_days:
            slow.append({"sku": sku, "name": v["name"], "n": len(v["days"]),
                         "median": m, "max": max(v["days"])})
    slow.sort(key=lambda r: (-r["median"], -r["n"]))

    return {
        "shipments": shipments,
        "all": summary(shipments),
        "sea": summary([r for r in shipments if r["mode"] == "sea"]),
        "air": summary([r for r in shipments if r["mode"] == "air"]),
        "slow_products": slow,
        "slow_days": slow_days,
        "computed_at": datetime.now().isoformat(timespec="seconds"),
    }


def cached(db, refresh: bool = False) -> dict:
    with _CACHE_LOCK:
        hit = _CACHE.get("data")
        if hit and not refresh and time.time() - _CACHE["at"] < _TTL_SEC:
            return {**hit, "cached": True}
    data = compute(db)
    with _CACHE_LOCK:
        _CACHE["data"] = data
        _CACHE["at"] = time.time()
    return {**data, "cached": False}
