"""インボイス（仕入）の原価計算まわりの共通処理。

輸入許可書の申告欄ごとの関税率を使った税額計算は、楽天・Amazonで同じ仕組みなので
ここに集約する。元は rakuten.py にあったものを、ルータのスキーマに依存しない形へ
切り出した（計算内容は変更していない）。

明細の分類（classify_invoice_lines）もここに置く。1便に楽天商品・Amazon商品・
発送資材が混ざるため、どちらのマスタも見て振り分ける必要がある。
"""
import re


# 明細の行き先
KIND_RAKUTEN = "rakuten"      # 楽天商品 → 楽天マスタのcost_jpyへ
KIND_AMAZON = "amazon"        # Amazon商品 → Amazonマスタのcost_jpyへ
KIND_MATERIAL = "material"    # 発送資材 → 資材費として記録（商品原価に載せない）
KIND_UNKNOWN = "unknown"      # どのマスタにも無い → カバー率の警告対象


def classify_invoice_lines(db, items, url_key_fn=None) -> list[dict]:
    """インボイス明細を「楽天商品 / Amazon商品 / 発送資材 / 未登録」に振り分ける。

    1便に楽天とAmazonの商品が混載されるため、片方のマスタだけを見ると
    相手側の明細が按分対象から漏れ、その分の送料・税がどの原価にもならず消える。
    （実測: カバー率50%の便で送料・税の半分が行方不明になっていた）

    そのため両方のマスタを照合し、便の実額を全明細へ配り切れるようにする。

    items: sku / buy_url / asin を持つ明細オブジェクトのリスト
    url_key_fn: 仕入URLを正規化する関数（楽天の_url_keyを渡す。省略時はURL照合しない）
    戻り値: [{index, kind, product, source}] のリスト
    """
    from app.models.product import Product
    from app.models.rakuten_product import RakutenProduct

    # URL照合用に一度だけ全件読む（明細ごとにクエリを投げると便あたり数百回になる）
    rak_by_url = {}
    amz_by_url = {}
    if url_key_fn:
        for p in db.query(RakutenProduct).filter(
            RakutenProduct.is_active == True,  # noqa: E712
            RakutenProduct.buy_url != None,    # noqa: E711
        ).all():
            k = url_key_fn(p.buy_url)
            if k and k not in rak_by_url:
                rak_by_url[k] = p
        for p in db.query(Product).filter(
            Product.is_active == True,  # noqa: E712
            Product.buy_url != None,    # noqa: E711
        ).all():
            k = url_key_fn(p.buy_url)
            if k and k not in amz_by_url:
                amz_by_url[k] = p

    result = []
    for idx, item in enumerate(items):
        sku = (getattr(item, "sku", "") or "").strip()
        asin = (getattr(item, "asin", "") or "").strip()
        buy_url = getattr(item, "buy_url", "") or ""
        product = None
        kind = KIND_UNKNOWN

        # 1) 楽天マスタ: SKU一致
        if sku:
            p = db.query(RakutenProduct).filter(
                RakutenProduct.sku == sku,
                RakutenProduct.is_active == True,  # noqa: E712
            ).first()
            if p:
                product, kind = p, KIND_RAKUTEN

        # 2) Amazonマスタ: SKU一致 → ASIN一致
        if product is None and sku:
            p = db.query(Product).filter(
                Product.sku == sku,
                Product.is_active == True,  # noqa: E712
            ).first()
            if p:
                product, kind = p, KIND_AMAZON
        if product is None and asin:
            p = db.query(Product).filter(
                Product.asin == asin,
                Product.is_active == True,  # noqa: E712
            ).first()
            if p:
                product, kind = p, KIND_AMAZON

        # 3) 仕入URLで照合（SKUが伝票に入っていない便向け）
        if product is None and url_key_fn:
            k = url_key_fn(buy_url)
            if k:
                if k in rak_by_url:
                    product, kind = rak_by_url[k], KIND_RAKUTEN
                elif k in amz_by_url:
                    product, kind = amz_by_url[k], KIND_AMAZON

        # 資材フラグが立っていれば、どちらのマスタで見つかっても資材として扱う
        if product is not None and getattr(product, "is_material", False):
            kind = KIND_MATERIAL

        result.append({
            "index": idx,
            "kind": kind,
            "product": product,
            "source": KIND_RAKUTEN if kind == KIND_RAKUTEN else (
                KIND_AMAZON if kind == KIND_AMAZON else (
                    # 資材はどちらのマスタで見つかったかを保持する
                    KIND_RAKUTEN if isinstance(product, RakutenProduct) else KIND_AMAZON
                ) if product is not None else ""
            ),
        })
    return result


def calc_coverage(classified: list[dict], item_totals: list[float]) -> dict:
    """カバー率（母数完全性）を返す。

    どのマスタにも無い明細が混ざっている便では、その明細に按分された送料・税が
    どの原価にもならず消える。何割が原価に反映されたかを出して画面で警告する。
    """
    total = sum(item_totals) or 0.0
    covered = sum(
        item_totals[c["index"]] for c in classified if c["kind"] != KIND_UNKNOWN
    )
    unknown_rows = [c["index"] for c in classified if c["kind"] == KIND_UNKNOWN]
    rate = (covered / total * 100) if total > 0 else 100.0
    if rate >= 95:
        level = "ok"
    elif rate >= 80:
        level = "low"       # 使うが精度低め
    else:
        level = "critical"  # 代表原価から外すべき
    return {
        "coverage_rate": round(rate, 1),
        "covered_cny": round(covered, 2),
        "total_cny": round(total, 2),
        "unknown_count": len(unknown_rows),
        "unknown_indexes": unknown_rows,
        "level": level,
    }


def parse_box_sheets(wb) -> dict:
    """インボイスの箱シート（箱规・箱单）から、箱の計費重量と中身を読む。

    タオタロウのインボイスには箱ごとの実測重量・三辺と、どの箱に何が何個入ったかが
    入っている。これがあると送料を金額比ではなく重量で配れる。
    （金額比だと、安くて嵩張るものが送料をほとんど負担しない。実測で17倍の差が出た）

    戻り値: {
      "boxes": {箱番号: {"billing_weight", "actual_weight", "volume", "l","w","h"}},
      "contents": [{"box", "goods_id", "qty"}],
      "total_billing_weight": float,
      "available": bool,   # 配賦に使えるだけのデータが揃っているか
    }
    """
    empty = {"boxes": {}, "contents": [], "total_billing_weight": 0.0, "available": False}

    def find_sheet(*names):
        for n in names:
            if n in wb.sheetnames:
                return wb[n]
        return None

    ws_spec = find_sheet("箱规", "箱規", "箱規格")
    ws_list = find_sheet("箱单", "箱單", "packing list", "Packing List")
    if ws_list is None:
        return empty

    boxes: dict[int, dict] = {}
    if ws_spec is not None:
        for r in range(2, ws_spec.max_row + 1):
            bno = ws_spec.cell(row=r, column=1).value
            if bno is None:
                continue
            try:
                bno = int(bno)
            except (TypeError, ValueError):
                continue
            boxes[bno] = {
                "l": ws_spec.cell(row=r, column=3).value,
                "w": ws_spec.cell(row=r, column=4).value,
                "h": ws_spec.cell(row=r, column=5).value,
                "actual_weight": _f(ws_spec.cell(row=r, column=6).value),
                "volume": _f(ws_spec.cell(row=r, column=7).value),
                "billing_weight": 0.0,
            }

    # 箱单: 箱号は箱の先頭行にだけ入り、以降の行は空欄で同じ箱の続き
    contents: list[dict] = []
    cur_box = None
    for r in range(2, ws_list.max_row + 1):
        bno = ws_list.cell(row=r, column=1).value
        if bno is not None:
            try:
                cur_box = int(bno)
            except (TypeError, ValueError):
                continue
            bw = _f(ws_list.cell(row=r, column=7).value)  # 计费重量KG
            if cur_box not in boxes:
                boxes[cur_box] = {
                    "l": ws_list.cell(row=r, column=2).value,
                    "w": ws_list.cell(row=r, column=3).value,
                    "h": ws_list.cell(row=r, column=4).value,
                    "actual_weight": _f(ws_list.cell(row=r, column=5).value),
                    "volume": _f(ws_list.cell(row=r, column=6).value),
                    "billing_weight": 0.0,
                }
            if bw > 0:
                boxes[cur_box]["billing_weight"] = bw

        gid = ws_list.cell(row=r, column=9).value    # 商品ID
        qty = _f(ws_list.cell(row=r, column=10).value)
        if cur_box is not None and gid and qty > 0:
            contents.append({"box": cur_box, "goods_id": str(gid).strip(), "qty": qty})

    # 計費重量が無い箱は実重量で代用（それも無ければ配賦に使えない）
    for b in boxes.values():
        if not b.get("billing_weight"):
            b["billing_weight"] = b.get("actual_weight") or 0.0

    total_bw = sum(b["billing_weight"] for b in boxes.values())
    return {
        "boxes": boxes,
        "contents": contents,
        "total_billing_weight": round(total_bw, 3),
        "available": bool(contents) and total_bw > 0,
    }


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def calc_freight_by_weight(
    goods_ids: list[str],
    item_totals: list[float],
    box_data: dict,
    total_freight_cny: float,
) -> dict:
    """送料を重量ベースで配る（2段階）。

      STEP1  便の運賃 → 各箱へ（箱の計費重量比）
      STEP2  箱の運賃 → 中身へ（同じ箱の中は個数比）

    箱の中の商品ごとの重量は分からないので、箱の中だけは個数比で割る。
    箱をまたぐ配分が実測重量で決まるぶん、金額比よりはるかに実態に近い。

    goods_ids: 明細ごとの商品ID（箱单と突き合わせるキー）。空文字は箱不明。
    戻り値: {"alloc": {明細index: 送料}, "fallback": bool, "reason": str,
             "unmatched_indexes": [...]}
    """
    n = len(goods_ids)
    total_cny = sum(item_totals) or 0.0

    def by_money(reason: str, unmatched=None):
        alloc = {
            i: (total_freight_cny * item_totals[i] / total_cny) if total_cny > 0 else 0.0
            for i in range(n)
        }
        return {"alloc": alloc, "fallback": True, "reason": reason,
                "unmatched_indexes": unmatched or list(range(n))}

    if not box_data or not box_data.get("available"):
        return by_money("箱データが無いため金額比で按分")

    boxes = box_data["boxes"]
    contents = box_data["contents"]
    total_bw = box_data["total_billing_weight"]
    if total_bw <= 0:
        return by_money("計費重量が取れないため金額比で按分")

    # 明細index ↔ 商品ID
    idx_by_gid: dict[str, list[int]] = {}
    for i, g in enumerate(goods_ids):
        if g:
            idx_by_gid.setdefault(str(g).strip(), []).append(i)

    # 箱单にあるのに明細に無い／その逆があると配り切れない
    content_gids = {c["goods_id"] for c in contents}
    line_gids = set(idx_by_gid.keys())
    unmatched = [i for i, g in enumerate(goods_ids)
                 if not g or str(g).strip() not in content_gids]
    if unmatched:
        return by_money(
            f"箱の中身と紐づかない明細が{len(unmatched)}件あるため金額比で按分",
            unmatched,
        )

    # STEP1: 便の運賃 → 箱へ
    box_freight = {
        b: total_freight_cny * info["billing_weight"] / total_bw
        for b, info in boxes.items()
    }

    # STEP2: 箱の運賃 → 中身へ（個数比）
    qty_in_box: dict[int, float] = {}
    for c in contents:
        qty_in_box[c["box"]] = qty_in_box.get(c["box"], 0.0) + c["qty"]

    alloc: dict[int, float] = {i: 0.0 for i in range(n)}
    for c in contents:
        bq = qty_in_box.get(c["box"], 0.0)
        if bq <= 0:
            continue
        share = c["qty"] / bq
        amount = box_freight.get(c["box"], 0.0) * share
        targets = idx_by_gid.get(c["goods_id"], [])
        if not targets:
            continue
        # 同じ商品IDが明細に複数行ある場合は、その行の金額比で分ける
        tot = sum(item_totals[i] for i in targets) or 0.0
        for i in targets:
            w = (item_totals[i] / tot) if tot > 0 else (1.0 / len(targets))
            alloc[i] += amount * w

    return {"alloc": alloc, "fallback": False,
            "reason": "箱の計費重量で按分（箱内は個数比）", "unmatched_indexes": []}


CUSTOMS_FEE_SEA_JPY = 2000   # 船便の通関料（一律）。航空便は無し


def guess_shipping_method(wb) -> str:
    """インボイスのシート構成から配送方法を推測する。

    船便のインボイスには海運用の記入要点シートが付く。ただし確実ではないので
    あくまで画面の初期値として使い、ユーザーが確認・変更できるようにする。
    戻り値: "sea" | "air" | ""（不明）
    """
    names = " ".join(getattr(wb, "sheetnames", []) or [])
    if "海运" in names or "海運" in names:
        return "sea"
    if "空运" in names or "空運" in names or "航空" in names:
        return "air"
    return ""


def calc_customs_fee_alloc(
    item_totals: list[float],
    customs_fee_jpy: float,
) -> dict[int, float]:
    """通関料を明細へ按分する。

    通関料は便に対して一律でかかり、商品ごとの内訳が無い。
    重量とは無関係な手続き費用なので、金額比で配る。
    （送料は重量比だが、通関料は書類1件あたりの費用なので性質が違う）
    """
    total = sum(item_totals) or 0.0
    if total <= 0 or customs_fee_jpy <= 0:
        return {i: 0.0 for i in range(len(item_totals))}
    return {
        i: customs_fee_jpy * t / total
        for i, t in enumerate(item_totals)
    }


def verify_allocation(
    rows: list[dict],
    material_rows: list[dict],
    coverage: dict,
    total_freight_cny: float,
    import_tax_jpy: float,
    permit_columns: list | None = None,
    customs_fee_jpy: float = 0,
) -> dict:
    """配賦結果を検算する。総額が合っていても配り方が偏っていることはあるので、
    「配り切れたか」だけでなく「どこへ配ったか」も見る。

    NGが出たら保存を止める。誤った原価が最新版として出回るほうが危ないため。
    戻り値: {"ok": bool, "checks": [{name, ok, level, detail}, ...]}
    level: "error"=保存を止める / "warn"=保存はするが画面に出す
    """
    checks: list[dict] = []

    def add(name, ok, level, detail):
        checks.append({"name": name, "ok": bool(ok), "level": level, "detail": detail})

    all_rows = list(rows) + list(material_rows)
    covered_ratio = (coverage.get("coverage_rate") or 0) / 100.0

    # ① 送料の配賦: 配った送料 ＋ 未登録分 ＝ 便の運賃
    alloc_freight = sum(r.get("freight_alloc_cny") or 0 for r in all_rows)
    expected_freight = total_freight_cny * covered_ratio
    diff_f = abs(alloc_freight - expected_freight)
    add(
        "送料の配賦",
        diff_f <= max(1.0, total_freight_cny * 0.005),
        "error",
        f"配賦{round(alloc_freight, 2)}元 / 期待{round(expected_freight, 2)}元"
        f"（便の運賃{round(total_freight_cny, 2)}元 × カバー率{coverage.get('coverage_rate')}%）",
    )

    # ② 税額の配賦: 配った税 ＋ 未登録分 ＝ 便の税
    alloc_tax = sum(r.get("tax_alloc_jpy") or 0 for r in all_rows)
    expected_tax = import_tax_jpy * covered_ratio
    diff_t = abs(alloc_tax - expected_tax)
    add(
        "税額の配賦",
        diff_t <= max(10.0, import_tax_jpy * 0.005),
        "error",
        f"配賦¥{round(alloc_tax)} / 期待¥{round(expected_tax)}"
        f"（便の税¥{round(import_tax_jpy)} × カバー率{coverage.get('coverage_rate')}%）",
    )

    # ③ 通関料の配賦: 配った通関料 ＋ 未登録分 ＝ 便の通関料
    if customs_fee_jpy > 0:
        alloc_fee = sum(r.get("customs_fee_alloc_jpy") or 0 for r in all_rows)
        expected_fee = customs_fee_jpy * covered_ratio
        add(
            "通関料の配賦",
            abs(alloc_fee - expected_fee) <= max(5.0, customs_fee_jpy * 0.01),
            "error",
            f"配賦¥{round(alloc_fee)} / 期待¥{round(expected_fee)}"
            f"（便の通関料¥{round(customs_fee_jpy)} × カバー率{coverage.get('coverage_rate')}%）",
        )

    # ④ 許可書の実額と配賦額の一致（欄ごとの実額を使っている場合のみ）
    if permit_columns:
        cols = [c if isinstance(c, dict) else c.model_dump() for c in permit_columns]
        permit_total = sum(
            (c.get("duty_jpy") or 0)
            + (c.get("consumption_tax_jpy") or 0)
            + (c.get("local_tax_jpy") or 0)
            for c in cols
        )
        if permit_total > 0:
            add(
                "許可書との一致",
                abs(alloc_tax - permit_total * covered_ratio) <= max(10.0, permit_total * 0.01),
                "error",
                f"許可書の実額¥{round(permit_total)} × カバー率 vs 配賦¥{round(alloc_tax)}",
            )
            # 許可書に税額があるのに1円も配られていない（配り忘れ）
            add(
                "税の配り忘れ",
                alloc_tax > 0,
                "error",
                f"許可書に¥{round(permit_total)}あるが配賦額が0" if alloc_tax == 0 else "配賦済み",
            )

    # ④ 共通費の行き先: 販売数が無い行に原価が乗っていないか
    bad_units = [
        r for r in rows
        if (r.get("item") is not None and getattr(r["item"], "qty", 0) <= 0)
        and (r.get("cost_per_unit_jpy") or r.get("cost_jpy") or 0) > 0
    ]
    add(
        "共通費の行き先",
        not bad_units,
        "error",
        f"数量0なのに原価が付いた行が{len(bad_units)}件" if bad_units else "問題なし",
    )

    # ⑤ 二重計上: 同じSKUが商品行と資材行の両方に出ていないか
    row_skus = {getattr(r.get("item"), "sku", None) for r in rows}
    mat_skus = {getattr(r.get("item"), "sku", None) for r in material_rows}
    dup = {s for s in (row_skus & mat_skus) if s}
    add(
        "二重計上",
        not dup,
        "error",
        f"商品と資材の両方に出たSKU: {', '.join(sorted(dup))}" if dup else "問題なし",
    )

    # ⑥ カバー率（低い便は代表原価に使うべきでない）
    lvl = coverage.get("level")
    add(
        "カバー率",
        lvl == "ok",
        "error" if lvl == "critical" else "warn",
        f"{coverage.get('coverage_rate')}%（未登録{coverage.get('unknown_count')}件）",
    )

    # ⑦ 桁違いの検出: 1個原価が極端な行（入力ミス・単位混在の兆候）
    odd = [
        r for r in rows
        if (r.get("cost_per_unit_jpy") or r.get("cost_jpy") or 0) > 100000
    ]
    add(
        "桁違いの原価",
        not odd,
        "warn",
        f"1個10万円超の行が{len(odd)}件（単位の混在かも）" if odd else "問題なし",
    )

    has_error = any((not c["ok"]) and c["level"] == "error" for c in checks)
    return {"ok": not has_error, "checks": checks}


def parse_permit_columns(text: str) -> list[dict]:
    """輸入許可書から申告欄ごとの関税率・BPR按分係数・品名・税表番号を抽出する。"""
    columns = []
    for m in re.finditer(r"＜\s*(\d+)\s*欄＞", text):
        col_no = int(m.group(1))
        after = text[m.end():m.end() + 800]

        item_name = ""
        n = re.search(r"品名\s+(.+?)(?:\s+数量|$)", after)
        if n:
            item_name = n.group(1).strip()

        hs_code = ""
        n = re.search(r"税表番号\s+([0-9]+(?:\.[0-9]+)?)", after)
        if n:
            hs_code = n.group(1)

        cif_jpy = 0
        n = re.search(r"申告価格（ＣＩＦ）\s*[\\¥￥]?\s*([0-9,]+)", after)
        if n:
            cif_jpy = int(n.group(1).replace(",", ""))

        tariff_rate = 0.0
        tariff_rate_str = ""
        n = re.search(r"関税率\s+[A-Z]?\s*(\S+)", after)
        if n:
            rate_text = n.group(1).strip()
            tariff_rate_str = rate_text
            if rate_text.upper() == "FREE":
                tariff_rate = 0.0
            else:
                pct = re.search(r"([0-9]+(?:\.[0-9]+)?)%", rate_text)
                if pct:
                    tariff_rate = float(pct.group(1))
                else:
                    try:
                        tariff_rate = float(rate_text.replace("%", ""))
                    except ValueError:
                        pass

        duty_jpy = 0
        n = re.search(r"関税額\s*[\\¥￥]?\s*([0-9,]+)", after)
        if n:
            duty_jpy = int(n.group(1).replace(",", ""))

        bpr_coeff = 0.0
        n = re.search(r"ＢＰＲ按分係数\s+([0-9,]+(?:\.[0-9]+)?)", after)
        if n:
            bpr_coeff = float(n.group(1).replace(",", ""))

        # 欄ごとの内国消費税の実額。税率から再計算すると許可書と合わないため
        # （税関の評価額は運賃・保険込みで、商品代×為替とは一致しない）、
        # 紙に書いてある額をそのまま使う。
        consumption_tax_jpy = 0
        n = re.search(r"税率\s+7\.8%\s*\n?\s*税額\s*[\\¥￥]?\s*([0-9,]+)", after)
        if n:
            consumption_tax_jpy = int(n.group(1).replace(",", ""))

        local_tax_jpy = 0
        n = re.search(r"税率\s+22/78\s*\n?\s*税額\s*[\\¥￥]?\s*([0-9,]+)", after)
        if n:
            local_tax_jpy = int(n.group(1).replace(",", ""))

        columns.append({
            "col_no": col_no,
            "item_name": item_name,
            "hs_code": hs_code,
            "cif_jpy": cif_jpy,
            "tariff_rate": tariff_rate,
            "tariff_rate_str": tariff_rate_str,
            "duty_jpy": duty_jpy,
            "consumption_tax_jpy": consumption_tax_jpy,
            "local_tax_jpy": local_tax_jpy,
            "bpr_coeff": bpr_coeff,
        })
    return columns


def match_items_to_columns(
    items: list[dict], columns: list[dict]
) -> list[int | None]:
    """インボイス商品を許可書の申告欄にマッチングする。
    BPR按分係数 = 商品金額合計（元）なので、金額の組合せで欄を特定する。
    戻り値: 各商品に対応するcolumnsのインデックス（マッチしない場合None）。
    """
    if not columns:
        return [None] * len(items)
    if len(columns) == 1:
        return [0] * len(items)

    item_amounts = [round(it.get("total_price_cny", 0) or (it.get("qty", 0) * it.get("unit_price_cny", 0)), 2) for it in items]

    # 各欄のBPR按分係数（=その欄に属する商品のCNY合計）
    col_targets = [c["bpr_coeff"] for c in columns]

    # 2欄の場合: 各商品の金額を足し合わせて、どの欄のBPR按分係数に近いかで分ける
    # N欄の場合もグリーディに割り当て
    n = len(items)
    assignments: list[int | None] = [None] * n

    # 許容する誤差（元）。BPR按分係数は商品金額の単純合計なので、本来は誤差0で一致する。
    # 端数丸めのぶれだけを吸収する幅に留める。ここを広げると
    # 「たまたま合計が近い別の組合せ」を誤って選ぶ（例: 360.00の欄に315+45.35=360.35を割当）。
    _MATCH_DELTAS = [0.0, 0.01, -0.01, 0.02, -0.02, 0.05, -0.05, 0.1, -0.1]

    def _find_subset_for_target(indices: list[int], target: float) -> list[int] | None:
        """indicesの中からitem_amountsの合計がtargetに一致する部分集合を探す。

        誤差が小さい組合せを優先し、同じ誤差なら品目数が少ない組合せを選ぶ。
        （単品でぴったり一致するならそれが正解である可能性が高い）
        meet-in-the-middleで全組合せを評価するので、最初に見つかった順には依存しない。
        """
        k = len(indices)
        if k == 0:
            return None
        half = k // 2
        left_indices = indices[:half]
        right_indices = indices[half:]

        # 左半分: 合計金額 -> (品目数, mask)。同じ合計なら品目数が少ない方を残す
        left_sums: dict[float, tuple[int, int]] = {}
        for mask in range(1 << len(left_indices)):
            total = round(sum(item_amounts[left_indices[j]] for j in range(len(left_indices)) if mask & (1 << j)), 2)
            pc = bin(mask).count("1")
            cur = left_sums.get(total)
            if cur is None or pc < cur[0]:
                left_sums[total] = (pc, mask)

        best_key = None      # (誤差, 品目数)
        best_result = None
        for rmask in range(1 << len(right_indices)):
            rtotal = round(sum(item_amounts[right_indices[j]] for j in range(len(right_indices)) if rmask & (1 << j)), 2)
            rpc = bin(rmask).count("1")
            need = round(target - rtotal, 2)
            for delta in _MATCH_DELTAS:
                hit = left_sums.get(round(need + delta, 2))
                if hit is None:
                    continue
                lpc, lmask = hit
                if lpc + rpc == 0:
                    continue  # 空集合は無効
                key = (abs(delta), lpc + rpc)
                if best_key is None or key < best_key:
                    best_key = key
                    best_result = (
                        [left_indices[j] for j in range(len(left_indices)) if lmask & (1 << j)]
                        + [right_indices[j] for j in range(len(right_indices)) if rmask & (1 << j)]
                    )
            if best_key == (0.0, 1):
                break  # 単品ぴったり一致。これ以上良い候補はない
        return best_result

    remaining = list(range(n))
    # 欄を小さいBPR順に処理（小さい方がマッチしやすい）、最後の欄は残り全部
    sorted_cols = sorted(range(len(columns)), key=lambda ci: col_targets[ci])
    for idx, ci in enumerate(sorted_cols):
        if idx == len(sorted_cols) - 1:
            for i in remaining:
                assignments[i] = ci
            break
        matched = _find_subset_for_target(remaining, col_targets[ci])
        if matched is not None:
            for i in matched:
                assignments[i] = ci
                remaining.remove(i)
        # マッチしなかった場合はスキップして最後の欄に回す

    return assignments


def calc_tariff_tax(
    items_with_totals: list[tuple[int, float]],
    exchange_rate: float,
    domestic_freight: float,
    international_freight: float,
    permit_cols_by_index: dict[int, int | None],
    columns: list,
) -> dict[int, dict]:
    """税率別計算: 各商品インデックスに対する関税・消費税・地方消費税を返す。

    items_with_totals: [(item_index, item_total_cny), ...]
    permit_cols_by_index: {item_index: 手動指定した申告欄番号 or None}
    columns: PermitColumn（pydanticモデル or dict）のリスト
    戻り値: {item_index: {tariff_rate, duty_jpy, consumption_tax_jpy, local_tax_jpy, total_tax_jpy, col_no}}

    楽天・Amazonの両方から使う。ルータのスキーマに依存しないよう、
    必要な値だけをプレーンな引数で受け取る。
    """
    if not columns:
        return {}

    items_dicts = [
        {"total_price_cny": total, "permit_col": permit_cols_by_index.get(idx)}
        for idx, total in items_with_totals
    ]
    col_dicts = [c if isinstance(c, dict) else c.model_dump() for c in columns]

    # 手動指定がある商品はそれを使い、残りを自動マッチング
    assignments = [None] * len(items_dicts)
    for i, it in enumerate(items_dicts):
        if it.get("permit_col") is not None:
            col_idx = next((ci for ci, c in enumerate(col_dicts) if c["col_no"] == it["permit_col"]), None)
            if col_idx is not None:
                assignments[i] = col_idx

    unassigned = [i for i, a in enumerate(assignments) if a is None]
    if unassigned:
        auto_items = [items_dicts[i] for i in unassigned]
        # 手動割り当て分を差し引いたBPR按分係数で再計算
        adjusted_cols = []
        for ci, c in enumerate(col_dicts):
            manual_total = sum(items_dicts[i]["total_price_cny"] for i, a in enumerate(assignments) if a == ci)
            adjusted_cols.append({**c, "bpr_coeff": c["bpr_coeff"] - manual_total})
        auto_assignments = match_items_to_columns(auto_items, adjusted_cols)
        for j, ui in enumerate(unassigned):
            assignments[ui] = auto_assignments[j]

    # 欄ごとに、その欄へ割り当たった商品の金額合計を出す（実額を配る母数）
    col_item_totals: dict[int, float] = {}
    for i, (_, item_total) in enumerate(items_with_totals):
        ci = assignments[i] if assignments[i] is not None else 0
        col_item_totals[ci] = col_item_totals.get(ci, 0.0) + item_total

    result = {}
    for i, (item_idx, item_total) in enumerate(items_with_totals):
        col_idx = assignments[i]
        if col_idx is None:
            col_idx = 0
        col = col_dicts[col_idx]
        tariff_rate = col["tariff_rate"]

        # 許可書に書かれた実額を、その欄に属する商品の金額比で割り振る。
        # 税率を掛け直すと許可書と合わない（税関の評価額CIFは運賃・保険込みで、
        # 商品代×為替より大きい。実測で1.379倍・税額23.8%の乖離があった）。
        col_total = col_item_totals.get(col_idx, 0.0)
        share = (item_total / col_total) if col_total > 0 else 0

        col_duty = col.get("duty_jpy") or 0
        col_consumption = col.get("consumption_tax_jpy") or 0
        col_local = col.get("local_tax_jpy") or 0

        duty_jpy = round(col_duty * share)
        consumption_tax_jpy = round(col_consumption * share)
        local_tax_jpy = round(col_local * share)

        result[item_idx] = {
            "tariff_rate": tariff_rate,
            "tariff_rate_str": col.get("tariff_rate_str", f"{tariff_rate}%"),
            "duty_jpy": duty_jpy,
            "consumption_tax_jpy": consumption_tax_jpy,
            "local_tax_jpy": local_tax_jpy,
            "total_tax_jpy": duty_jpy + consumption_tax_jpy + local_tax_jpy,
            "col_no": col["col_no"],
            "hs_code": col.get("hs_code", ""),
        }
    return result
