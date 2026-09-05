"""競合リサーチシートから、出品に使う中身を取り出す。

シートはHTML1枚がまるごとJSONで保存されている（amazon_research_sheets）。
そこには出品に必要なものがほぼ揃っているのに、これまで商品登録には
一切渡っていなかった。ここがその橋渡し。

シート側のキー名（lenA・titleParent など）はHTMLの都合で決まっていて
変えられないので、読み替えはすべてこのファイルに閉じ込める。
"""
import json
import re

# シートの「状態」で除くもの。
# 状態は運用上ほとんど使われていない（2026-09 時点で19件すべて空）ので、
# 「発注済みだけ出す」のような絞り込みにすると何も出てこない。
# ここでは「ボツ」だけ外し、あとは画面側で絞れるようにしてある。
EXCLUDED_STATUS = {"ボツ"}

# タオタロウの代行オプション（1販売単位あたり・元）。
# sheet.html の AGENT_OPTIONS と同じ値。片方だけ直すとずれるので注意
AGENT_OPTIONS = {
    "商品ラベル貼り付け作業": 0.50,
    "全量開封検品": 0.50,
    "アパレル検品・詳細検品": 2.00,
    "写真撮影": 3.00,
    "ネームタグ取り外し": 1.00,
    "ネームタグ縫い付け": 2.00,
    "品質表示タグ取り外し": 1.00,
    "品質表示タグ取り付け": 2.00,
    "OPP袋入替（タオタロウ支給）": 0.50,
    "OPP袋入替（自社支給）": 0.30,
    "おもちゃ年齢表示シール": 0.20,
    "Made in Chinaシール": 0.20,
    "説明書・チラシのセット": 0.50,
    "圧縮梱包": 4.00,
}

VOLUME_DIVISOR = 6000.0     # 容積重量の除数。sheet.html と同じ


def _f(v, default=0.0):
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _i(v):
    try:
        if v is None or v == "":
            return None
        return int(float(v))
    except (TypeError, ValueError):
        return None


def load_sheet(raw) -> dict:
    """保存されている文字列を辞書にする。壊れていても落とさない。"""
    if not raw:
        return {"researches": [], "settings": {}}
    try:
        d = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return {"researches": [], "settings": {}}
    if not isinstance(d, dict):
        return {"researches": [], "settings": {}}
    d.setdefault("researches", [])
    d.setdefault("settings", {})
    return d


def cost_of(row: dict, st: dict) -> dict:
    """1行ぶんの原価と粗利。sheet.html の計算と同じ式にしてある。

    三辺・実重量・1688単価・為替のどれかが欠けていると出せない。
    その場合は missing に理由を入れて返す（誤った粗利率を出さないため）。
    """
    rate = _f(st.get("exchangeRate")) * (1 + _f(st.get("rateAdjust")) / 100)

    la, lb, lc = _f(row.get("lenA")), _f(row.get("lenB")), _f(row.get("lenC"))
    wt = _f(row.get("weight"))
    goods = sum(_f(p.get("price")) * _f(p.get("qty"), 1)
                for p in (row.get("parts") or []) if isinstance(p, dict))

    missing = []
    if not (la and lb and lc):
        missing.append("三辺")
    if not wt:
        missing.append("実重量")
    if not goods:
        missing.append("1688単価")
    if rate <= 0:
        missing.append("為替")
    if missing:
        return {"missing": missing}

    pack = (_f(row.get("packFactor"), _f(st.get("packFactor"), 100))
            or _f(st.get("packFactor"), 100)) / 100 or 1
    vol_kg = la * lb * lc / VOLUME_DIVISOR * pack
    billable = max(vol_kg, wt)

    opts = sum(AGENT_OPTIONS.get(o, 0) for o in (row.get("optSel") or []))
    opts += _f(row.get("extra"))

    china = (goods + _f(st.get("chinaFixed"), 0.5) + opts) * rate
    ship = billable * _f(st.get("shipYuan"), 7.5) * rate
    cost = (china + ship) * (1 + _f(st.get("tariffRate"), 15.4) / 100)

    price, fee = _f(row.get("price")), _f(row.get("fee"))
    profit = price - cost - fee if price > 0 else None
    return {
        "missing": [],
        "billable_kg": round(billable, 3),
        "cost_jpy": round(cost, 1),
        "profit_jpy": round(profit, 1) if profit is not None else None,
        "profit_rate": (round(profit / price * 100, 1)
                        if profit is not None and price > 0 else None),
    }


def split_child_name(name: str) -> tuple:
    """子の名前「カラー ブラック」を（軸の名前, 値）に分ける。

    シートは自由入力の1本の文字列なので、最初の空白で切って当たりを付ける。
    外れることもあるので、画面で直せるようにしてある。
    """
    s = (name or "").strip()
    if not s:
        return ("", "")
    parts = re.split(r"[\s　:：/／]+", s, maxsplit=1)
    if len(parts) == 2:
        return (parts[0].strip(), parts[1].strip())
    return ("", s)


def pick_row(research: dict) -> dict:
    """出品の元にする候補商品。ふつうは1件だけだが、複数あれば先頭。

    三辺や重量が入っている行を優先する（空の行が先頭にあることがある）。
    """
    rows = [r for r in (research.get("rows") or []) if isinstance(r, dict)]
    if not rows:
        return {}
    filled = [r for r in rows
              if _f(r.get("weight")) and _f(r.get("lenA"))]
    return (filled or rows)[0]


def extract(research: dict, settings: dict) -> dict:
    """1リサーチぶんの出品内容を組み立てる。

    ここで返す形が、そのまま画面と amazon_listings の中身になる。
    """
    row = pick_row(research)
    c = cost_of(row, settings) if row else {"missing": ["候補商品なし"]}

    kids = []
    for i, ch in enumerate(research.get("titleChildren") or []):
        if not isinstance(ch, dict):
            continue
        title = (ch.get("title") or "").strip()
        if not title:
            continue
        axis_label, axis_value = split_child_name(ch.get("name"))
        kids.append({"sort_order": i, "title": title,
                     "axis_label": axis_label, "axis1": axis_value})

    bullets = [b.strip() for b in
               re.split(r"\n{2,}|\n", research.get("listingBullets") or "")
               if b.strip()]

    return {
        "research_id": research.get("id"),
        "research_title": research.get("title") or "",
        "status_on_sheet": research.get("status") or "",

        "title": (research.get("titleParent") or "").strip(),
        "keywords": (research.get("kwDraft") or "").strip(),
        "bullets": bullets[:5],
        "description": (research.get("listingBullets") or "").strip(),
        "diff_points": (research.get("diffPoints") or "").strip(),

        "rival_asin": (row.get("asin") or "").strip(),
        "rival_image": row.get("image") or "",
        "rival_name": row.get("competitor") or "",
        "len_a": _f(row.get("lenA")) or None,
        "len_b": _f(row.get("lenB")) or None,
        "len_c": _f(row.get("lenC")) or None,
        "weight": _f(row.get("weight")) or None,
        "price": _i(row.get("price")),
        "fee": _i(row.get("fee")),
        "monthly_sales": _i(row.get("monthlySales")),
        "review_count": _i(row.get("reviewCount")),
        "review_rate": _f(row.get("reviewRate")) or None,
        "urls_1688": [u for u in (row.get("urls1688") or []) if u],

        "cost_jpy": c.get("cost_jpy"),
        "profit_jpy": c.get("profit_jpy"),
        "profit_rate": c.get("profit_rate"),
        "cost_missing": c.get("missing") or [],

        "children": kids,
    }


def candidates(sheet: dict) -> list:
    """出品の候補になるリサーチを、シートの並び順で返す。

    ボツと、まだ何も入っていない雛形（競合ASINが無いもの）は外す。
    """
    st = sheet.get("settings") or {}
    out = []
    for r in sheet.get("researches") or []:
        if not isinstance(r, dict):
            continue
        if (r.get("status") or "") in EXCLUDED_STATUS:
            continue
        e = extract(r, st)
        if not e["rival_asin"]:
            continue
        out.append(e)
    return out
