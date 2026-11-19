"""請求書から金額を読み取る。

月次管理表の販管費は、見込みではなく請求書の実額で出したい。
いま読めるのは2つ。

  楽天の店舗別内訳書 … 決済手数料・システム利用料・出店料・広告・ポイント
  ヤマトの請求書     … 送料

楽天の内訳書でいちばん大事なのは「精算対象期間」。3月分のシステム利用料が
6月発行の請求書に載っていて、品目ごとに遅れ方も違う（楽天ペイ利用料は2か月、
広告は3か月）。請求書が届いた月で計上すると、まるごとずれる。
期間の月に入れるのが発生ベース。
"""
import re
from typing import Optional

# 内訳書の末尾に楽天自身が書いている分類
#   10：出店料 20：システム利用料 30：決済手数料 40：販売促進費
#   50：教育研修費 60：物流費 99：その他
AGG_LABEL = {
    "10": "出店料", "20": "システム利用料", "30": "決済手数料",
    "40": "販売促進費", "50": "教育研修費", "60": "物流費", "99": "その他",
}

# 損益計算書で並べたい費目。集約科目だけでは広告とポイントが同じ40・20に
# 混ざるので、品目名でも見る
BUCKETS = (
    ("ad",          ("広告", "ｱﾌｨﾘｴｲﾄ", "アフィリエイト", "RPP", "CPA")),
    ("promo",       ("ﾎﾟｲﾝﾄ付与料", "ポイント付与料", "ｸｰﾎﾟﾝ", "クーポン")),
    ("payment_fee", ("楽天ﾍﾟｲ利用料", "楽天ペイ利用料", "決済")),
    ("system_fee",  ("ｼｽﾃﾑ利用料", "システム利用料", "安全性")),
    ("rent",        ("出店料",)),
)
BUCKET_LABEL = {
    "ad": "広告宣伝費", "promo": "販売促進費", "payment_fee": "決済手数料",
    "system_fee": "システム利用料", "rent": "出店料", "other": "その他",
    "shipping": "荷造運賃",
}

_WAVE = "[~〜～]"
# 20 ｼｽﾃﾑ利用料_PC 2026/3/1～2026/3/31 \27,741
_LINE = re.compile(
    r"^(\d{2})\s+(\S.*?)\s+"
    r"(?:(\d{4}/\d{1,2}/\d{1,2}))?\s*" + _WAVE + r"\s*"
    r"(\d{4}/\d{1,2}/\d{1,2})\s+(-?[\d,]+)\s*$")


def _ymd(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    y, m, d = s.split("/")
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


def _bucket(agg: str, name: str) -> str:
    for key, words in BUCKETS:
        if any(w in name for w in words):
            return key
    if agg == "10":
        return "rent"
    if agg == "30":
        return "payment_fee"
    if agg == "20":
        return "system_fee"
    if agg == "40":
        return "ad"
    return "other"


def parse_rakuten_rms(text: str) -> dict:
    """楽天の店舗別内訳書。請求額の明細を1行ずつ返す。

    支払額（売上の入金）は費用ではないので取らない。請求額の節だけを見る。
    """
    shop_id = shop = doc_no = issued = ""
    m = re.search(r"店舗別ID[：:]\s*(\d+)", text)
    if m:
        shop_id = m.group(1)
    m = re.search(r"店舗名\s*[：:]\s*(\S+)", text)
    if m:
        shop = m.group(1)
    m = re.search(r"店舗別内訳書No[：:]\s*([\d-]+)", text)
    if m:
        doc_no = m.group(1)
    m = re.search(r"発行日[：:]\s*(\d{4}/\d{1,2}/\d{1,2})", text)
    if m:
        issued = _ymd(m.group(1))

    # 「再掲」と書かれていれば、前の月に同じ内容が出ている。
    # 二重に数えないよう印を付けて返す（入れるかどうかは呼ぶ側が決める）
    restated = "再掲" in text

    items, in_bill = [], False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("■"):
            in_bill = "請求額" in line
            continue
        if not in_bill:
            continue
        # 金額の頭の円記号。PDFから取るとバックスラッシュになる
        m = _LINE.match(line.replace("\\", "").replace("￥", "").replace("¥", ""))
        if not m:
            continue
        agg, name, start, end, amount = m.groups()
        try:
            yen = int(amount.replace(",", ""))
        except ValueError:
            continue
        start_d, end_d = _ymd(start), _ymd(end)
        items.append({
            "agg": agg, "agg_label": AGG_LABEL.get(agg, ""),
            "name": name.strip(),
            "period_start": start_d, "period_end": end_d,
            # 計上月は精算対象期間。またぐ場合は終了日の月に寄せる
            "ym": (end_d or start_d or "")[:7] or None,
            "amount": yen,
            "bucket": _bucket(agg, name),
        })
    return {
        "kind": "rakuten_rms", "shop_id": shop_id, "shop": shop,
        "doc_no": doc_no, "issued": issued, "restated": restated,
        "items": items, "total": sum(x["amount"] for x in items),
    }


def parse_yamato(text: str) -> dict:
    """ヤマトのWeb請求書。合計だけを取る。

    品目のラベルが画像で、文字としては拾えない。数字は拾えるので、
    税抜＋消費税＝税込 が成り立つ組を探す。請求書は必ずこの形なので、
    組が1つに決まれば合計と断定できる（2か月ぶんで確かめた）。
    """
    nums = sorted({int(x.replace(",", "")) for x in re.findall(r"\d[\d,]{2,}", text)})
    hits = {(a, b, c) for a in nums for b in nums for c in nums
            if a > 1000 and b > c > 0 and b != a and b + c == a}
    no = ""
    m = re.search(r"No\.\s*(\d+)", text)
    if m:
        no = m.group(1)
    if len(hits) != 1:
        return {"kind": "yamato", "doc_no": no, "ok": False,
                "candidates": sorted(hits, key=lambda x: -x[0])[:5]}
    total, net, tax = hits.pop()
    return {"kind": "yamato", "doc_no": no, "ok": True,
            "total": total, "amount": net, "tax": tax,
            "bucket": "shipping"}
