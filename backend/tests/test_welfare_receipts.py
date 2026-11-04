"""残量を「この1週間に届いたぶん」に分ける計算。

就労支援の画面は残量しか出していなかった。作業は平均1週間かかるので、
今日届いたぶんと先週届いたぶんが同じ数字に混ざると、どれがまだ
手つかずなのか分からない。
"""
import ast
import io
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "app", "api", "routes", "welfare.py")


def _load():
    """sqlalchemy を入れずに済むよう、欲しい関数だけを取り出して動かす。"""
    tree = ast.parse(io.open(SRC, encoding="utf-8").read())
    want = {"_allocate_receipts"}
    picked = [n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name in want]
    assert len(picked) == len(want), "関数が見つからない"
    mod = types.ModuleType("welfare_part")
    exec(compile(ast.Module(body=picked, type_ignores=[]), SRC, "exec"),
         mod.__dict__)
    return mod


alloc = _load()._allocate_receipts
LIMIT = "2026-10-29"   # この日より前の便は出さない


def qtys(lines):
    return [(l["date"], l["qty"]) for l in lines]


def test_今週の2便はそれぞれ出る():
    got = [("2026-10-29", "10/29", 30), ("2026-11-04", "11/4", 20)]
    assert qtys(alloc(got, 50, LIMIT)) == [("2026-10-29", 30),
                                           ("2026-11-04", 20)]


def test_古い便から先に使われる():
    # 40個は先週より前。30個だけ残っているなら、残りは新しい便のぶん
    got = [("2026-10-10", "", 40), ("2026-11-03", "", 30)]
    assert qtys(alloc(got, 30, LIMIT)) == [("2026-11-03", 30)]


def test_1週間より前の便は出さない():
    got = [("2026-10-01", "", 15)]
    assert alloc(got, 15, LIMIT) == []


def test_入荷の記録が無い在庫は出さない():
    assert alloc([], 12, LIMIT) == []


def test_同じ日の2便はまとめる():
    got = [("2026-11-02", "11/2", 10), ("2026-11-02", "11/2b", 15)]
    out = alloc(got, 25, LIMIT)
    assert qtys(out) == [("2026-11-02", 25)]
    assert out[0]["shipment_no"] == "11/2・11/2b"


def test_新しい便が途中まで使われている():
    got = [("2026-10-20", "", 20), ("2026-11-01", "", 20)]
    assert qtys(alloc(got, 5, LIMIT)) == [("2026-11-01", 5)]


def test_残量が0なら何も出ない():
    got = [("2026-11-04", "", 20)]
    assert alloc(got, 0, LIMIT) == []


def test_入荷より残量が多くても落ちない():
    # 残量修正で増やしたぶん。日付が分からないので入荷ぶんはそのまま出す
    got = [("2026-11-04", "", 20)]
    assert qtys(alloc(got, 50, LIMIT)) == [("2026-11-04", 20)]


if __name__ == "__main__":
    ok = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            ok += 1
            print("ok", name)
    print(f"{ok} passed")
