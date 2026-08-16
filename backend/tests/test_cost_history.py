"""原価履歴の記録を確認する。

商品マスタの cost_jpy は最後に保存した便で上書きされるため、
便ごとの実績をここに残さないと後から加重平均へ切り替えられない。

実行: cd backend && python tests/test_cost_history.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.services import invoice_calc as ic


class FakeItem:
    def __init__(self, sku, qty):
        self.sku, self.qty = sku, qty


class FakeQuery:
    def __init__(self, store):
        self.store = store
        self._filters = []

    def filter(self, *args):
        self._filters.extend(args)
        return self

    def first(self):
        # 実DBの代わりに (source, sku, invoice_no) で引く
        key = tuple(getattr(f.right, "value", None) for f in self._filters)
        return self.store.get(key)


class FakeDB:
    """(source, sku, invoice_no) をキーに持つだけの最小のスタブ"""
    def __init__(self):
        self.rows = {}
        self.added = []

    def query(self, model):
        return FakeQuery(self.rows)

    def add(self, obj):
        self.rows[(obj.source, obj.sku, obj.invoice_no)] = obj
        self.added.append(obj)


def row(sku, qty, cost, set_size=1, freight=10.0, tax=100.0, fee=20.0, total=500.0):
    return {
        "item": FakeItem(sku, qty), "product": None, "set_size": set_size,
        "cost_jpy": cost, "total_price_cny": total,
        "freight_alloc_cny": freight, "tax_alloc_jpy": tax,
        "customs_fee_alloc_jpy": fee,
    }


COMMON = dict(
    source="rakuten", invoice_no="INV-1", invoice_date="2026-01-15",
    exchange_rate=22.0, coverage={"coverage_rate": 100.0}, freight_method="weight",
)


def test_便ごとに記録される():
    db = FakeDB()
    n = ic.record_cost_history(db, [row("A", 10, 250.0), row("B", 20, 100.0)], **COMMON)
    assert n == 2
    assert len(db.added) == 2


def test_同一SKUの複数行は合算する():
    """色違いで同URL・分納などで1便に同じSKUが複数行出る。
    行ごとに上書きし合うと最後の行しか残らない"""
    db = FakeDB()
    n = ic.record_cost_history(
        db, [row("A", 10, 200.0, freight=10.0), row("A", 30, 300.0, freight=30.0)], **COMMON
    )
    assert n == 1
    saved = db.added[0]
    assert saved.qty == 40
    assert abs(saved.freight_alloc_cny - 40.0) < 0.01
    # 1セット原価は販売セット数で重み付け: (200*10 + 300*30) / 40 = 275
    assert abs(saved.cost_jpy - 275.0) < 0.1


def test_セット品は販売セット数で重みを持つ():
    db = FakeDB()
    ic.record_cost_history(db, [row("A", 600, 900.0, set_size=3)], **COMMON)
    saved = db.added[0]
    assert saved.qty == 600
    assert saved.set_size == 3
    assert abs(saved.sell_units - 200.0) < 0.01   # 600 / 3


def test_同じ便を再保存しても増えない():
    db = FakeDB()
    ic.record_cost_history(db, [row("A", 10, 250.0)], **COMMON)
    ic.record_cost_history(db, [row("A", 10, 260.0)], **COMMON)
    assert len(db.rows) == 1
    assert abs(list(db.rows.values())[0].cost_jpy - 260.0) < 0.1   # 上書きされる


def test_便が違えば別レコードになる():
    db = FakeDB()
    ic.record_cost_history(db, [row("A", 10, 250.0)], **COMMON)
    ic.record_cost_history(
        db, [row("A", 10, 320.0)],
        **{**COMMON, "invoice_no": "INV-2", "invoice_date": "2026-04-20"},
    )
    assert len(db.rows) == 2


def test_便番号が無ければ記録しない():
    """便を識別できないと重複を潰せないので、記録せず0を返す"""
    db = FakeDB()
    n = ic.record_cost_history(db, [row("A", 10, 250.0)], **{**COMMON, "invoice_no": ""})
    assert n == 0
    assert len(db.rows) == 0


def test_SKUが空の行は飛ばす():
    db = FakeDB()
    n = ic.record_cost_history(db, [row("", 10, 250.0), row("A", 10, 250.0)], **COMMON)
    assert n == 1


def test_信用度も一緒に残す():
    """カバー率と按分方式を残しておかないと、後から
    「この原価はどれだけ信用できるか」が判断できない"""
    db = FakeDB()
    ic.record_cost_history(
        db, [row("A", 10, 250.0)],
        **{**COMMON, "coverage": {"coverage_rate": 82.5}, "freight_method": "money"},
    )
    saved = db.added[0]
    assert abs(saved.coverage_rate - 82.5) < 0.01
    assert saved.freight_method == "money"


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
