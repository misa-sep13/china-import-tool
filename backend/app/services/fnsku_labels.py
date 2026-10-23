"""商品ラベル（FNSKUのバーコード）のPDFを作る。

セラーセントラルで納品プランを作らないとラベルが落とせなかったが、
FNSKUはSKUごとに決まっている番号で、どの納品プランに載せるかとは
関係ない。商品マスタにFNSKUと商品名があるので、ここで作ってしまえば
代行会社へ早く渡せる。

用紙はA4 24面（66.0×33.9mm、エーワン28362など）。
"""
import io
from typing import List

from reportlab.graphics.barcode import code128
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

# A4 24面（3列×8段）の実寸。エーワン28362の値に合わせてある
COLS, ROWS = 3, 8
LABEL_W, LABEL_H = 66.0 * mm, 33.9 * mm
MARGIN_L, MARGIN_T = 6.0 * mm, 10.5 * mm
GAP_X = 2.0 * mm

_FONT = "HeiseiKakuGo-W5"
_font_ready = False


def _ensure_font() -> None:
    global _font_ready
    if not _font_ready:
        pdfmetrics.registerFont(UnicodeCIDFont(_FONT))
        _font_ready = True


def _fit(text: str, size: float, width: float) -> str:
    """幅に収まるところまで切って、切ったら…を付ける。"""
    if pdfmetrics.stringWidth(text, _FONT, size) <= width:
        return text
    while text and pdfmetrics.stringWidth(text + "…", _FONT, size) > width:
        text = text[:-1]
    return text + "…"


def _draw(c: canvas.Canvas, x: float, y: float, item: dict) -> None:
    """1枚ぶん。左下を(x, y)として描く。"""
    pad = 2.5 * mm
    inner = LABEL_W - pad * 2
    fnsku = (item.get("fnsku") or "").strip()

    # バーコード。高さを抑えて、下に文字を入れる場所を残す
    bar = code128.Code128(fnsku, barHeight=11 * mm, barWidth=0.38 * mm,
                          humanReadable=False, quiet=False)
    bw = bar.width
    if bw > inner:        # 長いFNSKUでもはみ出さないよう細くする
        bar = code128.Code128(fnsku, barHeight=11 * mm,
                              barWidth=0.38 * mm * inner / bw,
                              humanReadable=False, quiet=False)
        bw = bar.width
    bar.drawOn(c, x + (LABEL_W - bw) / 2, y + LABEL_H - pad - 11 * mm)

    ty = y + LABEL_H - pad - 11 * mm - 3.2 * mm
    c.setFont(_FONT, 7.5)
    c.drawCentredString(x + LABEL_W / 2, ty, fnsku)

    ty -= 3.4 * mm
    c.setFont(_FONT, 6.5)
    c.drawCentredString(x + LABEL_W / 2, ty,
                        _fit(item.get("sku") or "", 6.5, inner))

    ty -= 3.2 * mm
    c.setFont(_FONT, 6)
    c.drawCentredString(x + LABEL_W / 2, ty,
                        _fit(item.get("name") or "", 6, inner))

    ty -= 3.0 * mm
    c.drawCentredString(x + LABEL_W / 2, ty, "新品")


def build_pdf(items: List[dict], skip: int = 0) -> bytes:
    """items: [{"fnsku", "sku", "name", "qty"}, ...]

    qtyの枚数だけ並べる。skipは使いかけのシートの残り枚数から
    刷り始めるための空け数。
    """
    _ensure_font()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)

    slot = skip % (COLS * ROWS)
    if skip and slot == 0:
        slot = 0
    drawn_any = False
    for it in items:
        if not (it.get("fnsku") or "").strip():
            continue
        for _ in range(int(it.get("qty") or 0)):
            if slot >= COLS * ROWS:
                c.showPage()
                slot = 0
            col, row = slot % COLS, slot // COLS
            x = MARGIN_L + col * (LABEL_W + GAP_X)
            y = A4[1] - MARGIN_T - (row + 1) * LABEL_H
            _draw(c, x, y, it)
            drawn_any = True
            slot += 1

    if not drawn_any:
        raise ValueError("刷るラベルがありません")
    c.showPage()
    c.save()
    return buf.getvalue()
