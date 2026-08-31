"""楽天の商品タイトル・商品説明文をClaude APIで生成する。

SDKは入れずhttpxで直接叩く（他の外部API連携と同じ方針。依存を増やさない）。
ANTHROPIC_API_KEY が未設定の間は生成機能だけが無効になり、
ドラフトの手入力・保存は今までどおり使える（fail-open）。

ライバルの商品説明は「材料」として渡すが、そのまま書き写さないよう
プロンプトで明示している。カラー展開なども自社の実際の値を優先させる。
"""
import json
import os
from typing import Optional

import httpx

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-5"
# 楽天の商品名は255文字まで。余裕を持たせて上限を指示する
TITLE_MAX = 120


def is_enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _model() -> str:
    return os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL


def _variant_text(draft: dict) -> str:
    """バリエーションを読める形にする。仕様表のカラー欄の材料になる。"""
    axis = (draft.get("variant_axis") or "").strip()
    rows = draft.get("variants") or []
    labels = [str(r.get("label") or "").strip() for r in rows]
    labels = [x for x in labels if x]
    if not axis or not labels:
        return "(なし・単品)"
    return f"{axis}: " + "、".join(labels)


def build_prompt(draft: dict, kind: str) -> str:
    """生成用のプロンプトを組み立てる。履歴に残すので関数として分けている。"""
    own = [
        f"SKU: {draft.get('sku') or '(未設定)'}",
        f"自社で付けたい商品名の案: {draft.get('rakuten_title') or '(未設定)'}",
        f"仕入れ元の中国語商品名: {draft.get('supplier_name_cn') or '(なし)'}",
        f"色・サイズなどの仕様: {draft.get('supplier_spec') or '(なし)'}",
        f"バリエーション: {_variant_text(draft)}",
        f"販売価格: {draft.get('price') or '(未設定)'}円",
        "この商品について（自分で書いたもの）:\n"
        + (draft.get("product_notes") or "(なし)"),
        f"社内メモ: {draft.get('memo') or '(なし)'}",
    ]
    rival = [
        f"ライバルの商品名: {draft.get('rival_title') or '(なし)'}",
        f"ライバルの販売価格: {draft.get('rival_price') or '(なし)'}円",
        f"ライバルの商品説明: {(draft.get('rival_caption') or '(なし)')[:1500]}",
    ]

    if kind == "title":
        task = (
            "楽天市場の商品名（タイトル）を1案だけ作ってください。\n"
            f"- 全角{TITLE_MAX}文字以内\n"
            "- 検索されやすいキーワードを前半に入れる\n"
            "- 記号の多用や誇大表現は避ける\n"
            "出力はタイトル本文のみ。前置きや説明は不要です。"
        )
    elif kind == "description":
        task = (
            "楽天市場の商品説明文（PC用）を作ってください。\n"
            "- 「【商品紹介】」で始め、箇条書き中心で読みやすく\n"
            "- 改行は <br> を使ったHTMLで出力\n"
            "- サイズや素材など、与えられていない情報は創作しない\n"
            "出力は説明文本文のみ。前置きは不要です。"
        )
    elif kind == "material":
        # 説明文は決まった形（特徴＋仕様表＋検索キーワード）で組み立てる。
        # HTMLごと書かせると形が崩れるので、材料だけ作らせる
        task = (
            "商品説明を作るための材料を出してください。\n\n"
            "features: 商品の特徴。4〜7個。1つ40文字くらいまで。"
            "「・」などの記号は付けず、文だけ書いてください。\n"
            "spec_rows: 仕様表の行。カラー・サイズ・素材・個数など、"
            "分かるものだけ。分からない項目は入れないでください。\n"
            "seo_words: 検索用のキーワードを空白区切りで20〜30語。\n\n"
            "サイズや素材など、与えられていない情報は創作しないでください。"
            "ライバルの説明にあっても、自社の仕様として確認できないものは"
            "spec_rows に入れないこと。\n\n"
            "JSONだけを出力してください。形式:\n"
            '{"features": ["...", "..."], '
            '"spec_rows": [{"label": "カラー", "value": "..."}], '
            '"seo_words": "..."}'
        )
    else:
        task = (
            "楽天市場の商品名と商品説明文（PC用）を作ってください。\n"
            'JSONで {"title": "...", "description": "..."} の形式のみ出力してください。'
        )

    return (
        "あなたは楽天市場の店舗運営者向けに商品ページの文章を書くアシスタントです。\n"
        "ライバル商品の説明文は参考情報です。表現をそのまま書き写さず、"
        "自社の商品情報を正として書いてください。"
        "カラー展開や仕様がライバルと違う場合は必ず自社の情報を優先します。\n"
        "とくに「この商品について（自分で書いたもの）」は、実際に商品を"
        "見ている人が書いた一番確かな情報です。ライバルの説明と食い違う"
        "ときは、こちらを正としてください。\n\n"
        "## 自社の商品情報\n" + "\n".join(own) + "\n\n"
        "## 参考（ライバル商品）\n" + "\n".join(rival) + "\n\n"
        "## 依頼\n" + task
    )


async def generate(draft: dict, kind: str = "both") -> dict:
    """生成して {"prompt", "output", "model"} を返す。"""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY が未設定です。Renderの環境変数に設定してください。"
        )

    prompt = build_prompt(draft, kind)
    payload = {
        "model": _model(),
        "max_tokens": 2000,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    async with httpx.AsyncClient(timeout=120) as client:
        res = await client.post(ANTHROPIC_URL, json=payload, headers=headers)
    if res.status_code != 200:
        raise RuntimeError(f"生成に失敗しました（{res.status_code}）: {res.text[:300]}")

    data = res.json()
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
    return {"prompt": prompt, "output": text, "model": payload["model"]}


# 情報が足りないとAIが断ることがある。その文をそのまま商品名として
# 保存すると、断り文が商品名になってしまう（実際に起きた）
_REFUSAL_SIGNS = ("申し訳ございません", "申し訳ありません", "できません",
                  "情報が不足", "未設定のため")


def looks_like_refusal(text: str) -> bool:
    """AIが作らずに断ったかどうか。

    商品名にしては長すぎ、かつ断りの言い回しが入っていれば断りとみなす。
    商品名は普通100文字前後なので、200文字を超えていたら文章である。
    """
    t = (text or "").strip()
    if not t:
        return True
    return len(t) > 200 and any(w in t for w in _REFUSAL_SIGNS)


def split_output(kind: str, output: str) -> dict:
    """生成結果をタイトル／説明文に振り分ける。both のときはJSONを試す。"""
    if kind == "title":
        return {"title": output.strip()}
    if kind == "description":
        return {"description": output.strip()}
    body = output.strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        parsed = json.loads(body)
        return {
            "title": (parsed.get("title") or "").strip() or None,
            "description": (parsed.get("description") or "").strip() or None,
        }
    except Exception:
        # JSONで返らなかった場合は説明文として扱う（捨てない）
        return {"description": output.strip()}


# ---------- 商品説明のHTML ----------
#
# 実際に登録している商品説明は「特徴の箇条書き ＋ 仕様表 ＋ 検索キーワード」
# という決まった形をしている。自由文をAIに書かせると形が崩れるので、
# 材料だけAIに作らせて、組み立てはこちらで行う。
# 色や罫線は既存の商品ページに合わせてある（変えると見た目が揃わない）。

_TABLE_HEAD = ('<table width="100%" border="0" cellpadding="5" cellspacing="1" '
               'bgcolor="#555545"  bordercolor="#999">')
_TD_LABEL = ('<td width="20%" align="center" valign="middle" bgcolor="#F5F5F5">\n'
             '<font color="#333333" size="2">{label}</font>\n</td>')
_TD_VALUE = ('<td align="left" valign="top" bgcolor="#FFFFFF">\n'
             '<font color="#555545" size="2">\n{value}\n</font>\n</td>')


def build_description(features, spec_rows, seo_words):
    """商品説明のHTMLを組み立てる。

    features:  ["マウスピースや入れ歯の持ち運びに！", ...]
    spec_rows: [{"label": "カラー", "value": "ホワイト、ネイビー"}, ...]
    seo_words: "マウスピースケース リテーナー おしゃれ …"
    """
    parts = ["【商品紹介】<br> "]
    for f in (features or []):
        t = str(f).strip()
        if t:
            parts.append(f"・{t}<br> ")

    rows = [r for r in (spec_rows or [])
            if str(r.get("label") or "").strip() and str(r.get("value") or "").strip()]
    if rows:
        parts.append("\n<br><br> <br>")
        parts.append(_TABLE_HEAD)
        for r in rows:
            parts.append("\n<tr>")
            parts.append(_TD_LABEL.format(label=str(r["label"]).strip()))
            parts.append(_TD_VALUE.format(value=str(r["value"]).strip()))
            parts.append("</tr>\n")
        parts.append("</table>")

    words = (seo_words or "").strip()
    if words:
        parts.append("\n<br><br> <br> \n")
        parts.append(words)

    return "\n".join(parts)
