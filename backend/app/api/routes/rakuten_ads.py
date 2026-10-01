"""楽天RPPの広告実績を取り込む。

楽天ウェブサービスに広告のAPIが無いので、RMSのパフォーマンスレポートから
落としたCSVを入れる。

日ごとに出せるのは「すべての広告」「キャンペーン」単位まで。商品別は
月ごと・全期間でしか出せない（画面にそう書かれている）。そのため、
  ・日別   … 毎日いくら使ったか
  ・商品別 … どの商品がクリックされ、どれだけ売れたか（月単位）
の2種類を別々に受け取る。

CSVの列名は実物を見ていないので、あり得る名前を順に試し、どの列を
何に使ったかを一緒に返す。取り違えたまま数字が出るほうが危ない。
"""
import io
import re
import zipfile
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.rakuten_ad import RakutenAdDaily, RakutenAdProduct
from app.services.rakuten_sales_import import read_upload_table, to_float

router = APIRouter(prefix="/rakuten/ads", tags=["rakuten-ads"])

# 列の当て方。左から順に試して、最初に見つかったものを使う
_COLS = {
    "day": ("日付", "日", "集計日", "配信日"),
    "period": ("年月", "月", "集計月"),
    "campaign": ("キャンペーン名", "キャンペーン"),
    "manage_number": ("商品管理番号", "商品管理番号（URL）"),
    "item_name": ("商品名",),
    "impressions": ("表示回数", "インプレッション数", "imp"),
    "clicks": ("クリック数(合計)", "クリック数（合計）", "クリック数"),
    "ctr": ("CTR", "クリック率"),
    "cost": ("実績額(合計)", "実績額（合計）", "実績額", "広告費"),
    "cpc": ("CPC実績(合計)", "CPC実績（合計）", "CPC実績", "CPC"),
    "sales": ("売上金額(合計12時間)", "売上金額（合計12時間）", "売上金額",
              "売上"),
    "orders": ("売上件数(合計12時間)", "売上件数（合計12時間）", "売上件数"),
    "cvr": ("CVR(合計12時間)", "CVR（合計12時間）", "CVR"),
    "roas": ("ROAS(合計12時間)", "ROAS（合計12時間）", "ROAS"),
    "bid": ("入札単価",),
}


def _find(headers: list, key: str) -> Optional[str]:
    for cand in _COLS[key]:
        if cand in headers:
            return cand
    # 「クリック数(合計)」のように括弧違いがあるので、ゆるくも探す
    base = _COLS[key][0]
    strip = lambda t: re.sub(r"[（）()％%\s]", "", str(t))
    for cand in _COLS[key]:
        plain = strip(cand)
        for h in headers:
            if strip(h) == plain:
                return h
    return None


def _num(v) -> float:
    """「41,828 円」「0.03 %」のような書き方から数だけ取る。"""
    if v is None:
        return 0.0
    s = str(v).replace(",", "").replace("円", "").replace("%", "")
    s = s.replace("％", "").strip()
    return to_float(s)


def _parse_day(v) -> Optional[date]:
    """「2026年09月01日」「2026/09/01」「2026-09-01」を日付にする。

    「2026年09月01日～2026年09月29日」のように期間が入っていることが
    あるので、先頭の日付を使う。
    """
    s = str(v or "").strip()
    if not s:
        return None
    s = re.split(r"[~〜]", s)[0].strip()
    m = re.search(r"(\d{4})\D+(\d{1,2})\D+(\d{1,2})", s)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


@router.post("/import")
async def import_ads(file: UploadFile = File(...),
                     period: Optional[str] = None,
                     db: Session = Depends(get_db)):
    """CSVを1つ受け取る。中身を見て、日別か商品別かを決めて入れる。"""
    raw = await file.read()
    name = file.filename or "report.csv"
    # 「全商品レポートダウンロード」はZIPで落ちてくる。中のCSVを取り出す
    if raw[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                inner = [n for n in z.namelist()
                         if n.lower().endswith((".csv", ".tsv"))]
                if not inner:
                    raise HTTPException(400, "ZIPの中にCSVがありませんでした")
                name = inner[0]
                raw = z.read(inner[0])
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(400, f"ZIPを開けませんでした: {e}")
    try:
        rows = read_upload_table(name, raw)
    except Exception as e:
        raise HTTPException(400, f"ファイルを読めませんでした: {e}")
    if not rows:
        raise HTTPException(400, "中身が空です")

    # 見出しの行を探す。RMSのCSVは上に説明が入っていることがある
    header_idx, headers = None, []
    for i, row in enumerate(rows[:30]):
        hs = [str(v).strip() if v is not None else "" for v in row]
        if any(h in ("実績額(合計)", "実績額", "クリック数", "クリック数(合計)")
               for h in hs):
            header_idx, headers = i, hs
            break
    if header_idx is None:
        raise HTTPException(
            400, "広告レポートの見出しが見つかりませんでした。"
                 "パフォーマンスレポートから落としたCSVか確認してください。")

    col = {k: _find(headers, k) for k in _COLS}
    is_product = bool(col["manage_number"])

    def val(row: dict, key: str):
        c = col.get(key)
        return row.get(c) if c else None

    dicts = []
    for row in rows[header_idx + 1:]:
        if not any(v not in (None, "") for v in row):
            continue
        d = {}
        for idx, h in enumerate(headers):
            if h:
                d[h] = row[idx] if idx < len(row) else None
        dicts.append(d)

    saved, skipped = 0, 0
    if is_product:
        p = (period or "").strip()
        if not re.fullmatch(r"\d{4}-\d{2}", p):
            # CSVの日付から月を取る
            for d in dicts:
                dd = _parse_day(val(d, "day"))
                if dd:
                    p = dd.strftime("%Y-%m")
                    break
        if not re.fullmatch(r"\d{4}-\d{2}", p or ""):
            raise HTTPException(400, "対象月が決められませんでした。月を指定してください。")
        for d in dicts:
            mn = str(val(d, "manage_number") or "").strip()
            if not mn:
                skipped += 1
                continue
            row = (db.query(RakutenAdProduct)
                   .filter(RakutenAdProduct.period == p,
                           RakutenAdProduct.manage_number == mn).first())
            if not row:
                row = RakutenAdProduct(period=p, manage_number=mn)
                db.add(row)
            row.item_name = str(val(d, "item_name") or "")[:500]
            row.impressions = int(_num(val(d, "impressions")))
            row.clicks = int(_num(val(d, "clicks")))
            row.ctr = _num(val(d, "ctr"))
            row.cost = _num(val(d, "cost"))
            row.cpc = _num(val(d, "cpc"))
            row.sales = _num(val(d, "sales"))
            row.orders = int(_num(val(d, "orders")))
            row.cvr = _num(val(d, "cvr"))
            row.roas = _num(val(d, "roas"))
            row.bid = _num(val(d, "bid"))
            saved += 1
    else:
        for d in dicts:
            day = _parse_day(val(d, "day"))
            if not day:
                skipped += 1
                continue
            camp = str(val(d, "campaign") or "").strip()
            row = (db.query(RakutenAdDaily)
                   .filter(RakutenAdDaily.day == day,
                           RakutenAdDaily.campaign == camp).first())
            if not row:
                row = RakutenAdDaily(day=day, campaign=camp)
                db.add(row)
            row.clicks = int(_num(val(d, "clicks")))
            row.cost = _num(val(d, "cost"))
            row.cpc = _num(val(d, "cpc"))
            row.sales = _num(val(d, "sales"))
            row.orders = int(_num(val(d, "orders")))
            row.roas = _num(val(d, "roas"))
            saved += 1
    db.commit()

    used = {k: v for k, v in col.items() if v}
    missing = [k for k, v in col.items()
               if not v and k in (("manage_number", "clicks", "cost")
                                  if is_product else ("day", "clicks", "cost"))]
    return {"kind": "product" if is_product else "daily",
            "saved": saved, "skipped": skipped,
            "used_columns": used, "missing": missing,
            "headers": headers[:30]}


@router.get("/daily")
def list_daily(date_from: Optional[str] = None, date_to: Optional[str] = None,
               db: Session = Depends(get_db)):
    """日ごとの消化。月の合計も添える。"""
    q = db.query(RakutenAdDaily)
    if date_from:
        q = q.filter(RakutenAdDaily.day >= date_from[:10])
    if date_to:
        q = q.filter(RakutenAdDaily.day <= date_to[:10])
    rows = q.order_by(RakutenAdDaily.day.desc()).all()

    days, months = [], {}
    for r in rows:
        d = {"day": r.day.isoformat(), "campaign": r.campaign or "",
             "clicks": r.clicks or 0, "cost": round(r.cost or 0),
             "sales": round(r.sales or 0), "orders": r.orders or 0,
             "cpc": round(r.cpc or 0, 1), "roas": round(r.roas or 0, 1)}
        days.append(d)
        m = months.setdefault(r.day.strftime("%Y-%m"),
                              {"month": r.day.strftime("%Y-%m"),
                               "clicks": 0, "cost": 0, "sales": 0, "orders": 0})
        m["clicks"] += d["clicks"]
        m["cost"] += d["cost"]
        m["sales"] += d["sales"]
        m["orders"] += d["orders"]
    for m in months.values():
        m["roas"] = round(m["sales"] / m["cost"] * 100, 1) if m["cost"] else 0
    return {"days": days,
            "months": [months[k] for k in sorted(months, reverse=True)]}


@router.get("/products")
def list_products(period: Optional[str] = None, db: Session = Depends(get_db)):
    """商品ごとの実績。月を指定する。"""
    q = db.query(RakutenAdProduct)
    if period:
        q = q.filter(RakutenAdProduct.period == period)
    rows = q.order_by(RakutenAdProduct.cost.desc()).all()
    items = [{
        "period": r.period, "manage_number": r.manage_number,
        "item_name": r.item_name or "",
        "impressions": r.impressions or 0, "clicks": r.clicks or 0,
        "ctr": round(r.ctr or 0, 2), "cost": round(r.cost or 0),
        "cpc": round(r.cpc or 0, 1), "sales": round(r.sales or 0),
        "orders": r.orders or 0, "cvr": round(r.cvr or 0, 2),
        "roas": round(r.roas or 0, 1), "bid": round(r.bid or 0, 1),
    } for r in rows]
    periods = sorted({p[0] for p in db.query(RakutenAdProduct.period).distinct()},
                     reverse=True)
    return {"items": items, "periods": periods,
            "total": {
                "clicks": sum(i["clicks"] for i in items),
                "cost": sum(i["cost"] for i in items),
                "sales": sum(i["sales"] for i in items),
                "orders": sum(i["orders"] for i in items),
            }}

# ============================================================
# 画面が使っているAPIの中身をそのまま受け取る
# ============================================================
# RMSの広告画面（SPA）は /rpp/api/reports/search で実績をJSONで受け取って
# いる。CSVを作らせて落とす必要はなく、同じJSONをそのまま入れれば足りる。
# 拡張機能がそれを送ってくる。

def _manage_number(row: dict) -> str:
    """商品管理番号。itemUrlがそのまま番号のことも、URLのこともある。"""
    for key in ("itemUrl", "itemPageUrl"):
        v = str(row.get(key) or "").strip()
        if not v:
            continue
        m = re.search(r"item\.rakuten\.co\.jp/[^/]+/([^/?#]+)", v)
        if m:
            return m.group(1)
        if "/" not in v:
            return v
    return ""


@router.post("/import-json")
def import_json(payload: dict, db: Session = Depends(get_db)):
    """拡張機能が拾ったJSONを入れる。kindは product か daily。"""
    kind = str(payload.get("kind") or "product")
    rows = payload.get("rows") or []
    period = str(payload.get("period") or "").strip()
    if kind == "product" and not re.fullmatch(r"\d{4}-\d{2}", period):
        raise HTTPException(400, "対象月が決められませんでした")

    saved, skipped = 0, 0
    for r in rows:
        if not isinstance(r, dict):
            skipped += 1
            continue
        total = r.get("totalUsersReport") or {}
        t12 = total.get("type12H") or {}

        clicks = int(_num(total.get("clicksValid")))
        cost = _num(total.get("adSalesBeforeDiscount"))
        cpc = _num(total.get("cpc"))
        sales = _num(t12.get("gms"))
        orders = int(_num(t12.get("cv")))
        cvr = _num(t12.get("cvr"))
        roas = _num(t12.get("roas"))

        if kind == "product":
            mn = _manage_number(r)
            if not mn:
                skipped += 1
                continue
            row = (db.query(RakutenAdProduct)
                   .filter(RakutenAdProduct.period == period,
                           RakutenAdProduct.manage_number == mn).first())
            if not row:
                row = RakutenAdProduct(period=period, manage_number=mn)
                db.add(row)
            row.item_name = str(r.get("itemName") or "")[:500]
            row.clicks = clicks
            row.ctr = _num(r.get("ctr"))
            row.cost = cost
            row.cpc = cpc
            row.sales = sales
            row.orders = orders
            row.cvr = cvr
            row.roas = roas
            row.bid = _num(r.get("itemCpc") or r.get("clickPrice"))
            saved += 1
        else:
            day = _parse_day(r.get("effectDate"))
            if not day:
                skipped += 1
                continue
            camp = str(r.get("campaignName") or "").strip()
            row = (db.query(RakutenAdDaily)
                   .filter(RakutenAdDaily.day == day,
                           RakutenAdDaily.campaign == camp).first())
            if not row:
                row = RakutenAdDaily(day=day, campaign=camp)
                db.add(row)
            row.clicks = clicks
            row.cost = cost
            row.cpc = cpc
            row.sales = sales
            row.orders = orders
            row.roas = roas
            saved += 1
    db.commit()
    return {"kind": kind, "saved": saved, "skipped": skipped,
            "used_columns": {}, "missing": []}
