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
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.rakuten_ad import (RakutenAdDaily, RakutenAdItemDaily,
                                   RakutenAdProduct)
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


def _parse_span(v) -> tuple:
    """「2026年09月01日～2026年09月30日」から開始と終了を読む。"""
    s = str(v or "").strip()
    parts = re.split(r"[~〜]", s)
    a = _parse_day(parts[0]) if parts else None
    b = _parse_day(parts[1]) if len(parts) > 1 else a
    return a, (b or a)


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
        # 集計期間が1日だけのレポートは「商品ごと・その日」として入れる。
        # 月のつもりの表を1日の数字で上書きしないよう、入れ先を分ける
        one_day = None
        for d in dicts:
            a, b = _parse_span(val(d, "day"))
            if a and b and a == b:
                one_day = a
            break

        if one_day:
            for d in dicts:
                mn = str(val(d, "manage_number") or "").strip()
                if not mn:
                    skipped += 1
                    continue
                row = (db.query(RakutenAdItemDaily)
                       .filter(RakutenAdItemDaily.day == one_day,
                               RakutenAdItemDaily.manage_number == mn).first())
                if not row:
                    row = RakutenAdItemDaily(day=one_day, manage_number=mn)
                    db.add(row)
                row.item_name = str(val(d, "item_name") or "")[:500]
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
            db.commit()
            return {"kind": "item-daily", "day": one_day.isoformat(),
                    "saved": saved, "skipped": skipped,
                    "used_columns": {k: v for k, v in col.items() if v},
                    "missing": []}

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


# ============================================================
# 見張りと提案
# ============================================================
# 楽天RPPは、ある日いきなり特定の商品でクリックが跳ね、気づかないうちに
# 広告費だけが出ていることがある。商品ごと・日ごとの数字を貯めてあるので、
# 「いつもの何倍か」で見つける。
#
# あわせて、広告費をかけてよい上限（損益分岐）を商品マスタから出し、
# 上げる・下げる・止めるの目安を添える。数字を変えるのは人がやる。

from statistics import median

from app.models.rakuten_product import RakutenProduct
from app.models.rakuten_settings import RakutenSettings

_SPIKE_RATIO = 2.0        # いつもの何倍で暴走とみなすか
_SPIKE_MIN_CLICKS = 30    # これ未満のクリックは誤差として扱う
_SPIKE_MIN_COST = 2000    # これ未満の増えかたは放っておく
_WASTE_MIN_COST = 300     # 在庫切れでこれ以上使っていたら知らせる
_JUDGE_MIN_COST = 2000    # 上げ下げを言うのに足りる広告費


def _profit_per_order(p, commission_rate: float) -> Optional[float]:
    """1個売れたときに残る粗利（円）。マスタが埋まっていないとNone。"""
    if not p or not p.selling_price or not p.cost_jpy:
        return None
    price = float(p.selling_price)
    fee = price * (commission_rate or 0.09)
    ship = float(p.shipping_fee or 0)
    return price - float(p.cost_jpy) - fee - ship


def _breakeven_roas(p, commission_rate: float) -> Optional[float]:
    """広告費がちょうど粗利と釣り合うROAS（%）。これを下回ると赤字。"""
    profit = _profit_per_order(p, commission_rate)
    if profit is None or profit <= 0 or not p.selling_price:
        return None
    rate = profit / float(p.selling_price)
    return round(100 / rate, 1)


@router.get("/watch")
def watch(db: Session = Depends(get_db)):
    """クリックの暴走と、広告費の上げ下げの目安を出す。"""
    st = db.query(RakutenSettings).first()
    commission_rate = st.commission_rate if st and st.commission_rate else 0.09

    products = {p.sku: p for p in db.query(RakutenProduct).all() if p.sku}

    # 広告の商品管理番号は親（y104）、マスタは色違い（y104_gold / y104_gray）に
    # 分かれていることがある。色違いを束ねて見ないと、在庫があるのに
    # 「在庫が無いのに広告が出ている」と言ってしまう
    family: dict = {}
    for p in products.values():
        base = str(p.sku or "").split("_")[0]
        if base:
            family.setdefault(base, []).append(p)

    def pick(mn: str):
        """採算の計算に使う1つ。売価と原価が入っているものを選ぶ。"""
        for p in family.get(mn, []):
            if p.selling_price and p.cost_jpy:
                return p
        return products.get(mn) or (family.get(mn) or [None])[0]

    def stock_of(mn: str):
        """色違いを合わせた実在庫。マスタに無ければ None。"""
        rows = family.get(mn) or ([products[mn]] if mn in products else [])
        if not rows:
            return None
        return sum(int(p.stock or 0) for p in rows)

    # ---- 全体の動き ----
    days = (db.query(RakutenAdDaily)
            .order_by(RakutenAdDaily.day.desc()).limit(30).all())
    overall = None
    if len(days) >= 4:
        latest = days[0]
        past = days[1:15]
        base_clicks = median([d.clicks or 0 for d in past])
        base_cost = median([d.cost or 0 for d in past])
        overall = {
            "day": latest.day.isoformat(),
            "clicks": latest.clicks or 0,
            "cost": round(latest.cost or 0),
            "usual_clicks": round(base_clicks),
            "usual_cost": round(base_cost),
            "roas": round(latest.roas or 0, 1),
            "spike": bool(base_clicks
                          and (latest.clicks or 0) >= base_clicks * _SPIKE_RATIO
                          and (latest.cost or 0) - base_cost >= _SPIKE_MIN_COST),
        }

    # ---- 商品ごと・日ごと ----
    item_days = sorted({d[0] for d in db.query(RakutenAdItemDaily.day).distinct()},
                       reverse=True)
    alerts = []
    latest_day = item_days[0] if item_days else None
    if latest_day:
        past_days = item_days[1:15]
        today_rows = (db.query(RakutenAdItemDaily)
                      .filter(RakutenAdItemDaily.day == latest_day).all())
        history = {}
        if past_days:
            for r in (db.query(RakutenAdItemDaily)
                      .filter(RakutenAdItemDaily.day.in_(past_days)).all()):
                history.setdefault(r.manage_number, []).append(r.clicks or 0)

        for r in today_rows:
            p = pick(r.manage_number)
            be = _breakeven_roas(p, commission_rate) if p else None
            past_clicks = history.get(r.manage_number, [])
            usual = median(past_clicks) if len(past_clicks) >= 3 else None
            clicks = r.clicks or 0
            cost = r.cost or 0
            name = r.item_name or (p.name if p else "")

            # 1) クリックの暴走
            if (usual is not None
                    and clicks >= max(_SPIKE_MIN_CLICKS, usual * _SPIKE_RATIO)
                    and cost >= _SPIKE_MIN_COST):
                times = round(clicks / usual, 1) if usual else None
                alerts.append({
                    "level": "danger", "kind": "spike",
                    "manage_number": r.manage_number, "item_name": name,
                    "headline": (f"クリックがいつもの{times}倍" if times
                                 else "クリックが急に増えた"),
                    "detail": (f"{latest_day.isoformat()} に {clicks:,}クリック"
                               f"（いつもは{round(usual):,}）で {round(cost):,}円。"
                               f"売上{round(r.sales or 0):,}円・{r.orders or 0}件、"
                               f"ROAS {round(r.roas or 0, 1)}%"),
                    "action": "入札を下げるか、いったん止めて中身を確認",
                    "cost": round(cost), "clicks": clicks,
                })

            # 2) 在庫が無いのに出ている（色違いを合わせて0のときだけ）
            have = stock_of(r.manage_number)
            if have is not None and have <= 0 and cost >= _WASTE_MIN_COST:
                alerts.append({
                    "level": "danger", "kind": "waste",
                    "manage_number": r.manage_number, "item_name": name,
                    "headline": "在庫が無いのに広告が出ている",
                    "detail": (f"{latest_day.isoformat()} に {round(cost):,}円"
                               f"（実在庫 {have}個）"),
                    "action": "広告を止める（除外商品に入れる）",
                    "cost": round(cost), "clicks": clicks,
                })

            # 3) 赤字のまま回っている
            if (be is not None and cost >= _JUDGE_MIN_COST
                    and (r.roas or 0) < be and (r.orders or 0) >= 1):
                alerts.append({
                    "level": "warn", "kind": "unprofitable",
                    "manage_number": r.manage_number, "item_name": name,
                    "headline": f"ROAS {round(r.roas or 0, 1)}% ＜ 採算ライン {be}%",
                    "detail": (f"{latest_day.isoformat()} に {round(cost):,}円使って"
                               f"売上{round(r.sales or 0):,}円。この商品は"
                               f"ROAS {be}% を割ると赤字"),
                    "action": "入札を下げる",
                    "cost": round(cost), "clicks": clicks,
                })

    # ---- 広告を止めたまま、在庫が戻っているもの ----
    stopped, resume = [], []
    for ex in db.query(RakutenAdExcluded).order_by(
            RakutenAdExcluded.excluded_at.desc()).all():
        have = stock_of(ex.manage_number)
        d = {"manage_number": ex.manage_number,
             "item_name": ex.item_name or "",
             "item_url": ex.item_url or "",
             "excluded_at": ex.excluded_at or "",
             "stock": have,
             "resume_requested": bool(ex.resume_requested),
             "resume_error": ex.resume_error or ""}
        stopped.append(d)
        if have is not None and have > 0:
            resume.append(d)
            alerts.append({
                "level": "info", "kind": "resume",
                "manage_number": ex.manage_number,
                "item_name": ex.item_name or "",
                "headline": f"入荷したので広告を再開できます（在庫{have}個）",
                "detail": (f"{ex.excluded_at} に除外しました。"
                           f"いまの実在庫は{have}個です"),
                "action": "RMSの「除外商品」から外す",
                "cost": 0, "clicks": 0,
            })

    order = {"danger": 0, "warn": 1, "info": 2}
    alerts.sort(key=lambda a: (order.get(a["level"], 9), -a["cost"]))

    # ---- 今月の上げ下げ ----
    periods = sorted({p[0] for p in db.query(RakutenAdProduct.period).distinct()},
                     reverse=True)
    suggestions = []
    if periods:
        for r in (db.query(RakutenAdProduct)
                  .filter(RakutenAdProduct.period == periods[0]).all()):
            p = pick(r.manage_number)
            profit = _profit_per_order(p, commission_rate) if p else None
            be = _breakeven_roas(p, commission_rate) if p else None
            if profit is None or be is None:
                continue
            cost = r.cost or 0
            if cost < _JUDGE_MIN_COST:
                continue

            # 1クリックで見込める粗利。これより高いCPCは払えない
            max_cpc = profit * ((r.cvr or 0) / 100)
            suggest = round(max_cpc * 0.7)
            now_bid = round(r.bid or 0)
            if (r.orders or 0) == 0:
                move, why = "止める", f"{round(cost):,}円使って売れていない"
            elif (r.roas or 0) < be:
                move, why = "下げる", f"ROAS {round(r.roas or 0, 1)}% ＜ 採算 {be}%"
            elif (r.roas or 0) >= be * 1.5 and suggest > now_bid:
                move, why = "上げる", f"ROAS {round(r.roas or 0, 1)}% で余裕がある"
            else:
                continue
            suggestions.append({
                "manage_number": r.manage_number,
                "item_name": r.item_name or (p.name if p else ""),
                "move": move, "why": why,
                "now_bid": now_bid, "suggest_bid": max(1, suggest),
                "cost": round(cost), "clicks": r.clicks or 0,
                "orders": r.orders or 0, "roas": round(r.roas or 0, 1),
                "breakeven": be, "cvr": round(r.cvr or 0, 2),
                "profit_per_order": round(profit),
            })
        rank = {"止める": 0, "下げる": 1, "上げる": 2}
        suggestions.sort(key=lambda x: (rank.get(x["move"], 9), -x["cost"]))

    return {
        "overall": overall,
        "alerts": alerts,
        "suggestions": suggestions,
        "stopped": stopped,
        "resume_count": len(resume),
        "item_days": [d.isoformat() for d in item_days[:20]],
        "period": periods[0] if periods else None,
        "commission_rate": commission_rate,
    }


@router.get("/item-days")
def item_days(days: int = 10, db: Session = Depends(get_db)):
    """商品ごと・日ごとの数字が、まだ無い日を返す。

    拡張機能がこれを見て、足りない日のレポートだけ作らせる。
    """
    have = {d[0].isoformat() for d in db.query(RakutenAdItemDaily.day).distinct()
            if d[0]}
    today = date.today()
    missing = []
    for i in range(1, max(1, min(days, 60)) + 1):
        d = (today - timedelta(days=i)).isoformat()
        if d not in have:
            missing.append(d)
    return {"missing": missing, "have": sorted(have, reverse=True)[:30]}


# ============================================================
# 除外商品（広告を止めている商品）
# ============================================================
# 在庫切れで止めたまま、入荷しても止まりっぱなしになりやすい。
# RMSの除外一覧（GET /rpp/api/exclude）を拡張機能が丸ごと送ってくるので、
# そのまま控えて、実在庫が戻ったものを見張りで知らせる。

from app.models.rakuten_ad import RakutenAdExcluded


@router.post("/excluded")
def import_excluded(payload: dict, db: Session = Depends(get_db)):
    """除外商品の一覧を丸ごと入れ替える。"""
    items = payload.get("items") or []
    keep = set()
    for it in items:
        if not isinstance(it, dict):
            continue
        mn = str(it.get("itemMngId") or it.get("manage_number") or "").strip()
        if not mn:
            continue
        keep.add(mn)
        row = (db.query(RakutenAdExcluded)
               .filter(RakutenAdExcluded.manage_number == mn).first())
        if not row:
            row = RakutenAdExcluded(manage_number=mn)
            db.add(row)
        row.item_name = str(it.get("itemName") or "")[:500]
        row.item_url = str(it.get("itemUrl") or "")[:500]
        row.image_url = str(it.get("itemImageUrl") or "")[:500]
        row.price = _num(it.get("itemPrice"))
        row.excluded_at = str(it.get("updatedAt") or "")[:30]

    # RMSで除外を外したものは、こちらからも消す
    removed = 0
    if keep:
        for row in db.query(RakutenAdExcluded).all():
            if row.manage_number not in keep:
                db.delete(row)
                removed += 1
    db.commit()
    return {"saved": len(keep), "removed": removed}


@router.post("/excluded/{manage_number}/resume")
def ask_resume(manage_number: str, db: Session = Depends(get_db)):
    """「広告を再開する」を予約する。

    RMSを触れるのは拡張機能だけなので、ここでは印を付けるだけ。
    次にRMSの広告画面を開いたときに、拡張が除外を外す。
    """
    row = (db.query(RakutenAdExcluded)
           .filter(RakutenAdExcluded.manage_number == manage_number).first())
    if not row:
        raise HTTPException(404, "除外の一覧にありません")
    row.resume_requested = True
    row.resume_error = ""
    db.commit()
    return {"ok": True, "manage_number": manage_number}


@router.delete("/excluded/{manage_number}/resume")
def cancel_resume(manage_number: str, db: Session = Depends(get_db)):
    """予約を取り消す。"""
    row = (db.query(RakutenAdExcluded)
           .filter(RakutenAdExcluded.manage_number == manage_number).first())
    if row:
        row.resume_requested = False
        row.resume_error = ""
        db.commit()
    return {"ok": True}


@router.get("/resume-queue")
def resume_queue(db: Session = Depends(get_db)):
    """拡張機能が見る、再開待ちの一覧。"""
    rows = (db.query(RakutenAdExcluded)
            .filter(RakutenAdExcluded.resume_requested == True).all())  # noqa: E712
    return {"items": [r.manage_number for r in rows]}


@router.post("/resume-done")
def resume_done(payload: dict, db: Session = Depends(get_db)):
    """拡張機能からの報告。外せたものは一覧から消す。"""
    done = [str(x) for x in (payload.get("done") or [])]
    error = str(payload.get("error") or "")[:200]
    failed = [str(x) for x in (payload.get("failed") or [])]
    for mn in done:
        row = (db.query(RakutenAdExcluded)
               .filter(RakutenAdExcluded.manage_number == mn).first())
        if row:
            db.delete(row)
    for mn in failed:
        row = (db.query(RakutenAdExcluded)
               .filter(RakutenAdExcluded.manage_number == mn).first())
        if row:
            row.resume_requested = False
            row.resume_error = error or "外せませんでした"
    db.commit()
    return {"done": len(done), "failed": len(failed)}
