"""商品説明（Amazonの箇条書き5行）を作らせるプロンプト。

リサーチシートの「④ 商品説明プロンプトをコピー」と同じものを作る。
商品登録タブからも同じ流れで使えるように、こちらへ持ってきた。

シートは1枚で完結する配布用HTMLなので読み込みを共有できず、
frontend/public/research/sheet.html の buildListingPrompt にも同じ文面がある。
片方だけ直すとずれるので、直すときは両方を直すこと。
"""
import re

IMG_LOOK_RULE = "\n".join([
    "・メイン画像（1枚目）の見せ方と、サブ画像が何枚目に何を説明しているか",
    "・A+（商品紹介コンテンツ）で伝えている内容",
    "・画像でしか分からない仕様（色味・質感・厚み・付属品やパッケージの見た目）",
    "※画像を開けない場合は「画像は未確認」と明記し、中身は推測しないでください。",
])

# URLを開けない相手（ChatGPTなど）に貼ったとき、中身を黙って創作されると困る。
# 「開けなければ開けないと書く」ところまで指示に含める。
URL_READ_RULE = (
    "※URLのページはブラウザで開き、素材・サイズ・入数・セット内容・付属品・仕入単価・仕様、"
    "およびページ画像に書かれている説明まで読み取ってから使ってください。\n"
    "※ページを開けない場合は「1688ページは未確認」と明記し、URLの中身は推測せず、"
    "貼られている情報だけで答えてください。"
)


def _words(text: str) -> list:
    t = re.sub(r"[【】\[\]（）()「」『』・,、。/／|｜:：;；!！?？]", " ", text or "")
    return [w for w in re.split(r"[\s　]+", t) if w]


def build(src: dict, must_kw: str = "", diff: str = "",
          notes: dict = None, short: bool = False,
          title: str = None) -> str:
    """1リサーチぶんのプロンプトを組み立てる。

    src   … amazon_listing_sync.extract() が返すもの
    notes … {row_id: {spec, reviews, imgtext, ...}}
    short … 分析用プロンプトを貼ったチャットで続けるときの短い版
    """
    # タイトルは子があれば / でつなぐ（プロンプトの指定どおり）
    if title is None:
        kids = [(c.get("title") or "").strip() for c in (src.get("children") or [])]
        kids = [k for k in kids if k]
        title = "/".join(kids) if kids else (src.get("title") or "").strip()
    t = (title or "").strip()
    if not t:
        return ""

    diff = (diff or src.get("diff_points") or "").strip()
    notes = notes or {}

    urls = [u for u in (src.get("urls_1688") or []) if u]

    refs, amz = [], []
    for i, row in enumerate(src.get("rows") or []):
        p = notes.get(row.get("row_id")) or {}
        name = (row.get("competitor") or "").strip() or "(名称未入力)"
        asin = (row.get("asin") or "").strip().upper()
        if asin:
            amz.append(f"{name}　https://www.amazon.co.jp/dp/{asin}")
        if not (p.get("spec") or p.get("reviews") or p.get("imgtext")):
            continue
        head = f"■競合{i + 1}：{name}"
        if row.get("price"):
            head += f"（売価{row['price']}円）"
        body = [head, p.get("spec") or "",
                ("【商品画像の文字】\n" + p["imgtext"]) if p.get("imgtext") else "",
                p.get("reviews") or ""]
        refs.append("\n".join([x for x in body if x]))

    out = [
        "■商品説明作成の指示",
        "あなたはプロのセールスコピーライターです。",
        "以下の情報を分析し、ターゲットの購買意欲を最大限に高める"
        "Amazonの箇条書き部分（5行）の商品説明文を作成してください。",
        "",
        "情報は2種類に分かれています。",
        "◆自社の確定情報 … これから売る自社商品の情報。サイズ・素材・数量・機能などの事実はこちらが正。",
        "◆競合の参考情報 … 基本的に同じ商品を売っている他社のページ。訴求の切り口や顧客の悩みをここから参考にする。"
        "事実の記載が食い違う場合は、1688（自社の仕入れ元）の情報を優先する。",
        "",
        "━━━━ ◆自社の確定情報（これから売る商品） ━━━━",
        "",
        "【商品タイトル(バリエーション毎に/で区切る)】",
        "[" + t + "]",
        "",
        "【必須キーワード】",
        "[" + "、".join(_words(must_kw)) + "]",
        "",
    ]

    if diff:
        out += ["【自社の差別化ポイント（事実）】", "[" + diff + "]", ""]

    if urls:
        out += [
            "【1688のページ（自社商品の仕入れ元。URLを開いて読んでください）】",
            "[" + "\n".join(urls) + "]",
            URL_READ_RULE,
            "※画像が添付されている場合は、画像に書かれている内容も必ず読んでください。",
        ]
        if diff:
            out.append("※1688に写っているのは改良前のベース商品です。"
                       "セット数・梱包・付属品などの改良は【自社の差別化ポイント】が正です。")
        out.append("")
    else:
        out += [
            "【1688のページ（自社商品の仕入れ元）】",
            "[　画像に添付しています。必ず画像に書かれている内容を理解してから"
            "商品説明文を作成してください。　]",
            "",
        ]

    if short:
        out += [
            "━━━━ ◆競合の参考情報（このチャットの上にある分析を使う） ━━━━",
            "",
            "競合の仕様・レビュー・Amazonページの内容は、このチャットの先に貼った"
            "分析用プロンプトと、それに対するあなたの分析（競合の弱点・差別化ポイント・"
            "詳細分析）にあります。ここには再掲しません。",
            "訴求の切り口と顧客の悩みはその分析を根拠にし、競合の弱点を突き、"
            "差別化ポイントを訴求に使ってください。",
            "※競合の画像や文章をそのまま真似せず、こちらの言葉で書いてください。",
            "",
        ]
    else:
        out += [
            "━━━━ ◆競合の参考情報（ほぼ同じ商品。訴求の参考に。事実は1688優先） ━━━━",
            "",
            "【競合の仕様・レビュー（参考）】",
            "[" + ("\n\n".join(refs) or "（competitorの仕様・レビューが未入力です）") + "]",
            "",
        ]
        if amz:
            out += [
                "【競合のAmazon商品ページ（参考。開いて画像も見てください）】",
                "[" + "\n".join(amz) + "]",
                IMG_LOOK_RULE,
                "※競合の画像や文章をそのまま真似せず、こちらの言葉で書いてください。",
                "",
            ]

    out += [
        "【作成時のルール】",
        "・5行の構成で作成してください。",
        "・各行の先頭には、その行に何が書かれているかが一目でわかる具体的で端的な見出しを"
        "【】で囲んで必ず記載してください。",
        "・1行あたりの文字数は、見出しを含めて120〜130文字程度（厳守）にしてください。",
        "・抽象的な文言は避け、【ターゲット】の悩みや願望に直接刺さる、具体的な訴求にしてください。",
        "・【必須キーワード】をすべて自然な文章になるように組み込んでください。"
        "不自然になる語だけは無理に入れず外して構いません。",
        "・同じ語を3回以上使わないでください（Amazonの商品仕様エラーの原因になります）。",
        "・サイズ・素材・数量・機能などの事実が競合ページと1688で食い違う場合は、"
        "1688と【自社の差別化ポイント】を優先してください。"
        "競合ページからは訴求ポイントを参考にしてください。",
        ("・【自社の差別化ポイント】に書かれた内容は事実です。1〜4行目の訴求に優先して"
         "使ってください。ただし、そこに書かれていない改良・品質向上を勝手に主張しないでください。")
        if diff else
        ("・競合レビューの不満点を自社商品が解決しているとは限りません。"
         "根拠のない改良・品質向上を勝手に主張しないでください。"),
        "",
        "【構成の指定】",
        "1行目：商品のおすすめポイントを分かりやすく簡潔に記載してください。"
        "出だしに「これが何の商品なのか」を端的に表現すること。",
        "",
        "2行目：アピールポイント①（商品の最大の強みや解決策など）を記載してください。",
        "",
        "3行目：アピールポイント②（次に重要な機能やメリットなど）を記載してください。",
        "",
        "4行目：アピールポイント③を記載してください。それ以外にも伝えたいアピールポイントが"
        "ある場合は、この4行目にまとめて追加してください。",
        "※例外ルール：5行目に書くべき内容が多くて文字数を圧迫する場合、"
        "またはアピールポイントが少ない場合には、5行目の内容（注意事項、簡単な使い方、"
        "お手入れ方法など）をこの4行目に前倒しして記載してもOKとします。",
        "",
        "5行目：サイズ、素材、仕様、注意事項、簡単な使い方、お手入れ方法など、"
        "購入の判断に必要な実用的な情報をまとめてください。",
    ]
    return "\n".join(out)


def check_lines(text: str, must_kw: str = "", ng_hit=None) -> dict:
    """できた5行を検査する。シートの「✅ チェックする」と同じ観点。

    行数・各行の字数（120〜130）・【見出し】の有無・必須キーワードの
    使い漏れ・同じ語の3回以上の重複を見る。
    """
    lines = [l.strip() for l in (text or "").split("\n") if l.strip()]
    problems, oks = [], []

    if not lines:
        return {"ok": False, "problems": ["まだ何も貼られていません"], "lines": []}

    if len(lines) != 5:
        problems.append(f"{len(lines)}行あります（5行にしてください）")
    else:
        oks.append("5行そろっています")

    detail = []
    for i, l in enumerate(lines, 1):
        d = {"no": i, "length": len(l), "text": l}
        bad = []
        if not (120 <= len(l) <= 130):
            bad.append(f"{len(l)}字（120〜130字）")
        if not re.match(r"^【[^】]+】", l):
            bad.append("先頭に【見出し】がありません")
        d["problems"] = bad
        detail.append(d)
    n_bad = sum(1 for d in detail if d["problems"])
    if n_bad:
        problems.append(f"{n_bad}行に直すところがあります")
    elif len(lines) == 5:
        oks.append("字数と見出しはそろっています")

    body = "\n".join(lines)
    missing = [w for w in _words(must_kw) if w and w not in body]
    if missing:
        problems.append("必須キーワードの使い漏れ: " + "・".join(missing[:12]))
    elif _words(must_kw):
        oks.append("必須キーワードはすべて入っています")

    cnt = {}
    for w in _words(body):
        k = w.lower()
        if len(k) >= 2:
            cnt[k] = cnt.get(k, 0) + 1
    rep = [(w, n) for w, n in cnt.items() if n >= 3]
    if rep:
        problems.append("3回以上の重複: "
                        + "・".join(f"{w}×{n}" for w, n in rep[:8])
                        + "（エラー99300の原因）")

    if ng_hit:
        ng = [(w, ng_hit(w)) for w in _words(body)]
        ng = [(w, h) for w, h in ng if h]
        if ng:
            problems.append("禁止語: " + "・".join(f"{w}（{h}）" for w, h in ng[:8]))

    return {"ok": not problems, "problems": problems, "oks": oks, "lines": detail}
