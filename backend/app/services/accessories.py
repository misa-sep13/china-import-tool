"""発注用付属品（purchase_components）にSKUを持たせる。

付属品にSKUが無いと、タオタロウへ送る管理番号が本体のSKUになる。
届いた配送依頼で付属品の行を本体と見分けられず、納品数が倍に化けた
（配送依頼721710で a021_stand_tube_squeezer が 40→80）。

そこで、SKUが空の付属品には自動で番号を付け、商品マスタに部材
（is_component）として作る。同じ仕入先ページ・同じ仕様のものが既に
部材としてあれば、それを使う（色違いの子4つが同じ収納袋を使うなど）。
"""
import re

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.models.product import Product


def _offer(url: str) -> str:
    """1688のURLを商品ページの番号で比べられる形にする（?以降は無視）。"""
    u = (url or "").strip()
    m = re.search(r"offer/(\d+)", u)
    if m:
        return "1688:" + m.group(1)
    return u.split("?")[0].rstrip("/").lower()


def _prefix(base_sku: str) -> str:
    """本体のSKUの頭（a021_stand_tube_squeezer → a021）。"""
    b = (base_sku or "").strip()
    return b.split("_")[0] if b else "acc"


def _next_sku(db: Session, prefix: str) -> str:
    n = 1
    while db.query(Product).filter(Product.sku == f"{prefix}_acc{n}").first():
        n += 1
    return f"{prefix}_acc{n}"


def ensure_skus(db: Session, comps: list, base_sku: str) -> tuple:
    """SKUが空の付属品に番号を付け、部材として商品マスタに作る。

    戻り値: (SKUを埋めた付属品のリスト, 新しく作ったSKUのリスト)
    URLが無いものは発注先が決まらないので触らない（発注時にも出さない行）。
    """
    from app.api.routes.products import _cost_per_yuan
    made = []
    out = []
    parts = None
    for c in comps or []:
        if not isinstance(c, dict):
            continue
        c = dict(c)
        sku = (c.get("sku") or "").strip()
        url = (c.get("buy_url") or "").strip()
        spec = (c.get("supplier_spec") or c.get("spec") or "").strip()
        if sku or not url:
            out.append(c)
            continue
        if parts is None:
            parts = (db.query(Product)
                     .filter(Product.is_component == True,
                             Product.is_active == True).all())
        hit = next((p for p in parts
                    if _offer(p.buy_url) == _offer(url)
                    and (p.spec or "").strip() == spec), None)
        if hit is None:
            new_sku = _next_sku(db, _prefix(base_sku))
            price = c.get("price")
            try:
                price = float(price) if price not in (None, "") else 0.0
            except (TypeError, ValueError):
                price = 0.0
            max_no = db.query(sa_func.max(Product.no)).scalar() or 0
            hit = Product(
                sku=new_sku, no=max_no + 1, supplier="タオタロウ",
                is_component=True, is_active=True, set_size=1,
                name=((c.get("name") or "").strip() or spec or new_sku)[:500],
                spec=spec, buy_url=url, price=price,
                cost_jpy=(round(price * _cost_per_yuan(db), 1) if price else None),
            )
            db.add(hit)
            db.flush()
            parts.append(hit)
            made.append(new_sku)
        c["sku"] = hit.sku
        out.append(c)
    return out, made


# ---------- 入数（pack_size）----------
#
# 付属品の「数量」は本体1つに付ける数（必要数）。仕入先の1つに何個
# 入っているか（入数）は別の話で、これまで持っていなかった。
# a030 の替えロールは10巻で1つのページなのに、必要数2をそのまま
# 送っていたので、10巻パックを2つ＝20巻、本体100個なら2,000巻の
# 発注になっていた。欲しいのは200巻。
# 入数が空（または1）なら、これまでと同じ計算になる。


def need_qty(comp: dict) -> int:
    """本体1つに付ける数（必要数）。"""
    try:
        n = int(float((comp or {}).get("qty") or 1))
    except (TypeError, ValueError):
        return 1
    return n if n > 0 else 1


def pack_size(comp: dict) -> int:
    """仕入先の1つに何個入っているか（入数）。空・不正は1。"""
    try:
        n = int(float((comp or {}).get("pack_size") or 1))
    except (TypeError, ValueError):
        return 1
    return n if n > 0 else 1


def order_qty(units, comp: dict) -> int:
    """本体 units 個ぶんの、この付属品の発注数（仕入先の単位）。

    必要数を入数で割り、切り上げる。端数は捨てられない（半分の
    パックは買えない）ので、多いほうへ寄せる。
    """
    try:
        u = int(float(units or 0))
    except (TypeError, ValueError):
        u = 0
    total = max(0, u) * need_qty(comp)
    if total <= 0:
        return 0
    return -(-total // pack_size(comp))
