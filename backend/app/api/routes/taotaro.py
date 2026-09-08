"""タオタロウAPIの窓口。

トークンは発注権限そのものなので、ブラウザには渡さずここで持つ。
画面はこのサーバー経由で呼ぶ（仕様書もサーバー間通信を前提としている）。

支払い（/send-orders/pay）は用意していない。取り消せないため、
仕様書の推奨どおり「検知と金額の取得」までをツールで行い、
実際の支払いは管理画面で目視確認のうえ実行する。
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.order_history import OrderHistory
from app.models.product import Product
from app.services import taotaro

router = APIRouter(prefix="/taotaro", tags=["taotaro"])


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except taotaro.TaotaroError as e:
        # 認証や権限の問題はそのまま画面に出したいので、文言を保つ
        raise HTTPException(status_code=502, detail=e.message)


@router.get("/ping")
def ping():
    """繋がるかどうかの確認。設定直後の切り分け用。"""
    if not taotaro.is_configured():
        return {"ok": False, "detail": "トークンが未設定です（TAOTARO_API_TOKEN）"}
    return _call(taotaro.ping)


def _to_our_names(items: list, db: Session) -> None:
    """中身の商品名を自社の日本語名に置き換える。

    原文（中国語）のままでは、どの便か見分けるのが難しい。
    荷受けの取り込みと同じ照合を使うので、同じ商品なら同じ名前になる。
    照合できなかった行は原文のまま残す（消すと中身が分からなくなる）。
    """
    from app.api.routes.welfare import _match_product, _product_indexes
    by_url_spec, unique_url, by_url_all, by_sku = _product_indexes(db)
    for x in items:
        names = []
        for line in x.pop("lines", []) or []:
            product, _ = _match_product(line, by_url_spec, unique_url, by_url_all, by_sku)
            name = (product.name if product else "") or line.get("name_cn") or ""
            name = name.strip()
            if name and name not in names:
                names.append(name[:26])
            if len(names) >= 3:
                break
        x["titles"] = names


@router.get("/send-orders")
def list_send_orders(
    page: int = 1,
    limit: int = Query(20, ge=1, le=100),
    state: Optional[int] = None,
    keyword: str = "",
    db: Session = Depends(get_db),
):
    """配送依頼の一覧。state=7 がお支払い待ち。"""
    d = _call(taotaro.list_send_orders, page=page, limit=limit,
              state=state, keyword=keyword)
    _to_our_names(d.get("items") or [], db)
    return d


@router.get("/send-orders/{sid:int}")
def get_send_order(sid: int):
    """配送依頼の詳細。費用の内訳と同梱注文の明細。"""
    return _call(taotaro.get_send_order, sid)


@router.get("/awaiting-payment")
def awaiting_payment():
    """お支払い待ちの配送依頼。支払い忘れによる出荷遅延を防ぐため。"""
    d = _call(taotaro.list_send_orders, page=1, limit=100, state=7)
    items = d.get("items") or []
    return {
        "count": len(items),
        "total_cny": round(sum((x.get("total_send_fee") or 0) for x in items), 2),
        "items": items,
    }


@router.get("/debug-match")
def debug_match(sid: int, db: Session = Depends(get_db)):
    """一覧の明細が自社商品に当たるかを1行ずつ見る（調査用）。"""
    from app.api.routes.welfare import _match_product, _product_indexes
    from app.services.taotaro import _request, _summary
    d = _request("/api/v1/send-orders", {"page": 1, "limit": 100, "sid": sid})
    items = [x for x in (d.get("items") or []) if x.get("sid") == sid]
    if not items:
        return {"detail": f"sid={sid} が一覧に見つかりません"}
    idx = _product_indexes(db)
    out = []
    for line in _summary(items[0])["lines"][:8]:
        product, how = _match_product(line, *idx)
        out.append({
            "url": line["buy_url"][:60], "spec": line["supplier_spec"],
            "size": line["size"][:34], "memo": line["customer_memo"],
            "matched": product.sku if product else None, "how": how,
        })
    return {"sid": sid, "lines": out}


@router.get("/debug-line")
def debug_line():
    """一覧の明細にどの項目が入っているかを見る（調査用）。"""
    from app.services.taotaro import _request
    d = _request("/api/v1/send-orders", {"page": 1, "limit": 1})
    items = d.get("items") or []
    if not items:
        return {"detail": "配送依頼がありません"}
    orders = items[0].get("orders") or []
    if not orders:
        return {"send_order_keys": sorted(items[0].keys()), "orders": 0}
    o = orders[0]
    return {"order_keys": sorted(o.keys()),
            "sample": {k: str(v)[:80] for k, v in o.items()
                       if k in ("goods_url", "url", "good_skus", "goods_name", "out_id")}}


# ---------- 発注 ----------
#
# 画面から直接 create_orders を叩かせない。先に /order-preview で
# 商品詳細を取り直し、どのSKUを買うことになるかを人に見せてから
# /order-submit を呼ぶ、という2段構えにしている。
# 色違いが届く事故は取り返しがつかないため。

class PreviewItem(BaseModel):
    sku: str
    qty: int
    buy_url: str = ""
    name: str = ""
    color: str = ""
    size: str = ""
    spec: str = ""


class PreviewRequest(BaseModel):
    items: List[PreviewItem]


@router.post("/order-preview")
def order_preview(req: PreviewRequest, db: Session = Depends(get_db)):
    """発注の下調べ。商品詳細を取り直し、SKUの候補と単価・在庫を返す。

    仕様書のとおり、価格と在庫はキャッシュされるので発注の直前に取り直す。
    ここで ok=false のものは、画面でSKUを選んでもらうまで発注できない。
    """
    out = []
    for it in req.items:
        row = {
            "sku": it.sku, "name": it.name, "qty": it.qty,
            "buy_url": it.buy_url, "color": it.color, "size": it.size,
            "ok": False, "error": "", "skus": [], "chosen": None,
            "product_id": None, "platform": "", "title": "",
            "min_order_quantity": 1, "remembered": False,
        }
        product = db.query(Product).filter(Product.sku == it.sku).first()
        url = (it.buy_url or (product.buy_url if product else "") or "").strip()
        if not url:
            row["error"] = "仕入URLがありません"
            out.append(row); continue
        if not taotaro._platform_of(url):
            row["error"] = "1688・淘宝以外のURLです（このAPIでは発注できません）"
            out.append(row); continue

        try:
            d = taotaro.goods_detail(url)
        except taotaro.TaotaroError as e:
            # 1688で商品が消えているとサーバーエラーになる。仕様書の指示どおり
            # リトライせず、この商品だけ飛ばす
            row["error"] = e.message
            out.append(row); continue

        row.update({
            "product_id": d["product_id"], "platform": d["platform"],
            "title": d.get("title_trans") or d.get("title") or "",
            "skus": d["skus"], "min_order_quantity": d["min_order_quantity"],
            "status": d.get("status"),
        })

        chosen = None
        # 一度人が確かめた組み合わせがあれば、それを最優先で使う
        if product and product.taotaro_sku_id:
            for s in d["skus"]:
                if s["sku_id"] == product.taotaro_sku_id:
                    chosen = s
                    row["remembered"] = True
                    break
        if not chosen:
            chosen = taotaro.match_sku(
                d["skus"], it.color or (product.color if product else ""),
                it.size or (product.size if product else ""),
                it.spec or (product.spec if product else ""))

        if not chosen:
            row["error"] = ("色・サイズがどれに当たるか決められませんでした。"
                            "選んでください")
            out.append(row); continue

        row["chosen"] = chosen
        if d.get("status") and d["status"] != "published":
            row["error"] = f"掲載状態が {d['status']} です（購入できない可能性）"
        elif it.qty < (d["min_order_quantity"] or 1):
            row["error"] = f"最小発注数 {d['min_order_quantity']} を下回っています"
        elif chosen.get("stock") is not None and it.qty > (chosen["stock"] or 0):
            row["error"] = f"在庫 {chosen['stock']} 個を超えています"
        else:
            row["ok"] = True

        row["inspect"] = taotaro.inspect_options(
            product.taotaro_inspect if product else None)
        out.append(row)

    return {"items": out,
            "ok_count": len([x for x in out if x["ok"]]),
            "ng_count": len([x for x in out if not x["ok"]])}


class SubmitItem(BaseModel):
    sku: str
    qty: int
    buy_url: str
    title: str = ""
    platform: str
    product_id: int
    sku_id: str
    remark: str = ""
    asin: str = ""
    fnsku: str = ""
    fba: int = 1
    # 検品オプション。画面で変えられる。覚えさせるかは remember_inspect で決める
    inspect: dict = {}
    remember_sku: bool = True
    remember_inspect: bool = False


class SubmitRequest(BaseModel):
    items: List[SubmitItem]


@router.post("/order-submit")
def order_submit(req: SubmitRequest, db: Session = Depends(get_db)):
    """発注を実行する。/order-preview で確認したものだけを渡すこと。

    タオタロウには goods_list でまとめて送る。1回のリクエストで
    まとめて作られるため、途中まで作られて失敗という状態にはならない。
    """
    if not req.items:
        raise HTTPException(status_code=400, detail="発注する商品がありません")

    goods_list = []
    for it in req.items:
        if it.qty <= 0:
            continue
        g = {
            "platform": it.platform,
            "product_id": int(it.product_id),
            "sku_id": str(it.sku_id),
            "title": it.title or it.sku,
            "url": it.buy_url,
            "quantity": int(it.qty),
            # 自社SKUを入れておくと、配送依頼の取り込みで照合が要らなくなる
            "out_id": it.sku,
        }
        if it.remark:
            g["remark"] = it.remark
        if it.fba and it.asin:
            g["fba"] = 1
            g["asin"] = it.asin
            if it.fnsku:
                g["fnsku"] = it.fnsku
        g.update(taotaro.inspect_options(it.inspect))
        goods_list.append(g)

    if not goods_list:
        raise HTTPException(status_code=400, detail="発注数が1以上の商品がありません")

    r = _call(taotaro.create_orders, goods_list)

    # 発注できたので、確かめた組み合わせと検品オプションを覚える。
    # 次からは自動で決まり、確認画面で選び直す手間が消える
    import json as _json
    for it in req.items:
        product = db.query(Product).filter(Product.sku == it.sku).first()
        if not product:
            continue
        if it.remember_sku:
            product.taotaro_product_id = int(it.product_id)
            product.taotaro_sku_id = str(it.sku_id)
        if it.remember_inspect:
            product.taotaro_inspect = _json.dumps(
                taotaro.inspect_options(it.inspect), ensure_ascii=False)

    # 発注履歴に残す。Excel出力のときと同じ形にしておく
    oids = r.get("oids") or []
    for i, it in enumerate(req.items):
        product = db.query(Product).filter(Product.sku == it.sku).first()
        db.add(OrderHistory(
            sku=it.sku,
            name=it.title or (product.name if product else ""),
            color=(product.color if product else ""),
            size=(product.size if product else ""),
            qty=it.qty,
            price=(product.price if product else 0) or 0,
            buy_url=it.buy_url,
            photo_url=(product.photo_url if product else ""),
            asin=it.asin,
            fnsku=it.fnsku,
            note=it.remark,
            # 1件ずつのIDが取れないこともある。その場合は out_id で照会できる
            taotaro_order_id=(oids[i] if i < len(oids) else None),
        ))
    db.commit()

    return {"ordered": len(goods_list), "oids": oids,
            "recorded": len(req.items)}


@router.post("/order-cancel")
def order_cancel(order_ids: str):
    """買付開始前の注文を取り消す。カンマ区切りで複数指定できる。"""
    ids = [x.strip() for x in (order_ids or "").split(",") if x.strip()]
    done = _call(taotaro.cancel_orders, ids)
    return {"requested": len(ids), "cancelled": done,
            "not_cancelled": [x for x in ids if x not in done]}
