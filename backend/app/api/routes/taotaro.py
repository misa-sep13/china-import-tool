"""タオタロウAPIの窓口。

トークンは発注権限そのものなので、ブラウザには渡さずここで持つ。
画面はこのサーバー経由で呼ぶ（仕様書もサーバー間通信を前提としている）。

支払い（/send-orders/pay）は用意していない。取り消せないため、
仕様書の推奨どおり「検知と金額の取得」までをツールで行い、
実際の支払いは管理画面で目視確認のうえ実行する。
"""
import json
from types import SimpleNamespace
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


@router.get("/orders")
def list_orders(page: int = 1, limit: int = Query(100, ge=1, le=100),
                start_time: Optional[int] = None):
    """タオタロウに入っている注文の一覧。読むだけ。

    発注したつもりのものが本当に向こうに入っているかを
    突き合わせるためのもの。out_id が自社のSKU。
    """
    return _call(taotaro.list_orders, page=page, limit=limit,
                 start_time=start_time)


@router.get("/ship-options")
def ship_options():
    """配送依頼を出すときに選ぶもの（便・届け先・原産地シール）。

    便は船便・航空便の2つに決めてあるので、16種類の一覧は出さない。
    届け先は3つあるため（作業所・FBA・自社）、毎回選んでもらう。
    """
    addrs = _call(taotaro.addresses)
    return {
        "ways": [{"key": k, "label": v["label"],
                  "delivery_name": v["delivery_name"], "note": v["note"]}
                 for k, v in taotaro.SHIP_WAYS.items()],
        "always_remark": taotaro.SHIP_REMARK_ALWAYS,
        # type 1＝届け先 / 2＝輸入者 / 3＝送り主
        "addresses": [{"address_id": a.get("address_id"), "type": a.get("type"),
                       "is_default": a.get("is_default"),
                       "consignee": a.get("consignee"),
                       "address": a.get("address")}
                      for a in addrs],
    }


class SendOrderIn(BaseModel):
    oids: List[int]
    way: str                       # sea / air
    address_id: int
    made_in_china_flag: int = 3
    importer_address_id: Optional[int] = None
    note: str = ""                 # 毎回の「急ぎです」に足す一言
    client_order_id: Optional[str] = None


class SendCheckIn(BaseModel):
    oids: List[int] = []


class ClassifyIn(BaseModel):
    orders: List[dict] = []


@router.post("/classify")
def classify_orders(data: ClassifyIn, db: Session = Depends(get_db)):
    """画面が持っている注文を、商品マスタだけで見分ける（タオタロウは呼ばない）。

    Amazon／楽天の振り分けと自社の商品名をすぐ出すため。
    セット組みの確かめ（send-check）はタオタロウの一覧を読むので時間がかかる。
    """
    from app.services import restock_split as rs
    return {"kinds": rs.classify_orders(db, data.orders)}


@router.post("/send-check")
def send_check(data: SendCheckIn, db: Session = Depends(get_db)):
    """配送依頼に入れる注文を確かめる（読むだけ）。

    セット組みの付属品が足りない・付属品だけ入っている・管理番号が
    商品マスタに無い、を返す。各注文が本体か付属品かの札も返す。
    """
    from app.services import restock_split as rs
    if not taotaro.is_configured():
        raise HTTPException(400, "タオタロウのトークンが未設定です")
    try:
        return rs.send_check(db, data.oids)
    except Exception as e:
        raise HTTPException(502, f"確かめられませんでした（{str(e)[:200]}）")


@router.post("/send-orders")
def create_send_order(data: SendOrderIn):
    """配送依頼を作る。

    client_order_id を付けて送る。通信が切れて作られたか分からない
    ときに、同じ鍵でそのまま送り直せば二重にならない。
    画面から来ないときは、注文の並びから毎回同じ鍵を作る。
    """
    key = (data.client_order_id or "").strip()
    if not key:
        import hashlib
        seed = ",".join(sorted(str(x) for x in data.oids)) + "|" + data.way
        key = "cit-" + hashlib.sha1(seed.encode()).hexdigest()[:24]
    res = _call(taotaro.create_send_order,
                oids=data.oids, way=data.way, address_id=data.address_id,
                made_in_china_flag=data.made_in_china_flag,
                importer_address_id=data.importer_address_id,
                extra_note=data.note, client_order_id=key)
    # 便に入った注文を、確かめるときに倉庫の在庫として数えないよう覚えを捨てる
    from app.services import restock_split as rs
    rs._orders_cache.clear()
    return res


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


@router.get("/balance")
def balance():
    """残高。発注の前に足りているか見るためのもの。"""
    if not taotaro.is_configured():
        return {"ok": False, "detail": "トークンが未設定です（TAOTARO_API_TOKEN）"}
    return _call(taotaro.balance)


@router.get("/transactions")
def transactions(page: int = 1, limit: int = Query(50, ge=1, le=100)):
    """入出金明細。会計との突合に使う。"""
    return _call(taotaro.transactions, page=page, limit=limit)


@router.get("/send-orders/{sid:int}/transactions")
def send_order_transactions(sid: int):
    """ある便に紐づく入出金明細。実際に引き落とされた額が分かる。

    配送依頼の詳細に出る費用は見積もりの内訳で、値引きや調整が入ると
    実際の引落と食い違う。原価に載せるのは引き落とされたほうなので、
    こちらも取れるようにしておく。
    """
    items = _call(taotaro.transactions_for, sid)
    total = sum(float(x.get("money") or 0) for x in items)
    return {"sid": sid, "count": len(items),
            "total_money": round(total, 2), "items": items}


@router.get("/send-orders/{sid:int}/invoice")
def send_order_invoice(sid: int):
    """請求書の発行状況とダウンロード先。URLは期限付き。"""
    return _call(taotaro.invoice, sid)


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


def _expand_for_order(items, db: Session) -> list:
    """発注の行をほどく。本体の下に、発注用付属品（purchase_components）を足す。

    1つの1688ページに本体と収納袋が入っている商品のように、一緒に頼むものが
    ある。付属品は在庫には連動しないが、頼まないと本体だけ届く。
    楽天側は前から展開していたが、Amazon側は本体しか送っていなかった。

    どの発注から展開した行かを持ち回る。発注履歴は販売単位で1件だけ残したい
    ので、行が増えたぶんだけ数が膨らまないようにするため。
    """
    rows = []
    for it in items:
        product = db.query(Product).filter(Product.sku == it.sku).first()
        # 画面の発注数は販売単位（セット数）。仕入先へ頼むのは個数なので、
        # 入数を掛けて送る。掛けずに送っていたため、2個セットを30と入れても
        # 30個しか発注されず、15セット分しか作れなかった
        unit = (product.set_size or 1) if product else 1
        rows.append({
            "sku": it.sku, "name": it.name, "qty": int(it.qty) * unit,
            "buy_url": it.buy_url, "color": it.color, "size": it.size,
            "spec": it.spec, "product": product,
            "origin_sku": it.sku, "origin_qty": it.qty, "is_accessory": False,
            "out_sku": it.sku,
        })
        if not product:
            continue
        try:
            pcomps = json.loads(getattr(product, "purchase_components", None) or "[]")
        except (ValueError, TypeError):
            pcomps = []
        # 同じものが二重に登録されていることがある（色ごとに1つずつ
        # 入れてしまったなど）。同じ発注先・同じ仕様のものは1つにまとめる。
        # そのまま流すと同じ付属品を2回頼むことになる
        seen_comp = set()
        for comp in pcomps:
            comp_sku = (comp.get("sku") or "").strip()
            comp_url = (comp.get("buy_url") or "").strip()
            comp_spec = (comp.get("supplier_spec") or comp.get("spec") or "").strip()
            c = (db.query(Product).filter(Product.sku == comp_sku).first()
                 if comp_sku else None)
            if c:
                comp_url = comp_url or c.buy_url or ""
                comp_spec = comp_spec or c.spec or ""
            # URLが無ければ発注先が決まらない。黙って本体のURLで買うと
            # 違うものが届くので、この行は出さない
            if not comp_url:
                continue
            key = (comp_sku, comp_url, comp_spec)
            if key in seen_comp:
                continue
            seen_comp.add(key)
            # 付属品にSKUが無いと本体と同じSKUで並び、同じ商品が
            # 何行も出たように見える。画面では区別できる名前にする
            label = (comp_sku or (it.sku + "（付属品）"))
            rows.append({
                "sku": label,
                "name": comp.get("name") or comp_spec or comp_sku or "付属品",
                "qty": int(it.qty) * int(comp.get("qty") or 1),
                "buy_url": comp_url, "color": "", "size": "",
                "spec": comp_spec, "product": c,
                "origin_sku": it.sku, "origin_qty": it.qty,
                # 自分のSKUを持たない付属品は、本体のSKUで並ぶ。
                # 本体の「覚えた組み合わせ」を上書きしないよう印を付ける
                "is_accessory": not comp_sku,
                # タオタロウへ送る管理番号。表示用の名前ではなく、
                # 本体のSKUを送る（配送依頼の取り込みで照合に使うため）
                "out_sku": comp_sku or it.sku,
            })
    return rows


@router.post("/order-preview")
def order_preview(req: PreviewRequest, db: Session = Depends(get_db)):
    """発注の下調べ。商品詳細を取り直し、SKUの候補と単価・在庫を返す。

    仕様書のとおり、価格と在庫はキャッシュされるので発注の直前に取り直す。
    ここで ok=false のものは、画面でSKUを選んでもらうまで発注できない。
    """
    out = []
    for it in _expand_for_order(req.items, db):
        it = SimpleNamespace(**it)
        product = it.product
        row = {
            "sku": it.sku, "name": it.name, "qty": it.qty,
            "buy_url": it.buy_url, "color": it.color, "size": it.size,
            # どの発注から展開された行か。発注履歴を販売単位で残すのに使う
            "origin_sku": it.origin_sku, "origin_qty": it.origin_qty,
            "is_accessory": it.is_accessory,
            "ok": False, "error": "", "skus": [], "chosen": None,
            "product_id": None, "platform": "", "title": "",
            "min_order_quantity": 1, "remembered": False,
            # 商品マスタの備考。現場へ伝えないと困ることが書いてあるので、
            # そのまま発注の備考へ持っていく。Excelは「お客様専用メモ」と
            # 「備考」の両方を出しているので、どちらも入れる
            # 商品マスタの単価（元）。仕入先の実売価と大きく違えば、
            # 円で入れてしまっている可能性がある
            "master_price": (product.price if product else None),
            "note": " / ".join([x for x in [
                str((product.customer_memo if product else "") or "").strip(),
                str((product.note if product else "") or "").strip(),
            ] if x]),
        }
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
            # 仕入先の商品名は原文のまま使う。訳は「純綿の蜂の巣は吸水して
            # 厚い雑巾を厚くします」のように意味の通らない日本語になり、
            # それがそのままタオタロウの注文名になってしまう
            "title": d.get("title") or d.get("title_trans") or "",
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
            if it.is_accessory:
                # 本体と同じページを指す付属品。本体のSKUに含まれている
                # ことが多い（「套装（収納袋＋眼罩耳塞）」など）。
                # 別に頼むものが無いなら、リサーチシートの付属品欄から消す
                row["error"] = (
                    "本体と同じページです。本体のSKUに含まれているなら、"
                    "リサーチシートの付属品欄から消してください。"
                    "別に頼むものなら、付属品にURLと仕様を入れてください")
            else:
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
    # どの発注から展開された行か。付属品の行が増えても発注履歴が
    # 膨らまないようにするため（楽天側で30セットが120と記録された）
    origin_sku: str = ""
    origin_qty: Optional[int] = None
    # 自分のSKUを持たない付属品。本体の覚えた組み合わせを上書きしない
    is_accessory: bool = False
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
        # FBA納品の指定。文字列の "1" を送る。
        # ASIN・FNSKUはこれとは別物で、あれば一緒に送る。
        # 以前はASINが無いとFBAの印ごと送っていなかったが、まだASINが
        # 決まっていない新商品もFBAへ送るので、分けて扱う
        if it.fba:
            g["fba"] = "1"
        if it.asin:
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
        # 付属品は本体のSKUで並ぶことがある。そのまま覚えると、
        # 次の発注で本体のかわりに収納袋が選ばれてしまう
        if it.remember_sku and not it.is_accessory:
            product.taotaro_product_id = int(it.product_id)
            product.taotaro_sku_id = str(it.sku_id)
        if it.remember_inspect:
            product.taotaro_inspect = _json.dumps(
                taotaro.inspect_options(it.inspect), ensure_ascii=False)

    # 発注履歴に残す。Excel出力のときと同じ形にしておく。
    # 付属品は本体と同じSKUで来ることがある（自分のSKUを持たない収納袋など）。
    # 行ごとに残すと、1回の発注が付属品の数だけ多く記録されてしまうので、
    # 親と同じSKUの行は発注1件につき1行にまとめる
    oids = r.get("oids") or []
    seen_origin = set()
    for i, it in enumerate(req.items):
        origin = (it.origin_sku or it.sku).strip()
        if it.sku == origin:
            if origin in seen_origin:
                continue
            seen_origin.add(origin)
        product = db.query(Product).filter(Product.sku == it.sku).first()
        db.add(OrderHistory(
            sku=it.sku,
            # 発注履歴はこちらの商品名で残す。it.title は仕入先の原文
            # （中国語）で、タオタロウへ送るためのもの。履歴に入れると
            # 一覧が中国語だらけになって、どれがどれか分からなくなる
            name=(product.name if product else "") or it.title,
            color=(product.color if product else ""),
            size=(product.size if product else ""),
            qty=(it.origin_qty if (it.sku == (it.origin_sku or it.sku)
                                   and it.origin_qty) else it.qty),
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

@router.get("/debug-goods")
def debug_goods(url: str):
    """商品詳細が実際にどう返るかを見る（調査用）。

    照合が当たらないとき、選択肢のラベルが訳だけなのか原文も来るのか、
    商品マスタの書き方とどこが違うのかを、推測せずに確かめるため。
    """
    d = taotaro.goods_detail(url)
    return {
        "title": d.get("title"), "title_trans": d.get("title_trans"),
        "product_id": d.get("product_id"),
        "min_order_quantity": d.get("min_order_quantity"),
        "skus": [{"sku_id": s["sku_id"], "label": s["label"],
                  "label_raw": s.get("label_raw"), "stock": s.get("stock"),
                  "price": s.get("price")}
                 for s in (d.get("skus") or [])[:20]],
    }


@router.get("/debug-match-spec")
def debug_match_spec(url: str, spec: str):
    """商品マスタの仕様が、どの選択肢に当たるかを1件ずつ見る（調査用）。"""
    d = taotaro.goods_detail(url)
    chosen = taotaro.match_sku(d["skus"], spec, "", "")
    return {
        "spec": spec,
        "spec_parts": taotaro._parts(spec),
        "chosen": chosen["label"] if chosen else None,
        "candidates": [
            {"label": s["label"], "label_raw": s.get("label_raw"),
             "parts": taotaro._label_parts(s["label"])
                      + taotaro._label_parts(s.get("label_raw"))}
            for s in (d.get("skus") or [])[:20]
        ],
    }


# ---------- 試算・判定（2026-09-24 提供開始） ----------
#
# 上流に行かないので速い。リサーチ権限も不要。
# 応答はこちらで組み替えず、そのまま画面へ渡す（実物の形を見ていないため、
# 勝手に整形すると項目を落とす）。

class QuoteIn(BaseModel):
    price_jpy: float                      # 日本での売価（円）
    length_cm: Optional[float] = None
    width_cm: Optional[float] = None
    height_cm: Optional[float] = None
    weight_g: Optional[float] = None
    qty: Optional[int] = None             # 既定 500
    units_per_carton: Optional[int] = None
    route: Optional[str] = None           # 既定は船便（標準）
    cost_cny: Optional[float] = None      # 入れると採算判定が付く
    duty_rate_pct: Optional[float] = None # 省略すると0%で計算される
    lang: Optional[str] = "ja"


class ScreeningIn(BaseModel):
    product_name: str
    # 文字列で送る。真偽値だとエラーになる（仕様書の注意）
    power: Optional[str] = None           # none / usb / battery / ac
    wireless: Optional[str] = None        # none / bt / wifi / other
    food_contact: Optional[bool] = None
    for_children: Optional[bool] = None
    lookalike: Optional[bool] = None
    health_claim: Optional[bool] = None   # 効能を書く予定か。判定が変わる
    lang: Optional[str] = "ja"


class FreightIn(BaseModel):
    length_cm: Optional[float] = None
    width_cm: Optional[float] = None
    height_cm: Optional[float] = None
    weight_g: Optional[float] = None
    units_per_carton: Optional[int] = None
    product_name: Optional[str] = None
    has_battery: Optional[bool] = None    # こちらは真偽値
    lang: Optional[str] = "ja"


# 判定で必ず送る項目（仕様書 2026-09-28 版）。False も意味を持つので落とさない
_SCREENING_REQUIRED = ("power", "wireless", "food_contact", "for_children")


def _clean(data) -> dict:
    """未入力の項目は送らない。既定値があるものは向こうに任せる。

    ただし判定の必須4項目は、False でもそのまま送る。落とすと
    「指定なし」と同じになり、判定が変わってしまう。
    """
    out = {}
    for k, v in data.model_dump().items():
        if k in _SCREENING_REQUIRED:
            if v is not None:
                out[k] = v
        elif v not in (None, ""):
            out[k] = v
    return out


@router.post("/tools/quote")
def tools_quote(data: QuoteIn):
    """売価から、工場に払える上限を逆算する。"""
    return _call(taotaro.tools_quote, _clean(data))


@router.post("/tools/screening")
def tools_screening(data: ScreeningIn):
    """日本に入れるのに認証が要るかを見る。"""
    return _call(taotaro.tools_screening, _clean(data))


@router.post("/tools/freight")
def tools_freight(data: FreightIn):
    """ルート別の1個あたり国際送料。"""
    return _call(taotaro.tools_freight, _clean(data))


@router.get("/refunds")
def refunds(folder: str = "配送依頼", days: int = 365,
            db: Session = Depends(get_db)):
    """配送依頼メールの「値引きした○元を返金」を、月ごとにまとめる。

    円は設定の為替レート（円/元）で換算して添える。仕入の原価計算で
    使っているものと同じ値なので、他の画面の金額と考え方がそろう。

    メールは読むだけで、既読にも移動にもしない。
    """
    from app.models.settings import OrderSettings
    from app.services import taotaro_refunds, permit_mail
    try:
        data = taotaro_refunds.collect(folder=folder, days=days)
    except permit_mail.PermitMailError as e:
        raise HTTPException(400, str(e))

    row = db.query(OrderSettings).first()
    rate = (getattr(row, "exchange_rate", None) or 21.0) if row else 21.0
    for m in data["months"]:
        m["total_jpy"] = round(m["total_cny"] * rate)
    for r in data["rows"]:
        r["amount_jpy"] = round(r["amount_cny"] * rate)
    data["rate"] = rate
    data["total_jpy"] = round(data["total_cny"] * rate)
    return data


@router.get("/probe")
def probe(path: str):
    """【一時】タオタロウAPIの口が存在するかを確かめる。読み取りだけ。

    問い合わせ（質問管理）を取れる口があるかを調べるためのもの。
    確認が済んだら消す。
    """
    from app.services.taotaro import _request
    p = "/" + path.lstrip("/")
    if not p.startswith("/api/v1/"):
        raise HTTPException(400, "/api/v1/ で始まる経路だけ")
    try:
        d = _request(p, {"page": 1, "limit": 5})
        keys = sorted(d.keys()) if isinstance(d, dict) else type(d).__name__
        # items だけを見ていたが、methods のように別の名前で
        # 返す口もある。最初に見つかった配列を中身として扱う
        items = []
        if isinstance(d, dict):
            for k in ("items", "methods", "list", "data"):
                v = d.get(k)
                if isinstance(v, list) and v:
                    items = v
                    break
        return {"ok": True, "path": p, "keys": keys,
                "count": len(items),
                "first": items[0] if items else None,
                "raw": d if len(str(d)) < 2000 else None}
    except taotaro.TaotaroError as e:
        return {"ok": False, "path": p, "code": e.code, "message": e.message}


@router.post("/watch/check")
def watch_check(db: Session = Depends(get_db)):
    """配送依頼の状態を今すぐ見に行く（普段は10分ごとに自動で動く）。

    初めて押したときは今の状態を覚えるだけで、知らせは飛ばない。
    そうしないと、過去ぶん全部の通知が一度に来る。
    """
    from app.services.send_order_watch import check_once
    return check_once(db)


@router.get("/send-orders/{sid:int}/raw")
def send_order_raw(sid: int):
    """配送依頼の詳細を、タオタロウから返ってきたまま返す。

    新しい項目（箱の情報など）が本番でどう入るのかを確かめるために使う。
    仕様書と実物が食い違うことがあるので、加工前を見られるようにしておく。
    """
    return _call(taotaro.get_send_order, sid, True)


# ---------- 注文のASIN・FNSKU・管理番号を後から入れる ----------
#
# 初回発注の時点では、その商品をまだAmazonに出品していないので
# FNSKUもASINも存在しない。だから発注時には入れようがなく、
# 空のまま注文が作られる。公式APIに注文を更新する口が無いので、
# 会員画面の updateOrder（FBA指示書と同じクッキーで叩く）で後から入れる。
#
# 消す方向には絶対に動かさない。すでに何か入っている欄は触らない。

# 入れてよいステータス。出荷してしまったあと（配送依頼提出済み以降）は
# もう商品ラベルを貼り終わっているので対象にしない
_FILLABLE_STATES = [1, 2, 3, 4, 7]


def _offer_no(url: str) -> str:
    """1688・タオバオのURLから商品番号だけ取る。

    同じ商品でもURLに付くパラメータが毎回違うので、番号で見る
    （fba_plan の取り込みと同じ基準）。
    """
    import re
    m = re.search(r"(\d{10,})", url or "")
    return m.group(1) if m else ""


def _id_plan(db: Session, cookie, states: list) -> dict:
    """何をどう埋めるかを組み立てる。ここでは書き込まない。"""
    from app.models.rakuten_product import RakutenProduct
    from app.services import taotaro_web

    orders = taotaro_web.list_orders(cookie, states=states)

    # 自社の商品。Amazonの商品はASIN・FNSKUを持ち、楽天の商品は持たない。
    # 楽天用の発注にFNSKUを入れてはいけないので、持っているものだけ入れる
    by_sku, by_skuid, by_offer = {}, {}, {}
    # 画面で「どの商品か」が分かるよう、名前・Amazon/楽天・仕様も持たせる
    rk_skus = {(r.sku or "").strip() for r in db.query(RakutenProduct).all()}
    for p in db.query(Product).all():
        has_amz = bool((p.asin or "").strip() or (p.fnsku or "").strip())
        rec = {"sku": p.sku, "asin": (p.asin or "").strip(),
               "fnsku": (p.fnsku or "").strip(),
               "name": p.name or "", "spec": p.spec or "",
               "channel": ("Amazon・楽天" if (has_amz and p.sku in rk_skus)
                           else "Amazon" if has_amz
                           else "楽天" if p.sku in rk_skus else "Amazon（未出品）")}
        if p.sku:
            by_sku[p.sku] = rec
        if (p.taotaro_sku_id or "").strip():
            by_skuid.setdefault(str(p.taotaro_sku_id).strip(), []).append(rec)
        no = _offer_no(p.buy_url or "")
        if no:
            by_offer.setdefault(no, []).append(rec)
    for r in db.query(RakutenProduct).all():
        rec = {"sku": r.sku, "asin": "", "fnsku": "",
               "name": r.name or "", "spec": r.supplier_spec or "", "channel": "楽天"}
        if r.sku and r.sku not in by_sku:
            by_sku[r.sku] = rec
        if (getattr(r, "taotaro_sku_id", "") or "").strip():
            by_skuid.setdefault(str(r.taotaro_sku_id).strip(), []).append(rec)
        no = _offer_no(r.buy_url or "")
        if no:
            by_offer.setdefault(no, []).append(rec)

    fill, skip = [], []
    for o in orders:
        # どの商品かを決める。管理番号が入っていればそれが確実。
        # 入っていなければ、覚えてあるタオタロウのSKU番号 → 商品番号の順に探す
        rec, how = None, ""
        if o["out_id"] and o["out_id"] in by_sku:
            rec, how = by_sku[o["out_id"]], "管理番号"
        if rec is None and o["sku_id"]:
            cand = by_skuid.get(o["sku_id"]) or []
            if len(cand) == 1:
                rec, how = cand[0], "タオタロウのSKU番号"
        if rec is None:
            cand = by_offer.get(_offer_no(o["url"])) or []
            if len(cand) == 1:
                rec, how = cand[0], "仕入先URL"
            elif len(cand) > 1:
                # 画面で選べるよう候補を返す（同じ商品が二重に入らないようSKUで重複を除く）
                seen, cands = set(), []
                for c in cand:
                    if c["sku"] and c["sku"] not in seen:
                        seen.add(c["sku"])
                        cands.append({k: c.get(k, "") for k in ("sku", "name", "spec", "channel")})
                skip.append({**o, "candidates": cands, "reason":
                             f"同じURLの商品が{len(cands)}件あり、どれか決められません"})
                continue
        if rec is None:
            skip.append({**o, "reason": "うちの商品と紐づきません"})
            continue

        # 空いている欄だけ埋める
        put = {}
        if not o["out_id"] and rec["sku"]:
            put["out_id"] = rec["sku"]
        if not o["asin"] and rec["asin"]:
            put["asin"] = rec["asin"]
        if not o["fnsku"] and rec["fnsku"]:
            put["fnsku"] = rec["fnsku"]
        if not put:
            continue

        want = []
        if not o["fnsku"] and not rec["fnsku"] and rec["asin"]:
            want.append("FNSKUがマスタに入っていません")
        if not o["asin"] and not rec["asin"]:
            want.append("まだAmazonに出品していません")
        fill.append({**o, "sku": rec["sku"], "matched_by": how,
                     "name": rec.get("name", ""), "channel": rec.get("channel", ""),
                     "put": put, "note": "／".join(want)})

    # 写真と仕様（色・サイズ）。会員画面の一覧には無いので、公式APIの一覧から足す
    # （配送依頼の画面と同じ一覧を使う。少しの間覚えているので速い）
    try:
        from app.services import restock_split as rs
        extra = {}
        for page in range(1, 6):
            d = rs._list_orders_cached(page)
            for x in d.get("items") or []:
                img = str(x.get("image") or "")
                if img.startswith("//"):
                    img = "https:" + img
                extra[x.get("oid")] = {
                    "image": img,
                    "props": " / ".join(str(v.get("value") or "")
                                        for v in (x.get("sku_props") or [])),
                }
            if not d.get("has_more_pages"):
                break
        for row in fill + skip:
            row.update(extra.get(row.get("oid"), {}))
    except Exception:
        pass

    return {"fill": fill, "skip": skip, "scanned": len(orders), "_by_sku": by_sku}


@router.get("/web/check")
def web_check(db: Session = Depends(get_db)):
    """貼ってあるクッキーで会員画面に入れるかを見るだけ。

    入れたら、もらい直した新しいクッキーを設定に書き戻す。
    つまりここを押すだけで期限が延びる。
    """
    from app.models.settings import OrderSettings
    from app.services import taotaro_web

    row = db.query(OrderSettings).first()
    try:
        with taotaro_web.logged_in(db, row) as sess:
            u = taotaro_web.who(sess)
    except taotaro_web.WebError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "uid": u.get("uid"), "uname": u.get("uname")}


@router.get("/ids/preview")
def ids_preview(db: Session = Depends(get_db)):
    """タオタロウの注文に入れるASIN・FNSKU・管理番号の下見。書き込まない。"""
    from app.models.settings import OrderSettings
    from app.services import taotaro_web

    row = db.query(OrderSettings).first()
    try:
        # logged_in が、使う直前にXSRF-TOKENをもらい直し、
        # 新しくなったクッキーを設定に書き戻す
        with taotaro_web.logged_in(db, row) as sess:
            plan = _id_plan(db, sess, _FILLABLE_STATES)
            plan.pop("_by_sku", None)
            return plan
    except taotaro_web.WebError as e:
        raise HTTPException(400, str(e))


class IdsApplyIn(BaseModel):
    # 下見で出た注文番号のうち、入れてよいもの。省くと下見の全部
    oids: Optional[List[int]] = None
    # 同じURLの商品が複数あって決められなかった注文に、画面で選んだSKU {注文番号: SKU}。
    # これを渡したときは、選んだ注文だけを入れる
    choices: Optional[dict] = None


@router.post("/ids/apply")
def ids_apply(body: IdsApplyIn = IdsApplyIn(), db: Session = Depends(get_db)):
    """下見の内容をタオタロウへ書き込む。空いている欄だけ埋める。"""
    from app.models.settings import OrderSettings
    from app.services import taotaro_web

    row = db.query(OrderSettings).first()
    only = set(body.oids or [])
    done, failed = [], []
    stopped = ""

    try:
        with taotaro_web.logged_in(db, row) as sess:
            plan = _id_plan(db, sess, _FILLABLE_STATES)
            items = plan["fill"]
            if body.choices:
                # 画面で選んだ商品で入れる。候補に無いSKUは受け付けない
                by_sku = plan.get("_by_sku") or {}
                items = []
                for o in plan["skip"]:
                    pick = str((body.choices or {}).get(str(o["oid"]))
                               or (body.choices or {}).get(o["oid"]) or "").strip()
                    if not pick:
                        continue
                    if pick not in {c["sku"] for c in (o.get("candidates") or [])}:
                        failed.append({"oid": o["oid"], "sku": pick, "put": {},
                                       "error": "候補に無い商品です"})
                        continue
                    rec = by_sku.get(pick) or {"sku": pick, "asin": "", "fnsku": ""}
                    put = {}
                    if not o["out_id"]:
                        put["out_id"] = pick
                    if not o["asin"] and rec.get("asin"):
                        put["asin"] = rec["asin"]
                    if not o["fnsku"] and rec.get("fnsku"):
                        put["fnsku"] = rec["fnsku"]
                    if put:
                        items.append({**o, "sku": pick, "put": put})

            for item in items:
                if only and item["oid"] not in only:
                    continue
                # 変えない欄は今の値をそのまま送り返す。送らなかった項目を
                # 向こうが空にしてしまうと、備考の「楽天用」などが消える
                try:
                    taotaro_web.update_order(
                        sess, item["oid"],
                        asin=item["put"].get("asin", item["asin"]),
                        fnsku=item["put"].get("fnsku", item["fnsku"]),
                        out_id=item["put"].get("out_id", item["out_id"]),
                        remark=item["remark"])
                except taotaro_web.WebError as e:
                    # 途中で止めない。1件の失敗で残り全部を落とすほうが困る
                    failed.append({"oid": item["oid"], "sku": item.get("sku"),
                                   "put": item["put"], "error": str(e)})
                    # ただしログイン切れだけは別。残りも全部同じ結果に
                    # なるので、そこで止めて理由を返す
                    if taotaro_web.is_login_error(e):
                        stopped = str(e)
                        break
                    continue
                done.append({"oid": item["oid"], "sku": item.get("sku"),
                             "put": item["put"]})
    except taotaro_web.WebError as e:
        raise HTTPException(400, str(e))

    # 管理番号が変わったので、配送依頼の確かめが古い一覧を使わないようにする
    if done:
        from app.services import restock_split as rs
        rs._orders_cache.clear()
    return {"done": done, "failed": failed, "stopped": stopped,
            "done_count": len(done), "failed_count": len(failed)}
