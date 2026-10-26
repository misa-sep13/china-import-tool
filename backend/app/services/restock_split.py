"""タオタロウの倉庫にある在庫を「航空便／船便／倉庫に残す」に振り分ける。

発注した時点で必要だった数と、いま必要な数は違う。売れ行きが落ちれば
送りすぎになるし、落ちた商品をFBAに積むと保管料を払って寝かせることに
なる。配送依頼をかける前に、いまの売れ行きで計算し直す。

考え方：
  航空便   船便が届く日までに欠品する分だけ。送料が高いので最小限
  船便     目標在庫日数に足りない残り
  倉庫     送らずに中国へ置く。90日は無料なので、急いで送る理由はない

倉庫に残すぶんには期限がある。無料保管は入庫から90日なので、
古いものには印を付けて、保管料に変わる前に出せるようにする。
"""
from datetime import datetime, timezone
from typing import Optional

from app.models.product import Product
from app.models.rakuten_product import RakutenProduct
from app.services import taotaro

# 入庫から何日で無料保管が切れるか。残り日数がこれ以下なら印を付ける
FREE_DAYS = 90
WARN_DAYS = 20


def _days_since(iso: Optional[str]) -> Optional[int]:
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except Exception:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - d).days


def warehouse_stock(db, pages: int = 5) -> dict:
    """倉庫にある在庫を自社SKUごとにまとめる。

    state=4（入庫済み）で、まだ便に入っていないものだけを数える。
    便に入っているものは、もう送る手続きが済んでいる。
    """
    prods = {p.sku: p for p in
             db.query(Product).filter(Product.is_active == True).all()}

    rows = {}
    for page in range(1, max(1, pages) + 1):
        d = taotaro.list_orders(page=page, limit=100)
        for o in d.get("items") or []:
            if o.get("state") != 4:
                continue
            if o.get("sid"):
                continue                      # もう便に入っている
            sku = str(o.get("out_id") or "").strip()
            p = prods.get(sku)
            if p is None or p.is_component:
                continue
            # FNSKUもASINも無い＝Amazonに出していない。同じSKUで
            # 商品マスタにも載っているが、楽天ぶんとして発注したもの。
            # Amazonの画面に出す意味がない
            if not ((p.fnsku or "").strip() or (p.asin or "").strip()):
                continue
            qty = int(o.get("quantity") or 0)
            if qty <= 0:
                continue
            age = _days_since(o.get("arrived_at"))
            r = rows.setdefault(sku, {
                "sku": sku, "name": p.name or "", "pieces": 0,
                "set_size": max(1, p.set_size or 1),
                "oldest_days": age, "orders": [],
            })
            r["pieces"] += qty
            if age is not None and (r["oldest_days"] is None
                                    or age > r["oldest_days"]):
                r["oldest_days"] = age
            r["orders"].append({"oid": o.get("oid"), "qty": qty,
                                "arrived_days": age})
        if not d.get("has_more_pages"):
            break
    return rows


def rakuten_need(db, skus: set, lt_sea: int) -> dict:
    """楽天でも売っている商品の、取り置きが要る数。

    同じSKUで両方に出しているので、中国の在庫は1つの山になる。
    先に楽天ぶんを取り置かないと、楽天の在庫が切れる。
    次の船便が届くまで持たせる数だけ残す。
    """
    out = {}
    rows = (db.query(RakutenProduct)
            .filter(RakutenProduct.sku.in_(list(skus)))
            .filter(RakutenProduct.is_active == True).all())
    for r in rows:
        if r.is_promo or r.is_material:
            continue
        # 楽天の販売数は63日ぶん（APIの上限）。在庫切れの日は除いて日販にする
        days = max(1, 63 - int(r.stockout_days_90 or 0))
        daily = float(r.sales_90 or 0) / days
        have = int(r.stock or 0) + int(r.inbound or 0) + int(r.standard_stock or 0)
        need = max(0, round(daily * lt_sea) - have)
        out[r.sku] = {"daily": round(daily, 2), "stock": have,
                      "days": int(have / daily) if daily > 0 else None,
                      "reserve": need}
    return out


def split(stock: dict, plan_items: list, lt_sea: int, lt_air: int,
          target_days: int, rakuten: Optional[dict] = None) -> list:
    """倉庫の在庫を航空便・船便・倉庫に振り分ける。

    stock: warehouse_stock() の戻り値
    plan_items: 納品プランの計算結果（日販・FBA在庫を持っている）
    rakuten: 楽天でも売っている商品の取り置き数
    """
    by_sku = {it["sku"]: it for it in plan_items}
    rakuten = rakuten or {}
    out = []
    for sku, s in stock.items():
        it = by_sku.get(sku) or {}
        daily = float(it.get("daily") or 0) * float(it.get("growth") or 1)
        fba = int(it.get("fba_available") or 0)
        inbound = int(it.get("fba_inbound") or 0) + int(it.get("fba_processing") or 0)
        have = fba + inbound
        china_all = int(s["pieces"])

        # 楽天でも売っている商品は、先に楽天ぶんを取り置く。
        # 残りをAmazonに振り分ける（同じSKU＝同じ商品のため）
        rk = rakuten.get(sku)
        reserve = min(int(rk["reserve"]) if rk else 0, china_all)
        china = china_all - reserve

        if daily <= 0:
            # 売れ行きが無い。新商品は初回を送りたいので全部船便、
            # 既に在庫がある商品は送らない（寝かせても仕方がない）
            air = 0
            sea = china if have == 0 else 0
        else:
            # 船便が届く日までに売れる数に足りない分を空輸する
            air = max(0, round(daily * lt_sea) - have)
            air = min(air, china)
            # 目標日数に足りない残りを船便で
            need = max(0, round(daily * target_days) - have - air)
            sea = min(need, china - air)

        keep = china - air - sea
        left = (FREE_DAYS - s["oldest_days"]) if s["oldest_days"] is not None else None
        out.append({
            "sku": sku,
            "name": s["name"],
            "set_size": s["set_size"],
            "china_pieces": china_all,
            "rakuten_reserve": reserve,
            "rakuten_daily": rk["daily"] if rk else None,
            "rakuten_stock": rk["stock"] if rk else None,
            "rakuten_days": rk["days"] if rk else None,
            "amazon_pool": china,
            "daily": round(daily, 2),
            "fba_available": fba,
            "fba_inbound": inbound,
            "fba_days": int(have / daily) if daily > 0 else None,
            "air_pieces": air,
            "sea_pieces": sea,
            "keep_pieces": keep,
            "oldest_days": s["oldest_days"],
            "free_days_left": left,
            # 無料保管が切れそうなのに倉庫へ残す。放っておくと保管料になる
            "warn_storage": bool(keep > 0 and left is not None and left <= WARN_DAYS),
        })
    out.sort(key=lambda x: (x["free_days_left"] is None,
                            x["free_days_left"] if x["free_days_left"] is not None else 0))
    return out
