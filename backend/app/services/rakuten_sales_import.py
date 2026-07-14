from __future__ import annotations

import csv
import io
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable

import openpyxl


PC_FEE_RATE = 0.035
MOBILE_FEE_RATE = 0.035
POINT_BASE_RATE = 0.01
SAFETY_SYSTEM_RATE = 0.001
PAYMENT_FEE_RATE = 0.0335
FIXED_FEE_RATE = 0.00838
AFFILIATE_SERVICE_RATE = 0.30
COUPON_ISSUE_FEE = 50


def normalize_key(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    if re.fullmatch(r"\d+\.0", text):
        return text[:-2]
    return text


def to_float(value, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)):
        if math.isnan(value):
            return default
        return float(value)
    text = str(value).strip()
    if not text:
        return default
    text = (
        text.replace(",", "")
        .replace("￥", "")
        .replace("¥", "")
        .replace("%", "")
        .replace("円", "")
    )
    try:
        return float(text)
    except Exception:
        return default


def _decode_text(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp932", "shift_jis", "utf-16"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def read_upload_table(filename: str, data: bytes) -> list[list]:
    lower = (filename or "").lower()
    if lower.endswith((".xlsx", ".xlsm")):
        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        all_rows = []
        for ws in wb.worksheets:
            if all_rows:
                all_rows.append([])
            all_rows.extend([[cell for cell in row] for row in ws.iter_rows(values_only=True)])
        return all_rows

    text = _decode_text(data)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
    except Exception:
        dialect = csv.excel_tab if "\t" in sample else csv.excel
    return [row for row in csv.reader(io.StringIO(text), dialect)]


def _clean_header(value) -> str:
    return normalize_key(value).replace("\ufeff", "").replace("\n", "").strip()


def find_table_rows(rows: list[list], required: Iterable[str]) -> list[dict]:
    required = list(required)
    header_idx = None
    headers: list[str] = []
    for i, row in enumerate(rows):
        headers = [_clean_header(v) for v in row]
        if all(req in headers for req in required):
            header_idx = i
            break
    if header_idx is None:
        raise ValueError(f"必要な列が見つかりません: {', '.join(required)}")

    result = []
    for row in rows[header_idx + 1 :]:
        if not any(v not in (None, "") for v in row):
            if result:
                break
            continue
        item = {}
        for idx, header in enumerate(headers):
            if header:
                item[header] = row[idx] if idx < len(row) else None
        result.append(item)
    return result


@dataclass
class SalesAgg:
    product_key: str = ""
    sku_key: str = ""
    product_name: str = ""
    units: float = 0
    sales: float = 0
    point_cost: float = 0
    all_coupon: float = 0
    store_coupon: float = 0
    coupon_fee: float = 0
    rpp_cost: float = 0
    coupon_ad_cost: float = 0
    affiliate_cost: float = 0
    affiliate_fee: float = 0
    sales_store_coupon_excluded: float = 0
    sales_all_coupon_excluded: float = 0
    pc_sales: float = 0
    mobile_sales: float = 0
    platform_fee: float = 0
    shipping_cost: float = 0
    product_cost: float = 0
    profit: float = 0
    matched_sku: str = ""
    extra: dict = field(default_factory=dict)

    def add_order_line(self, line: dict):
        self.units += line["qty"]
        self.sales += line["line_total"]
        self.point_cost += line["point_cost"]
        self.all_coupon += line["all_coupon_alloc"]
        self.store_coupon += line["store_coupon_alloc"]
        self.coupon_fee += line["coupon_fee"]
        self.sales_store_coupon_excluded += line["line_total"] - line["store_coupon_alloc"]
        self.sales_all_coupon_excluded += line["line_total"] - line["all_coupon_alloc"]
        if line["is_pc"]:
            self.pc_sales += line["line_total"] - line["store_coupon_alloc"]
        else:
            self.mobile_sales += line["line_total"] - line["store_coupon_alloc"]
        self.shipping_cost += line["shipping_cost"]
        self.product_cost += line["product_cost"]
        if not self.product_name and line.get("product_name"):
            self.product_name = line["product_name"]
        if not self.matched_sku and line.get("matched_sku"):
            self.matched_sku = line["matched_sku"]

    def finalize(self):
        self.affiliate_fee = self.affiliate_cost * AFFILIATE_SERVICE_RATE
        self.platform_fee = (
            self.pc_sales * PC_FEE_RATE
            + self.mobile_sales * MOBILE_FEE_RATE
            + self.sales_all_coupon_excluded * POINT_BASE_RATE
            + self.sales_all_coupon_excluded * SAFETY_SYSTEM_RATE
            + self.sales_all_coupon_excluded * PAYMENT_FEE_RATE
            + self.sales_store_coupon_excluded * FIXED_FEE_RATE
        )
        self.profit = (
            self.sales
            - self.point_cost
            - self.store_coupon
            - self.coupon_fee
            - self.platform_fee
            - self.shipping_cost
            - self.product_cost
            - self.rpp_cost
            - self.coupon_ad_cost
            - self.affiliate_cost
            - self.affiliate_fee
        )

    def as_dict(self, level: str, period: str) -> dict:
        profit_rate = (self.profit / self.sales * 100) if self.sales else None
        rpp_rate = (self.rpp_cost / self.sales * 100) if self.sales else None
        platform_fee_rate = (self.platform_fee / self.sales_all_coupon_excluded * 100) if self.sales_all_coupon_excluded else None
        return {
            "period": period,
            "level": level,
            "product_key": self.product_key,
            "sku_key": self.sku_key or "",
            "product_name": self.product_name,
            "units": round(self.units, 2),
            "sales": round(self.sales, 2),
            "point_cost": round(self.point_cost, 2),
            "all_coupon": round(self.all_coupon, 2),
            "store_coupon": round(self.store_coupon, 2),
            "coupon_fee": round(self.coupon_fee, 2),
            "rpp_cost": round(self.rpp_cost, 2),
            "coupon_ad_cost": round(self.coupon_ad_cost, 2),
            "affiliate_cost": round(self.affiliate_cost, 2),
            "affiliate_fee": round(self.affiliate_fee, 2),
            "sales_store_coupon_excluded": round(self.sales_store_coupon_excluded, 2),
            "sales_all_coupon_excluded": round(self.sales_all_coupon_excluded, 2),
            "pc_sales": round(self.pc_sales, 2),
            "mobile_sales": round(self.mobile_sales, 2),
            "platform_fee": round(self.platform_fee, 2),
            "platform_fee_rate": round(platform_fee_rate, 2) if platform_fee_rate is not None else None,
            "shipping_cost": round(self.shipping_cost, 2),
            "product_cost": round(self.product_cost, 2),
            "profit": round(self.profit, 2),
            "profit_rate": round(profit_rate, 2) if profit_rate is not None else None,
            "rpp_rate": round(rpp_rate, 2) if rpp_rate is not None else None,
        }


def _product_lookup(products) -> dict[str, object]:
    lookup = {}
    fallback_keys: list[tuple[str, object]] = []
    for p in products:
        keys = {
            normalize_key(getattr(p, "sku", "")),
            normalize_key(getattr(p, "rakuten_sku_id", "")),
            normalize_key(getattr(p, "rakuten_item_url", "")),
        }
        sku = normalize_key(getattr(p, "sku", ""))
        if "_" in sku:
            fallback_keys.append((sku.split("_")[0], p))
        for key in keys:
            if key and key not in lookup:
                lookup[key] = p
    for key, p in fallback_keys:
        if key not in lookup:
            lookup[key] = p
    return lookup


def _parse_order_lines(order_rows: list[dict], products, default_shipping_fee: int = 180) -> tuple[list[dict], int]:
    lookup = _product_lookup(products)
    lines = []
    skipped = 0
    for row in order_rows:
        status = normalize_key(row.get("ステータス"))
        if status == "900":
            skipped += 1
            continue
        product_key = normalize_key(row.get("商品管理番号"))
        if not product_key:
            skipped += 1
            continue
        sku_key = normalize_key(row.get("SKU管理番号")) or normalize_key(row.get("システム連携用SKU番号")) or product_key
        qty = to_float(row.get("個数"))
        unit_price = to_float(row.get("単価"))
        line_total = unit_price * qty
        divisor = to_float(row.get("送付先商品合計金額")) or to_float(row.get("商品合計金額")) or line_total or 1
        ratio = line_total / divisor if divisor else 0
        all_coupon_total = to_float(row.get("クーポン利用総額"))
        store_coupon_total = to_float(row.get("店舗発行クーポン利用額"))
        all_coupon_alloc = all_coupon_total * ratio
        store_coupon_alloc = store_coupon_total * ratio
        point_rate = to_float(row.get("ポイント倍率"), 1)
        point_base = max(0, to_float(row.get("合計金額")) - all_coupon_total)
        point_cost = math.floor(point_base * 0.01 * max(0, point_rate - 1))
        coupon_fee = (COUPON_ISSUE_FEE * qty) if store_coupon_total >= 1 else 0
        terminal = normalize_key(row.get("利用端末"))
        is_pc = terminal in {"", "0", "0.0"}

        product = lookup.get(sku_key) or lookup.get(product_key)
        shipping_fee = getattr(product, "shipping_fee", None) if product else None
        if shipping_fee is None:
            shipping_fee = default_shipping_fee
        cost_jpy = getattr(product, "cost_jpy", None) if product else 0
        product_name = getattr(product, "name", None) if product else normalize_key(row.get("商品名"))
        matched_sku = normalize_key(getattr(product, "sku", "")) if product else ""

        lines.append(
            {
                "product_key": product_key,
                "sku_key": sku_key,
                "qty": qty,
                "unit_price": unit_price,
                "line_total": line_total,
                "all_coupon_alloc": all_coupon_alloc,
                "store_coupon_alloc": store_coupon_alloc,
                "point_cost": point_cost,
                "coupon_fee": coupon_fee,
                "is_pc": is_pc,
                "shipping_cost": qty * to_float(shipping_fee),
                "product_cost": qty * to_float(cost_jpy),
                "product_name": product_name,
                "matched_sku": matched_sku,
            }
        )
    return lines, skipped


def _parse_cost_by_product(rows: list[dict], cost_candidates: list[str]) -> dict[str, float]:
    result = defaultdict(float)
    for row in rows:
        key = normalize_key(row.get("商品管理番号") or row.get("商品管理番号（URL）") or row.get("商品ID"))
        if not key:
            url = normalize_key(row.get("商品ページURL"))
            match = re.search(r"/([^/]+)/?$", url)
            key = match.group(1) if match else ""
        if not key:
            continue
        cost = 0.0
        for name in cost_candidates:
            if name in row:
                cost = to_float(row.get(name))
                break
        result[key] += cost
    return dict(result)


def _parse_affiliate_by_product(rows: list[dict]) -> dict[str, float]:
    result = defaultdict(float)
    for row in rows:
        key = normalize_key(row.get("商品管理番号") or row.get("item_mng_id"))
        if not key:
            continue
        reward = to_float(row.get("成果報酬") if "成果報酬" in row else row.get("rewards"))
        result[key] += reward
    return dict(result)


def build_sales_summary(
    *,
    period: str,
    products,
    settings,
    order_rows: list[dict],
    rpp_rows: list[dict] | None = None,
    coupon_ad_rows: list[dict] | None = None,
    affiliate_rows: list[dict] | None = None,
) -> dict:
    default_shipping_fee = getattr(settings, "default_shipping_fee", 180) or 180
    order_lines, skipped_orders = _parse_order_lines(order_rows, products, default_shipping_fee)

    parent_aggs: dict[str, SalesAgg] = {}
    sku_aggs: dict[tuple[str, str], SalesAgg] = {}
    for line in order_lines:
        p_key = line["product_key"]
        s_key = line["sku_key"]
        parent = parent_aggs.setdefault(p_key, SalesAgg(product_key=p_key, product_name=line.get("product_name") or ""))
        parent.add_order_line(line)
        sku = sku_aggs.setdefault(
            (p_key, s_key),
            SalesAgg(product_key=p_key, sku_key=s_key, product_name=line.get("product_name") or ""),
        )
        sku.add_order_line(line)

    rpp_costs = _parse_cost_by_product(rpp_rows or [], ["実績額(合計)", "実績額", "広告費", "費用"])
    coupon_ad_costs = _parse_cost_by_product(
        coupon_ad_rows or [],
        ["実績額(合計)", "実績額", "広告費", "利用金額", "消化金額", "費用"],
    )
    affiliate_costs = _parse_affiliate_by_product(affiliate_rows or [])

    for key, cost in rpp_costs.items():
        parent_aggs.setdefault(key, SalesAgg(product_key=key)).rpp_cost += cost
    for key, cost in coupon_ad_costs.items():
        parent_aggs.setdefault(key, SalesAgg(product_key=key)).coupon_ad_cost += cost
    for key, cost in affiliate_costs.items():
        parent_aggs.setdefault(key, SalesAgg(product_key=key)).affiliate_cost += cost

    for agg in list(parent_aggs.values()) + list(sku_aggs.values()):
        agg.finalize()

    parent_rows = [agg.as_dict("parent", period) for agg in parent_aggs.values()]
    sku_rows = [agg.as_dict("sku", period) for agg in sku_aggs.values()]
    parent_rows.sort(key=lambda r: (-(r["sales"] or 0), r["product_key"] or ""))
    sku_rows.sort(key=lambda r: (r["product_key"] or "", r["sku_key"] or ""))

    total_sales = sum(r["sales"] for r in parent_rows)
    total_units = sum(r["units"] for r in parent_rows)
    total_profit = sum(r["profit"] for r in parent_rows)
    return {
        "parent_rows": parent_rows,
        "sku_rows": sku_rows,
        "totals": {
            "units": round(total_units, 2),
            "sales": round(total_sales, 2),
            "profit": round(total_profit, 2),
            "profit_rate": round(total_profit / total_sales * 100, 2) if total_sales else None,
        },
        "skipped_orders": skipped_orders,
    }
