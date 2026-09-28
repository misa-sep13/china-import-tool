"""メルカリShopsの注文CSVを、ラベル発行ツールの形に変換する。

これまではスプレッドシートのマクロでやっていたが、使えなくなった。

メルカリShopsのCSVは、注文1件につき2行ある。
  ・order   行 … 注文番号・購入者名・金額
  ・product 行 … 商品名・個数・送付先の住所と電話
送付先は product 行にしか入っていないので、order_id で突き合わせて1行にする。

文字コードは Shift_JIS（cp932）。出す側もラベル発行ツールに合わせて
Shift_JIS にする。
"""
import csv
import io
import re

# ラベル発行ツールが読む列。並びを変えるとあちらが読めなくなる
HEADERS = [
    "注文番号",
    "送付先郵便番号1", "送付先郵便番号2",
    "送付先住所都道府県", "送付先住所郡市区", "送付先住所それ以降の住所",
    "送付先姓", "送付先名",
    "商品名", "商品管理番号", "システム連携用番号", "個数",
    "送付先電話番号1", "送付先電話番号2", "送付先電話番号3",
]

# 全角スペースでも半角でも姓名を分ける
_SPACE = re.compile(r"[\s　]+")


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp932", "shift_jis", "utf-8"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    raise ValueError("文字コードを判別できませんでした")


def split_name(full: str) -> tuple[str, str]:
    """「小林 美芳」を姓と名に分ける。区切りが無ければ全部を姓に入れる。"""
    parts = [p for p in _SPACE.split((full or "").strip()) if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], "".join(parts[1:])


def split_zip(code: str) -> tuple[str, str]:
    """「709-0802」を 709 と 0802 に分ける。ハイフンが無くても切る。"""
    digits = re.sub(r"\D", "", code or "")
    if len(digits) >= 7:
        return digits[:3], digits[3:7]
    return digits, ""


def split_phone(number: str) -> tuple[str, str, str]:
    """電話番号を3つに分ける。

    ラベル発行ツールが3欄に分かれているため。携帯は3-4-4、東京・大阪は
    2-4-4、それ以外の固定電話は3-3-4 で切る。桁が合わないものは
    分けずに先頭の欄へ入れる（欠けるより、まとまって見えたほうがよい）。
    """
    d = re.sub(r"\D", "", number or "")
    if len(d) == 11:
        return d[:3], d[3:7], d[7:]
    if len(d) == 10:
        if d.startswith(("03", "04", "06")):
            return d[:2], d[2:6], d[6:]
        return d[:3], d[3:6], d[6:]
    return d, "", ""


def convert(raw: bytes) -> tuple[list[dict], list[str]]:
    """変換した行と、気づいたことの一覧を返す。

    落ちた行は黙って捨てない。どの注文が出せなかったかを画面に出す。
    """
    text = _decode(raw)
    reader = csv.DictReader(io.StringIO(text))
    orders: dict[str, dict] = {}
    products: dict[str, list[dict]] = {}
    for row in reader:
        kind = (row.get("type") or "").strip()
        oid = (row.get("order_id") or "").strip()
        if not oid:
            continue
        if kind == "order":
            orders[oid] = row
        elif kind == "product":
            products.setdefault(oid, []).append(row)

    out, notes = [], []
    for oid, order in orders.items():
        items = products.get(oid) or []
        if not items:
            notes.append(f"{oid}：商品の行が無いため出せませんでした")
            continue
        for item in items:
            zip1, zip2 = split_zip(item.get("shipping_postal_code"))
            last, first = split_name(
                item.get("shipping_name") or order.get("buyer_name") or "")
            tel1, tel2, tel3 = split_phone(item.get("shipping_phone_number"))
            rest = " ".join(x for x in [
                (item.get("shipping_address_1") or "").strip(),
                (item.get("shipping_address_2") or "").strip(),
            ] if x)
            out.append({
                "注文番号": oid,
                "送付先郵便番号1": zip1,
                "送付先郵便番号2": zip2,
                "送付先住所都道府県": (item.get("shipping_state") or "").strip(),
                "送付先住所郡市区": (item.get("shipping_city") or "").strip(),
                "送付先住所それ以降の住所": rest,
                "送付先姓": last,
                "送付先名": first,
                "商品名": (item.get("product_name") or "").strip(),
                "商品管理番号": (item.get("original_product_id") or "").strip(),
                "システム連携用番号": (item.get("variant_id") or "").strip(),
                "個数": (item.get("quantity") or "1").strip(),
                "送付先電話番号1": tel1,
                "送付先電話番号2": tel2,
                "送付先電話番号3": tel3,
            })
            if not zip1:
                notes.append(f"{oid}：郵便番号が読めませんでした")
            if not tel1:
                notes.append(f"{oid}：電話番号がありません")
            if not first:
                notes.append(f"{oid}：お名前を姓と名に分けられませんでした（{last}）")
    return out, notes


def to_csv(rows: list[dict]) -> bytes:
    """ラベル発行ツールが読む Shift_JIS のCSVにする。"""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=HEADERS, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue().encode("cp932", errors="replace")
