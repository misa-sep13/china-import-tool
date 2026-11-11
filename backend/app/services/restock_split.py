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


# タオタロウの注文一覧は1ページ取るのに数秒かかる。配送依頼の画面では
# チェックを付け外すたびに確かめるので、毎回取り直すと1回50秒かかっていた。
# 少しの間だけ覚えておく（倉庫に着いた・便に入ったはすぐには変わらない）
_ORDERS_TTL = 90
_orders_cache = {}


def _list_orders_cached(page: int) -> dict:
    import time
    hit = _orders_cache.get(page)
    if hit and time.time() - hit[0] < _ORDERS_TTL:
        return hit[1]
    d = taotaro.list_orders(page=page, limit=100)
    _orders_cache[page] = (time.time(), d)
    return d


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
        d = _list_orders_cached(page)
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


def _norm(s: str) -> str:
    """仕様の文字を比べられる形にする（空白・区切り・全角半角の差を消す）。"""
    import unicodedata
    t = unicodedata.normalize("NFKC", str(s or ""))
    for ch in " 　、,，;；/／":
        t = t.replace(ch, "")
    return t.lower()


# まだ倉庫に届いていない注文の状態（買付中〜ショップから出荷、オプション作業中、不良対応中）
_ON_THE_WAY = {1, 2, 3, 7, 9}


def set_tables(db):
    """セット組みを見るための表。

    戻り値: (全商品{SKU:商品}, 付属品{SKU:商品},
             本体→[(付属品SKU, 本体1個あたりの数)], 注文→付属品SKU を返す関数)
    付属品の注文は管理番号で見分け、違っていれば仕入先ページ＋仕様の文字で当てる。
    """
    import json
    from app.services.accessories import _offer

    prods = {p.sku: p for p in
             db.query(Product).filter(Product.is_active == True).all()}
    comps = {s: p for s, p in prods.items() if p.is_component}
    comps_of = {}
    for p in prods.values():
        if p.is_component:
            continue
        try:
            lst = json.loads(p.purchase_components or "[]") or []
        except (ValueError, TypeError):
            lst = []
        for x in lst if isinstance(lst, list) else []:
            c = str((x or {}).get("sku") or "").strip()
            if c in comps:
                comps_of.setdefault(p.sku, []).append((c, int(x.get("qty") or 1)))

    # 楽天のマスタにある管理番号も「正しい番号」として扱う
    rk_skus = set()
    for r in db.query(RakutenProduct).filter(RakutenProduct.is_active == True).all():
        for k in (r.sku, r.rakuten_sku_id):
            if (k or "").strip():
                rk_skus.add(k.strip())

    def as_component(o):
        sku = str(o.get("out_id") or "").strip()
        if sku in comps:
            return sku
        # 管理番号がどちらかのマスタの本体を指していれば、それを信じる。
        # 同じフックを別の商品（y141）でも使っていることがあり、
        # 仕様だけで当てると他の商品の注文を付属品に数えてしまう
        if sku and "（" not in sku and (sku in prods or sku in rk_skus):
            return None
        offer = _offer(o.get("url") or "")
        vals = _norm("".join(str(v.get("value") or "") for v in (o.get("sku_props") or [])))
        for c in comps.values():
            spec = _norm(c.spec)
            if offer and _offer(c.buy_url) == offer and spec and vals and (
                    spec in vals or vals in spec):
                return c.sku
        return None

    return prods, comps, comps_of, as_component


def make_classifier(db):
    """注文1件が「何か」を、商品マスタだけで見分ける関数を作る（タオタロウは呼ばない）。

    戻り値: (全商品, 付属品, 本体→付属品, classify)
    classify(o) → (kind, key, 画面用の情報)
      kind: body（付属品のある本体）/ component / other / unknown（マスタに無い）/ noid（管理番号なし）
    """
    prods, comps, comps_of, as_component = set_tables(db)
    # 楽天の商品も同じ倉庫に入る。Amazonのマスタに無いからといって
    # 「マスタに無い」と出すと、楽天の商品が全部そう見えてしまう
    rk = {}
    for r in db.query(RakutenProduct).filter(RakutenProduct.is_active == True).all():
        for k in (r.sku, r.rakuten_sku_id):
            k = (k or "").strip()
            if k:
                rk.setdefault(k, r)
    # 付属品 → 使う本体（画面で本体のすぐ下に並べるため）
    parent_of = {}
    for b, lst in comps_of.items():
        for c, _q in lst:
            parent_of.setdefault(c, b)
    # 楽天の付属品。楽天の商品マスタの「発注用付属品」に挙がっているSKU
    # （石鹸置き y141_1 のフック y141 ×2 など）。Amazonの付属品しか見ていなかったので、
    # 楽天の付属品が本体と同じ名前の商品として出ていた
    import json as _json
    rk_qty = {}
    for r in {id(v): v for v in rk.values()}.values():
        try:
            lst = _json.loads(r.purchase_components or "[]") or []
        except (ValueError, TypeError):
            lst = []
        for x in lst if isinstance(lst, list) else []:
            c = str((x or {}).get("sku") or "").strip()
            if c and c != r.sku and c in rk:
                parent_of.setdefault(c, r.sku)
                rk_qty.setdefault(c, int(x.get("qty") or 1))

    def channel(sku):
        p = prods.get(sku)
        amz = bool(p and ((p.fnsku or "").strip() or (p.asin or "").strip()
                          or p.is_component))
        rak = sku in rk
        return "both" if (amz and rak) else "amazon" if amz else "rakuten" if rak else ""

    def classify(o):
        c = as_component(o)
        sku = str(o.get("out_id") or "").strip()
        # 「y127（付属品）」はツールが付けた付属品の名前（本体SKU＋（付属品））
        base = sku.split("（")[0].strip() if "（付属品）" in sku else ""
        if c:
            kind, key = "component", c
        elif base and (base in prods or base in rk):
            kind, key = "component", sku
            parent_of.setdefault(sku, base)
        elif sku in rk and sku in rk_qty:
            kind, key = "component", sku       # 楽天の付属品（y141 など）
        elif sku in prods:
            kind, key = ("body" if sku in comps_of else "other"), sku
        elif sku in rk:
            kind, key = "other", sku
        elif not sku:
            # 管理番号の無い注文（梱包資材・管理番号を入れ忘れた注文）。
            # Amazon・楽天のどちらの画面にも混ぜず、「すべて」の最後にまとめる
            kind, key = "noid", ""
        else:
            kind, key = "unknown", sku
        p = prods.get(key)
        name = (p.name if p else "") or ((rk[key].name if key in rk else "") or "")
        if kind == "component" and parent_of.get(key) and (not name or key in rk_qty):
            pp = prods.get(parent_of[key]) or rk.get(parent_of[key])
            pname = (pp.name if pp else "") or parent_of[key]
            q = rk_qty.get(key)
            qs = f"×{q}" if q else ""
            if not name or name.strip() == pname.strip():
                # 楽天の付属品は本体と同じ名前で登録されていることがある（y141）。
                # そのままだと本体と見分けられないので「付属品×2（本体）」と出す
                name = f"付属品{qs}（{pname}）"
            else:
                # 自分の名前がある付属品（ストラップなど）は名前を残し、何の付属品かを足す
                name = f"{name}（{parent_of[key]} の付属品{qs}）"
        info = {
            "kind": kind, "sku": key, "name": name,
            "channel": (channel(key) if kind != "component"
                        else channel(parent_of.get(key, key)) or "amazon"),
            # 付属品は本体のすぐ下に並べる
            "group": parent_of.get(key, key) if kind == "component" else key,
        }
        return kind, key, info

    return prods, comps, comps_of, classify


def classify_orders(db, orders: list) -> dict:
    """画面が持っている注文を、商品マスタだけで見分けて返す（すぐ返る）。"""
    _p, _c, _co, classify = make_classifier(db)
    out = {}
    for o in orders or []:
        if isinstance(o, dict) and o.get("oid") is not None:
            out[o["oid"]] = classify(o)[2]
    return out


def send_check(db, oids: list, pages: int = 5) -> dict:
    """配送依頼に入れようとしている注文を確かめる。

    タオタロウの配送依頼は、セット組みの付属品が入っていなくても通る。
    選んだ本体に対して付属品が足りなければ止め、倉庫にある付属品の注文が
    あれば「これを足せば揃う」と返す。届いていなければその注文を出す。

    戻り値:
      kinds    {oid: {kind: body/component/other/unknown, sku, name}}（画面の札）
      problems [{level: error/warn, text, add_oids}]
    """
    prods, comps, comps_of, classify = make_classifier(db)
    picked = {int(x) for x in (oids or [])}

    kinds, arrived, coming = {}, [], {}
    for page in range(1, max(1, pages) + 1):
        d = _list_orders_cached(page)
        for o in d.get("items") or []:
            if o.get("sid"):
                continue                       # もう便に入っている
            st = o.get("state")
            kind, key, info = classify(o)
            if st == 4:
                kinds[o.get("oid")] = info
                arrived.append((o, kind, key))
            elif st in _ON_THE_WAY and kind == "component":
                coming.setdefault(key, []).append(
                    f"注文{o.get('oid')} {int(o.get('quantity') or 0)}個（{o.get('state_label') or ''}）")
        if not d.get("has_more_pages"):
            break

    problems = []
    sel = [(o, k, s) for (o, k, s) in arrived if o.get("oid") in picked]
    body_pcs, have = {}, {}
    for o, k, s in sel:
        q = int(o.get("quantity") or 0)
        if k == "body":
            body_pcs[s] = body_pcs.get(s, 0) + q
        elif k == "component":
            have[s] = have.get(s, 0) + q
        elif k == "unknown":
            problems.append({"level": "warn", "add_oids": [], "text":
                f"注文{o.get('oid')}：管理番号「{s}」が商品マスタにありません。"
                "打ち間違いでないか確かめてください（取り込みで照合できません）"})
        elif k == "noid":
            problems.append({"level": "warn", "add_oids": [], "text":
                f"注文{o.get('oid')}：管理番号が空です。梱包資材などならそのままで構いません。"
                "商品なら、下の「ASIN・FNSKU・管理番号をタオタロウに入れる」で入れてください"})

    need, users = {}, {}
    for b, pcs in body_pcs.items():
        for c, q in comps_of.get(b, []):
            need[c] = need.get(c, 0) + pcs * q
            users.setdefault(c, []).append(f"{b} {pcs}個×{q}")
    for c, n in need.items():
        h = have.get(c, 0)
        if h >= n:
            continue
        cp = comps[c]
        label = f"{c}（{cp.name or cp.spec or ''}）"
        # 倉庫に着いていて、まだ選んでいない付属品の注文で埋められるか
        add, more = [], h
        for o, k, s in arrived:
            if k == "component" and s == c and o.get("oid") not in picked and more < n:
                add.append(o.get("oid"))
                more += int(o.get("quantity") or 0)
        text = (f"セット組みの付属品 {label} が足りません：{h}/{n}個"
                f"（使う本体：{'、'.join(users[c])}）。")
        if more >= n:
            text += "倉庫にある付属品の注文を一緒に入れれば揃います。"
        else:
            arriving = coming.get(c) or []
            text += ("まだ届いていない注文：" + "、".join(arriving) + "。届くまで本体は送らないでください"
                     if arriving else "届く予定の注文もありません。発注漏れの可能性があります")
        problems.append({"level": "error", "add_oids": add if more >= n else add,
                         "text": text})

    # 付属品だけ選んで、使う本体が入っていない
    for c, h in have.items():
        if c in need:
            continue
        parents = [b for b, lst in comps_of.items() if any(x[0] == c for x in lst)]
        problems.append({"level": "warn", "add_oids": [], "text":
            f"付属品 {c} が{h}個入っていますが、使う本体（{'・'.join(parents) or '不明'}）が入っていません。"
            "本体を先に送った分の追加なら、そのままで構いません"})

    return {"kinds": kinds, "problems": problems}


def set_check(db, pages: int = 5) -> list:
    """倉庫にある本体に対して、セット組みの付属品が揃っているかを見る。

    本体と付属品は別の注文で発注するので、届く日がずれる。
    タオタロウの配送依頼は、付属品が入っていなくても通ってしまう
    （a017_1 のフックが遅れて、本体だけ送りそうになった）。
    配送依頼をかける前に、足りないものと、まだ届いていない注文を出す。

    付属品の注文は管理番号で見分ける。管理番号が違う・空の古い注文もあるので、
    付属品の仕入先ページと仕様の文字でも当てる。
    """
    prods, comps, comps_of, as_component = set_tables(db)
    if not comps_of:
        return []

    body_pcs, have, coming, wrongs = {}, {}, {}, {}
    for page in range(1, max(1, pages) + 1):
        d = _list_orders_cached(page)
        for o in d.get("items") or []:
            if o.get("sid"):
                continue                       # もう便に入っている
            st = o.get("state")
            qty = int(o.get("quantity") or 0)
            if qty <= 0:
                continue
            c = as_component(o)
            if c:
                oid_sku = str(o.get("out_id") or "").strip()
                if oid_sku and oid_sku != c:
                    wrongs.setdefault(c, []).append(
                        {"oid": o.get("oid"), "out_id": oid_sku, "qty": qty})
                if st == 4:
                    have[c] = have.get(c, 0) + qty
                elif st in _ON_THE_WAY:
                    coming.setdefault(c, []).append({
                        "oid": o.get("oid"), "qty": qty,
                        "state": o.get("state_label") or "",
                        "out_id": str(o.get("out_id") or "").strip(),
                    })
                continue
            sku = str(o.get("out_id") or "").strip()
            if st == 4 and sku in comps_of:
                body_pcs[sku] = body_pcs.get(sku, 0) + qty
        if not d.get("has_more_pages"):
            break

    # 付属品ごとに、倉庫にある本体ぶんの必要数を足し上げる
    # （a019_bag のように4つの本体が同じ付属品を使うことがある）
    need, parents = {}, {}
    for b, pcs in body_pcs.items():
        for c, q in comps_of.get(b, []):
            need[c] = need.get(c, 0) + pcs * q
            parents.setdefault(c, []).append({"sku": b, "pieces": pcs, "per": q})

    out = []
    for c, n in need.items():
        h = have.get(c, 0)
        if h >= n:
            continue
        cp = comps[c]
        wrong = wrongs.get(c, [])
        out.append({
            "component": c, "name": cp.name or "", "spec": cp.spec or "",
            "need": n, "have": h, "short": n - h,
            "parents": parents.get(c, []),
            "coming": coming.get(c, []),
            # 管理番号が付属品のSKUと違う注文。取り込みや照合で迷子になるので知らせる
            "wrong_out_id": wrong,
        })
    return out


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
