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
