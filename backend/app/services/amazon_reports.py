"""SP-API Reports で日別の実績を取ってくる。

発注ロジックは「その日どうだったか」を知らないと組めない。
  ・在庫が無かった日は、売れなかったのではなく売れようがなかった
  ・Vine（レビュー用の無料配布）は有償の需要ではない
  ・まとめ買いの日を日常の実力と見なすと在庫を持ちすぎる
  ・セール日をそのまま数えても、除外しても、どちらも歪む
どれも日別が要る。ここでは2種類のレポートを取る。

  GET_FLAT_FILE_ALL_ORDERS_DATA_BY_LAST_UPDATE_GENERAL
      注文明細。日別の販売数・売上・プロモ値引き・Vineが分かる
  GET_LEDGER_SUMMARY_VIEW_DATA
      FBA在庫元帳（日次）。その日の終わりに販売可能在庫があったか

レポートは「作成を依頼 → 出来るまで待つ → ダウンロード」の3段構え。
数分かかることがあるので、画面から直接ではなく夜間の取り込みで使う。
"""
import csv
import gzip
import io
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

from app.services.amazon_api import _get_access_token

log = logging.getLogger("amazon.reports")

BASE = "https://sellingpartnerapi-fe.amazon.com"
MARKETPLACE = "A1VC38T7YXB528"      # Amazon.co.jp

# レポートが出来るまで待つ上限。実測で数十秒〜数分
POLL_MAX_SEC = 600
POLL_INTERVAL = 10

ORDERS_REPORT = "GET_FLAT_FILE_ALL_ORDERS_DATA_BY_LAST_UPDATE_GENERAL"
LEDGER_REPORT = "GET_LEDGER_SUMMARY_VIEW_DATA"


class ReportError(Exception):
    """取り込みを止めるべき失敗。画面にそのまま出せる日本語。"""


def _request(path: str, method: str = "GET", body: Optional[dict] = None) -> dict:
    token = _get_access_token()
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={
            "x-amz-access-token": token,
            "Content-Type": "application/json",
        },
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as res:
                raw = res.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 ** (attempt + 1))
                continue
            raise ReportError(f"レポートAPIがエラーを返しました（HTTP {e.code}）"
                              f": {e.read().decode()[:300]}")
        except Exception as e:
            raise ReportError(f"レポートAPIに繋がりませんでした（{type(e).__name__}）")
    raise ReportError("レポートAPIのレート制限が続いています")


def _create_report(report_type: str, start: date, end: date,
                   options: Optional[dict] = None) -> str:
    body = {
        "reportType": report_type,
        "marketplaceIds": [MARKETPLACE],
        # 終端は翌日0時。その日ぶんを丸ごと含めるため
        "dataStartTime": datetime.combine(
            start, datetime.min.time(), timezone.utc).isoformat(),
        "dataEndTime": datetime.combine(
            end + timedelta(days=1), datetime.min.time(), timezone.utc).isoformat(),
    }
    if options:
        body["reportOptions"] = options
    d = _request("/reports/2021-06-30/reports", "POST", body)
    rid = d.get("reportId")
    if not rid:
        raise ReportError("レポートの作成を受け付けてもらえませんでした")
    return rid


def _wait_report(report_id: str) -> Optional[str]:
    """出来上がるまで待ち、ダウンロード用のIDを返す。

    対象データが1件も無いと DONE でも documentId が付かない。
    それは失敗ではないので None を返す。
    """
    waited = 0
    while waited < POLL_MAX_SEC:
        d = _request(f"/reports/2021-06-30/reports/{report_id}")
        status = d.get("processingStatus")
        if status == "DONE":
            return d.get("reportDocumentId")
        if status in ("CANCELLED", "FATAL"):
            # CANCELLED は「対象データ無し」でも起きる
            if status == "CANCELLED":
                return None
            raise ReportError(f"レポートの作成に失敗しました（{status}）")
        time.sleep(POLL_INTERVAL)
        waited += POLL_INTERVAL
    raise ReportError("レポートが時間内に出来上がりませんでした")


def _download(document_id: str) -> str:
    d = _request(f"/reports/2021-06-30/documents/{document_id}")
    url = d.get("url")
    if not url:
        raise ReportError("レポートの取り出し先が分かりませんでした")
    with urllib.request.urlopen(url, timeout=120) as res:
        raw = res.read()
    if d.get("compressionAlgorithm") == "GZIP":
        raw = gzip.decompress(raw)
    # 日本のレポートは cp932 のことがある。utf-8 で読めなければ切り替える
    for enc in ("utf-8", "cp932", "shift_jis"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _rows(text: str) -> List[dict]:
    """レポートはタブ区切り。列名は日本語のことも英語のこともある。"""
    if not text.strip():
        return []
    return list(csv.DictReader(io.StringIO(text), delimiter="\t"))


def _pick(row: dict, *names) -> str:
    """列名のゆれを吸収して値を取る。"""
    for n in names:
        if n in row and row[n] not in (None, ""):
            return str(row[n]).strip()
    return ""


def _num(s) -> float:
    try:
        return float(str(s or "0").replace(",", "").replace("¥", "").strip() or 0)
    except ValueError:
        return 0.0


def fetch_orders(start: date, end: date) -> List[dict]:
    """注文明細を日別に集計して返す。

    戻り: [{sku, asin, day, units, vine_units, revenue, promo_discount}]

    Vineの見分けは promotion-ids に Vine が含まれるかで行う。
    キャンセルされた注文は数えない（売れていないので）。
    """
    rid = _create_report(ORDERS_REPORT, start, end)
    doc = _wait_report(rid)
    if not doc:
        return []
    rows = _rows(_download(doc))

    agg: Dict[tuple, dict] = {}
    for r in rows:
        status = _pick(r, "order-status", "注文ステータス").lower()
        if "cancel" in status or "キャンセル" in status:
            continue

        sku = _pick(r, "sku", "SKU", "seller-sku")
        if not sku:
            continue
        asin = _pick(r, "asin", "ASIN")

        raw_day = _pick(r, "purchase-date", "購入日")
        if not raw_day:
            continue
        try:
            # 「2026-09-01T12:34:56+00:00」の形。日付だけ使う
            day = datetime.fromisoformat(raw_day.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                day = datetime.strptime(raw_day[:10], "%Y-%m-%d").date()
            except ValueError:
                continue

        qty = int(_num(_pick(r, "quantity", "quantity-shipped", "数量")))
        if qty <= 0:
            continue

        promo_ids = _pick(r, "promotion-ids", "プロモーションID")
        is_vine = "vine" in promo_ids.lower()

        price = _num(_pick(r, "item-price", "商品の販売価格"))
        promo = abs(_num(_pick(r, "item-promotion-discount", "商品プロモーション割引")))

        key = (sku, day)
        e = agg.setdefault(key, {
            "sku": sku, "asin": asin, "day": day,
            "units": 0, "vine_units": 0, "revenue": 0.0, "promo_discount": 0.0,
        })
        e["units"] += qty
        if is_vine:
            e["vine_units"] += qty
        e["revenue"] += price
        e["promo_discount"] += promo
        if asin and not e["asin"]:
            e["asin"] = asin

    return list(agg.values())


def fetch_ledger(start: date, end: date) -> List[dict]:
    """FBA在庫元帳（日次）から、日ごとの販売可能在庫の期末残を返す。

    戻り: [{sku, day, sellable_end}]

    在庫が無かった日を「売れなかった日」として平均に入れると、
    実力を低く見て発注を絞り、また欠品する。それを避けるための材料。
    """
    rid = _create_report(LEDGER_REPORT, start, end,
                         {"aggregateByLocation": "COUNTRY",
                          "aggregatedByTimePeriod": "DAILY"})
    doc = _wait_report(rid)
    if not doc:
        return []
    rows = _rows(_download(doc))

    out = []
    for r in rows:
        sku = _pick(r, "MSKU", "msku", "sku")
        if not sku:
            continue
        raw_day = _pick(r, "Date", "date", "日付")
        if not raw_day:
            continue
        day = None
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
            try:
                day = datetime.strptime(raw_day[:10], fmt).date()
                break
            except ValueError:
                continue
        if not day:
            continue

        disposition = _pick(r, "Disposition", "disposition")
        if disposition and disposition.upper() != "SELLABLE":
            continue

        end_bal = int(_num(_pick(r, "Ending Warehouse Balance",
                                 "ending-warehouse-balance", "期末残高")))
        out.append({"sku": sku, "day": day, "sellable_end": end_bal})
    return out
