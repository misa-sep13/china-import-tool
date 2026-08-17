"""通関料の按分を確認する。

船便のみ一律2000円、航空便は無し。輸入許可書には載らない費用なので、
配送方法の選択から渡す。書類1件あたりの手続き費用なので、送料のような
重量比ではなく金額比で配る。

実行: cd backend && python tests/test_customs_fee.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services import invoice_calc as ic


def test_金額比で配り切る():
    alloc = ic.calc_customs_fee_alloc([300.0, 100.0], 2000.0)
    assert abs(alloc[0] - 1500.0) < 0.01
    assert abs(alloc[1] - 500.0) < 0.01
    assert abs(sum(alloc.values()) - 2000.0) < 0.01


def test_航空便は0円():
    alloc = ic.calc_customs_fee_alloc([300.0, 100.0], 0)
    assert sum(alloc.values()) == 0
    assert set(alloc.keys()) == {0, 1}


def test_商品代が0でも落ちない():
    alloc = ic.calc_customs_fee_alloc([0.0, 0.0], 2000.0)
    assert sum(alloc.values()) == 0


def test_船便の通関料は2000円():
    assert ic.CUSTOMS_FEE_SEA_JPY == 2000


class FakeWB:
    def __init__(self, names):
        self.sheetnames = names


def test_海運シートがあれば船便と推測する():
    assert ic.guess_shipping_method(FakeWB(["发票", "海运发票填写要点", "箱单"])) == "sea"


def test_空運シートがあれば航空便と推測する():
    assert ic.guess_shipping_method(FakeWB(["发票", "空运发票填写要点"])) == "air"


def test_手がかりが無ければ空を返す():
    """推測できないときは空。画面側で既定値を出してユーザーに選ばせる"""
    assert ic.guess_shipping_method(FakeWB(["发票", "箱单"])) == ""


def test_検算が通関料の配り忘れを検出する():
    class FakeItem:
        def __init__(self, sku, qty=10):
            self.sku, self.qty = sku, qty

    rows = [
        {"item": FakeItem("A"), "freight_alloc_cny": 200.0, "tax_alloc_jpy": 10000.0,
         "customs_fee_alloc_jpy": 1000.0, "cost_per_unit_jpy": 2700.0},
        {"item": FakeItem("B"), "freight_alloc_cny": 200.0, "tax_alloc_jpy": 10000.0,
         "customs_fee_alloc_jpy": 0.0, "cost_per_unit_jpy": 2700.0},   # 1000円配り忘れ
    ]
    cov = {"coverage_rate": 100.0, "unknown_count": 0, "level": "ok",
           "covered_cny": 4000.0, "total_cny": 4000.0}
    r = ic.verify_allocation(rows, [], cov, total_freight_cny=400.0,
                             import_tax_jpy=20000.0, customs_fee_jpy=2000.0)
    assert r["ok"] is False
    fee = next(c for c in r["checks"] if c["name"] == "通関料の配賦")
    assert fee["ok"] is False


def test_通関料を配り切れば検算が通る():
    class FakeItem:
        def __init__(self, sku, qty=10):
            self.sku, self.qty = sku, qty

    rows = [
        {"item": FakeItem("A"), "freight_alloc_cny": 200.0, "tax_alloc_jpy": 10000.0,
         "customs_fee_alloc_jpy": 1000.0, "cost_per_unit_jpy": 2700.0},
        {"item": FakeItem("B"), "freight_alloc_cny": 200.0, "tax_alloc_jpy": 10000.0,
         "customs_fee_alloc_jpy": 1000.0, "cost_per_unit_jpy": 2700.0},
    ]
    cov = {"coverage_rate": 100.0, "unknown_count": 0, "level": "ok",
           "covered_cny": 4000.0, "total_cny": 4000.0}
    r = ic.verify_allocation(rows, [], cov, total_freight_cny=400.0,
                             import_tax_jpy=20000.0, customs_fee_jpy=2000.0)
    assert r["ok"] is True


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

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
