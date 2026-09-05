"""競合リサーチシートから、出品に使う中身を取り出す。

シートはHTML1枚がまるごとJSONで保存されている（amazon_research_sheets）。
そこには出品に必要なものがほぼ揃っているのに、これまで商品登録には
一切渡っていなかった。ここがその橋渡し。

シート側のキー名（lenA・titleParent など）はHTMLの都合で決まっていて
変えられないので、読み替えはすべてこのファイルに閉じ込める。
"""
import json
import re

# シートの状態は日本語のラベルではなくキーで入っている
# （リサーチ中は空文字、以降 adopted / ordered / imaged / listed / rejected）。
# 「採用」以降が商品登録の対象。仕入れを決めた時点で登録の準備を始められる
# よう、採用は発注より前の工程に置いてある。
ADOPTED_STATUS = {"adopted", "ordered", "imaged", "listed"}

STATUS_LABEL = {
    "": "リサーチ中", "active": "リサーチ中", "adopted": "採用",
    "ordered": "発注済み", "imaged": "画像依頼済み",
    "listed": "商品登録済み", "rejected": "ボツ",
}

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
                     "axis_label": axis_label, "axis1": axis_value,
                     "axis_label_value": axis_value})

    bullets = [b.strip() for b in
               re.split(r"\n{2,}|\n", research.get("listingBullets") or "")
               if b.strip()]

    return {
        "research_id": research.get("id"),
        "research_title": research.get("title") or "",
        "status_on_sheet": research.get("status") or "",
        "status_label": STATUS_LABEL.get(research.get("status") or "", ""),

        "title": (research.get("titleParent") or "").strip(),
        "keywords": (research.get("kwDraft") or "").strip(),
        "bullets": bullets[:5],
        "description": (research.get("listingBullets") or "").strip(),
        "diff_points": (research.get("diffPoints") or "").strip(),

        # 候補商品の行ID。調査メモ（商品仕様・レビュー）を引くのに使う
        "rows": [{"row_id": r.get("id"), "asin": (r.get("asin") or "").strip()}
                 for r in (research.get("rows") or []) if isinstance(r, dict)],

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
        # 商品タイトルの下書きを作るための材料
        "sug_groups": research.get("sugGroups") or [],
        "rival_names": [r.get("competitor") for r in (research.get("rows") or [])
                        if isinstance(r, dict) and r.get("competitor")],
    }


def candidates(sheet: dict, all_status: bool = False) -> list:
    """出品の候補になるリサーチを、シートの並び順で返す。

    既定では「採用」以降だけ。まだ何も入っていない雛形
    （競合ASINが無いもの）は、状態にかかわらず外す。
    """
    st = sheet.get("settings") or {}
    out = []
    for r in sheet.get("researches") or []:
        if not isinstance(r, dict):
            continue
        status = r.get("status") or ""
        if all_status:
            if status == "rejected":
                continue
        elif status not in ADOPTED_STATUS:
            continue
        e = extract(r, st)
        if not e["rival_asin"]:
            continue
        out.append(e)
    return out


# ---------- 商品タイトルの下書き ----------
#
# 命名ルール:
#   ブランド名 ／ メインキーワード ／ 関連ワード（SEOが高く成約のある語）
#   ／ サイズ・数量・色   … 計65字程度
#   推したい点があれば、ブランド名の次に【立てて入る】のように挟む
#
# 語はサジェスト（実際に検索されている言い回し）を先に、次に競合タイトルで
# 多く使われている語。リサーチシートの「③ 商品タイトル」と同じ考え方。

TITLE_TARGET = 65
TITLE_LIMIT = 130

# 入れても意味の薄い語
_TITLE_SKIP = {"の", "と", "や", "用", "付", "入", "個", "枚", "セット",
               "for", "with", "and", "the", "a", "an"}


def _words(text: str) -> list:
    """日本語まじりの文を、タイトルに使える単位に切る。

    形態素解析は入れない（Renderに辞書を置きたくない）。
    区切り文字と、全角スペースで割るだけで実用上足りている。
    """
    t = re.sub(r"[【】\[\]（）()「」『』/／,、|｜]", " ", text or "")
    return [w for w in re.split(r"[\s　]+", t) if len(w) >= 2]


def rival_brands(src: dict, specs: list = None) -> set:
    """競合のブランド名を集める。自社タイトルに混ぜると商標の問題になる。

    商品仕様の「ブランド名 | ○○」が最も確かなので、それを最優先で使う。
    取り込んでいない商品は、競合タイトルの先頭語を疑う（先頭にブランドを
    置くセラーが多いが、一般語のこともあるので他の競合にも出る語は残す）。
    """
    out = set()
    for sp in (specs or []):
        for m in re.finditer(r"^(?:ブランド名?|メーカー名?)\s*[|｜:：]\s*(.+)$",
                             sp or "", re.M):
            v = m.group(1).strip()
            if v:
                out.add(v)
                out.update(_words(v))

    rivals = [r for r in (src.get("rival_names") or []) if r]
    if len(rivals) >= 2:
        heads = [(_words(r) or [""])[0] for r in rivals]
        for i, h in enumerate(heads):
            # 他の競合にも出てくる語は一般語とみなして残す
            if h and sum(1 for r in rivals if h in r) == 1:
                out.add(h)
    elif rivals:
        h = (_words(rivals[0]) or [""])[0]
        # 英字だけの先頭語はブランドのことが多い
        if h and re.fullmatch(r"[A-Za-z][A-Za-z0-9\-']*", h):
            out.add(h)
    return {b for b in out if b}


def build_title(src: dict, brand: str = "", push: str = "",
                specs: list = None) -> str:
    """1リサーチぶんの材料から、親タイトルの下書きを作る。

    競合のブランド名は入れない（商標の問題になるため）。
    """
    seeds = [g.get("seed") for g in (src.get("sug_groups") or []) if g.get("seed")]
    rivals = [r for r in (src.get("rival_names") or []) if r]
    ng_brands = rival_brands(src, specs)

    main = seeds[0] if seeds else ""
    if not main and rivals:
        cand = [w for w in _words(rivals[0])
                if len(w) >= 3 and w not in ng_brands]
        main = cand[0] if cand else ""
    if not main:
        return ""

    seen = {main}
    rel = []

    def add(w):
        w = (w or "").strip()
        if not w or w in seen or w.lower() in _TITLE_SKIP:
            return
        if w in ng_brands:          # 競合のブランド名は入れない
            return
        seen.add(w)
        rel.append(w)

    for g in (src.get("sug_groups") or []):
        for v in (g.get("list") or []):
            for w in _words(v):
                if w != main:
                    add(w)

    freq = {}
    for r in rivals:
        for w in set(_words(r)):
            freq[w] = freq.get(w, 0) + 1
    for w in sorted(freq, key=lambda x: -freq[x]):
        add(w)

    # サイズは三辺から。色や個数（バリエーションの情報）は親には入れない。
    # 親は選択肢をまとめる器で、色は子ごとに末尾へ付けるため
    tail = []
    if src.get("len_a") and src.get("len_b"):
        tail.append(f"{_trim_num(src['len_a'])}×{_trim_num(src['len_b'])}cm")

    head = " ".join([x for x in [brand,
                                 f"【{push.strip()}】" if push.strip() else "",
                                 main] if x])
    tail_s = " ".join(tail)
    out = head
    for w in rel:
        nxt = out + " " + w
        if len(nxt + ((" " + tail_s) if tail_s else "")) > TITLE_TARGET:
            break
        out = nxt
    if tail_s:
        out += " " + tail_s
    return out[:TITLE_LIMIT].strip()


def _trim_num(v) -> str:
    f = float(v)
    return str(int(f)) if f == int(f) else str(f)
