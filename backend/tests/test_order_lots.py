"""固定ロット（「この数でしか買えない」仕入先）の振り分け。

ローカルに sqlalchemy が無いので、rakuten.py をまるごと import せず、
_apply_order_lots だけを抜き出して動かす。
"""
import ast
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "app", "api", "routes", "rakuten.py")


def _load(name):
    tree = ast.parse(io.open(SRC, encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            ns = {}
            exec(compile(ast.Module([node], []), SRC, "exec"), ns)
            return ns[name]
    raise AssertionError(f"{name} が見つかりません")


apply_lots = _load("_apply_order_lots")


class P:
    def __init__(self, sku, lot=None, group=None):
        self.sku = sku
        self.order_lot = lot
        self.order_lot_group = group


def row(sku, daily, needs):
    return {"sku": sku, "daily_avg": daily, "needs_order": needs, "order_qty": 0}


def check(name, got, want):
    assert got == want, f"{name}: {got} ではなく {want} のはず"
    print("ok:", name)


# --- 2色を合わせて500個。日販の比で分かれる ---
items = [row("y48_glay-m", 1.59, True), row("y48_glay-s", 1.83, False)]
prods = {"y48_glay-m": P("y48_glay-m", 500, "y48_glay"),
         "y48_glay-s": P("y48_glay-s", 500, "y48_glay")}
apply_lots(items, prods)
check("合計がロットちょうど", items[0]["order_qty"] + items[1]["order_qty"], 500)
check("売れている色に多く行く", items[1]["order_qty"] > items[0]["order_qty"], True)
check("片方だけ時期が来ていても両方発注", [i["needs_order"] for i in items], [True, True])
check("Mの数", items[0]["order_qty"], 232)
check("Sの数", items[1]["order_qty"], 268)

# --- どちらも時期が来ていなければ何もしない ---
items = [row("y48_glay-m", 1.59, False), row("y48_glay-s", 1.83, False)]
apply_lots(items, prods)
check("時期が来ていなければ0のまま", [i["order_qty"] for i in items], [0, 0])
check("発注にもしない", [i["needs_order"] for i in items], [False, False])

# --- 日販が両方0なら頭割り ---
items = [row("y48_glay-m", 0, True), row("y48_glay-s", 0, False)]
apply_lots(items, prods)
check("頭割り", [i["order_qty"] for i in items], [250, 250])

# --- まとめる相手がいない（1商品だけのロット） ---
items = [row("zz", 2.0, True)]
apply_lots(items, {"zz": P("zz", 300, None)})
check("単独ロットはその数", items[0]["order_qty"], 300)
check("まとめ名は空", items[0]["order_lot_group"], "")

# --- ロットを決めていない商品は触らない ---
items = [{"sku": "aa", "daily_avg": 5, "needs_order": True, "order_qty": 77}]
apply_lots(items, {"aa": P("aa")})
check("ロット無しはそのまま", items[0]["order_qty"], 77)

# --- 端数が出ても合計はロットちょうど（3色） ---
items = [row("a", 1, True), row("b", 1, True), row("c", 1, True)]
prods3 = {k: P(k, 100, "g") for k in ("a", "b", "c")}
apply_lots(items, prods3)
check("3色でも合計ちょうど", sum(i["order_qty"] for i in items), 100)

print("\nぜんぶ通りました")
