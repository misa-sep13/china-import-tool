"""送料の重量按分を確認する。

金額比だと、安くて嵩張るものが送料をほとんど負担しない
（実インボイスで耳栓が17倍の差になった）。箱の実測重量で配ることで
これを正す。箱データが無い便では黙って金額比に落ちるのではなく、
落ちたことが呼び出し元に分かるようにする。

実行: cd backend && python tests/test_freight_by_weight.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services import invoice_calc as ic


def make_box_data():
    """2箱。箱1は重い(30kg)が中身は安物、箱2は軽い(10kg)が中身は高級品"""
    return {
        "boxes": {
            1: {"billing_weight": 30.0, "actual_weight": 29.0, "volume": 0.12},
            2: {"billing_weight": 10.0, "actual_weight": 9.5, "volume": 0.05},
        },
        "contents": [
            {"box": 1, "goods_id": "CHEAP", "qty": 100},
            {"box": 2, "goods_id": "PRICEY", "qty": 10},
        ],
        "total_billing_weight": 40.0,
        "available": True,
    }


def test_重量比で配り切る():
    box = make_box_data()
    # 安物100元 / 高級品900元。金額比なら 10% : 90%
    res = ic.calc_freight_by_weight(["CHEAP", "PRICEY"], [100.0, 900.0], box, 400.0)
    assert res["fallback"] is False
    assert abs(sum(res["alloc"].values()) - 400.0) < 0.01
    # 重量比 30:10 なので 300 : 100 になるはず（金額比なら 40 : 360）
    assert abs(res["alloc"][0] - 300.0) < 0.01
    assert abs(res["alloc"][1] - 100.0) < 0.01


def test_金額比とは配分が変わる():
    """安くて重いものが、金額比よりずっと多く負担する"""
    box = make_box_data()
    res = ic.calc_freight_by_weight(["CHEAP", "PRICEY"], [100.0, 900.0], box, 400.0)
    money_share = 400.0 * 100.0 / 1000.0     # 金額比なら40元
    assert res["alloc"][0] > money_share * 5  # 実際は300元＝7.5倍


def test_混載箱は個数比で分ける():
    box = {
        "boxes": {1: {"billing_weight": 20.0}},
        "contents": [
            {"box": 1, "goods_id": "A", "qty": 30},
            {"box": 1, "goods_id": "B", "qty": 10},
        ],
        "total_billing_weight": 20.0,
        "available": True,
    }
    res = ic.calc_freight_by_weight(["A", "B"], [500.0, 500.0], box, 100.0)
    assert abs(res["alloc"][0] - 75.0) < 0.01   # 30/40
    assert abs(res["alloc"][1] - 25.0) < 0.01   # 10/40


def test_箱データが無ければ金額比に落ちる():
    res = ic.calc_freight_by_weight(["A", "B"], [100.0, 900.0], None, 400.0)
    assert res["fallback"] is True
    assert abs(res["alloc"][0] - 40.0) < 0.01
    assert abs(sum(res["alloc"].values()) - 400.0) < 0.01


def test_明細と箱单が紐づかなければ金額比に落ちる():
    """一部でも紐づかないと配り切れないので、黙って歪めず金額比に落とす"""
    box = make_box_data()
    res = ic.calc_freight_by_weight(["CHEAP", "UNKNOWN"], [100.0, 900.0], box, 400.0)
    assert res["fallback"] is True
    assert "紐づかない" in res["reason"]
    assert abs(sum(res["alloc"].values()) - 400.0) < 0.01


def test_同じ商品IDが複数行にあれば金額比で分ける():
    box = {
        "boxes": {1: {"billing_weight": 10.0}},
        "contents": [{"box": 1, "goods_id": "A", "qty": 100}],
        "total_billing_weight": 10.0,
        "available": True,
    }
    # 同じ商品IDの明細が2行（色違いなど）。箱单側は合算1行
    res = ic.calc_freight_by_weight(["A", "A"], [300.0, 100.0], box, 100.0)
    assert abs(res["alloc"][0] - 75.0) < 0.01
    assert abs(res["alloc"][1] - 25.0) < 0.01
    assert abs(sum(res["alloc"].values()) - 100.0) < 0.01


def test_箱シートが無いブックでも落ちない():
    class FakeWB:
        sheetnames: list = []
    res = ic.parse_box_sheets(FakeWB())
    assert res["available"] is False
    assert res["boxes"] == {}


if __name__ == "__main__":
    # Windowsコンソール(cp932)ではテスト名の中国語が出せないので UTF-8 に切り替える
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
