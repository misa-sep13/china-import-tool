"""この1週間に届いたぶんを、便ごとに出す計算。

就労支援の画面は残量しか出していなかった。作業は平均1週間かかるので、
今日届いたぶんと先週届いたぶんが同じ数字に混ざると、どれがまだ
手つかずなのか分からない。
"""
import ast
import io
import os
import types

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "app", "api", "routes", "welfare.py")


def _load():
    """sqlalchemy を入れずに済むよう、欲しい関数だけを取り出して動かす。"""
    tree = ast.parse(io.open(SRC, encoding="utf-8").read())
    picked = [n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "_recent_receipts"]
    assert picked, "_recent_receipts が見つからない"
    mod = types.ModuleType("welfare_part")
    exec(compile(ast.Module(body=picked, type_ignores=[]), SRC, "exec"),
         mod.__dict__)
    return mod._recent_receipts


recent = _load()
LIMIT = "2026-10-29"   # この日より前の便は出さない


def qtys(lines):
    return [(l["date"], l["qty"]) for l in lines]


def test_今週の2便はそれぞれ出る():
    got = [("2026-10-29", "10/29", 30), ("2026-11-04", "11/4", 20)]
    assert qtys(recent(got, LIMIT)) == [("2026-10-29", 30),
                                        ("2026-11-04", 20)]


def test_1週間より前の便は出さない():
    got = [("2026-10-01", "", 15), ("2026-11-02", "", 8)]
    assert qtys(recent(got, LIMIT)) == [("2026-11-02", 8)]


def test_届いた数をそのまま出す():
    # 残量と突き合わせない。作業に出したあとでも、届いた数は変わらない
    got = [("2026-11-03", "", 1250)]
    assert qtys(recent(got, LIMIT)) == [("2026-11-03", 1250)]


def test_入荷の記録が無ければ何も出ない():
    assert recent([], LIMIT) == []


def test_同じ日の2便はまとめる():
    got = [("2026-11-02", "11/2", 10), ("2026-11-02", "11/2b", 15)]
    out = recent(got, LIMIT)
    assert qtys(out) == [("2026-11-02", 25)]
    assert out[0]["shipment_no"] == "11/2・11/2b"


def test_日付が無い行は出さない():
    assert recent([(None, "", 20)], LIMIT) == []


if __name__ == "__main__":
    ok = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            ok += 1
    print(f"{ok} passed")
