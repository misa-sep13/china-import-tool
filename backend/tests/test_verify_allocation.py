"""配賦の検算が本当に機能するかを確認する。

検算そのものがバグって「常に通る」状態になっていると、
壊れた原価がそのまま保存される。だから正常系だけでなく
「わざと壊すと赤が出るか」を必ず確認する。

実行: cd backend && python -m pytest tests/test_verify_allocation.py -v
      （pytestが無ければ python tests/test_verify_allocation.py でも動く）
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services import invoice_calc as ic


class FakeItem:
    def __init__(self, sku, qty=10):
        self.sku = sku
        self.qty = qty


def make_normal():
    """送料400元・税20000円を、カバー率100%で全額配り切った状態"""
    rows = [
        {"item": FakeItem("A"), "freight_alloc_cny": 200.0,
         "tax_alloc_jpy": 10000.0, "cost_per_unit_jpy": 2700.0},
        {"item": FakeItem("B"), "freight_alloc_cny": 100.0,
         "tax_alloc_jpy": 5000.0, "cost_per_unit_jpy": 2700.0},
    ]
    materials = [
        {"item": FakeItem("M"), "freight_alloc_cny": 100.0,
         "tax_alloc_jpy": 5000.0, "total_cost_jpy": 27000.0},
    ]
    coverage = {"coverage_rate": 100.0, "unknown_count": 0, "level": "ok",
                "covered_cny": 4000.0, "total_cny": 4000.0}
    return rows, materials, coverage


def verify(rows, materials, coverage, freight=400.0, tax=20000.0, cols=None):
    return ic.verify_allocation(
        rows, materials, coverage,
        total_freight_cny=freight, import_tax_jpy=tax, permit_columns=cols,
    )


def detail_of(result, name):
    return next((c["detail"] for c in result["checks"] if c["name"] == name), "")


def test_正常な配賦は通る():
    rows, mats, cov = make_normal()
    assert verify(rows, mats, cov)["ok"] is True


def test_送料の配り忘れを検出する():
    rows, mats, cov = make_normal()
    rows[0]["freight_alloc_cny"] = 0.0   # 200元ぶん配り忘れ
    r = verify(rows, mats, cov)
    assert r["ok"] is False
    assert "200" in detail_of(r, "送料の配賦")


def test_税の配り忘れを検出する():
    rows, mats, cov = make_normal()
    rows[1]["tax_alloc_jpy"] = 0.0       # 5000円ぶん配り忘れ
    assert verify(rows, mats, cov)["ok"] is False


def test_二重計上を検出する():
    """同じSKUが商品行と資材行の両方に出たら、その分が二重に計上される"""
    rows, mats, cov = make_normal()
    mats[0]["item"] = FakeItem("A")
    r = verify(rows, mats, cov)
    assert r["ok"] is False
    assert "A" in detail_of(r, "二重計上")


def test_数量0なのに原価が付いたら検出する():
    rows, mats, cov = make_normal()
    rows[0]["item"] = FakeItem("A", qty=0)
    assert verify(rows, mats, cov)["ok"] is False


def test_カバー率が低い便は止める():
    rows, mats, cov = make_normal()
    cov = {"coverage_rate": 60.0, "unknown_count": 5, "level": "critical",
           "covered_cny": 2400.0, "total_cny": 4000.0}
    for x in rows + mats:            # カバー率相応に配賦額も減る
        x["freight_alloc_cny"] *= 0.6
        x["tax_alloc_jpy"] *= 0.6
    assert verify(rows, mats, cov)["ok"] is False


def test_許可書の実額と食い違ったら検出する():
    rows, mats, cov = make_normal()
    cols = [{"col_no": 1, "duty_jpy": 987,
             "consumption_tax_jpy": 3744, "local_tax_jpy": 1043}]  # 計5774
    r = verify(rows, mats, cov, tax=20000.0, cols=cols)            # 20000円配っている
    assert r["ok"] is False


def test_許可書どおりに配れば通る():
    rows, mats, cov = make_normal()
    cols = [{"col_no": 1, "duty_jpy": 987,
             "consumption_tax_jpy": 3744, "local_tax_jpy": 1043}]
    for x, v in zip(rows + mats, [2887, 1443, 1444]):              # 計5774
        x["tax_alloc_jpy"] = v
    assert verify(rows, mats, cov, tax=5774.0, cols=cols)["ok"] is True


if __name__ == "__main__":
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            passed += 1
            print(f"  [OK] {name}")
        except AssertionError as e:
            failed += 1
            print(f"  [NG] {name}: {e}")
    print(f"\nPASS={passed} FAIL={failed}")
    sys.exit(1 if failed else 0)
