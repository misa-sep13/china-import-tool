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


def build_prompt(draft: dict, kind: str) -> str:
    """生成用のプロンプトを組み立てる。履歴に残すので関数として分けている。"""
    own = [
        f"SKU: {draft.get('sku') or '(未設定)'}",
        f"自社で付けたい商品名の案: {draft.get('rakuten_title') or '(未設定)'}",
        f"仕入れ元の中国語商品名: {draft.get('supplier_name_cn') or '(なし)'}",
        f"色・サイズなどの仕様: {draft.get('supplier_spec') or '(なし)'}",
        f"販売価格: {draft.get('price') or '(未設定)'}円",
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
    else:
        task = (
            "楽天市場の商品名と商品説明文（PC用）を作ってください。\n"
            'JSONで {"title": "...", "description": "..."} の形式のみ出力してください。'
        )

    return (
        "あなたは楽天市場の店舗運営者向けに商品ページの文章を書くアシスタントです。\n"
        "ライバル商品の説明文は参考情報です。表現をそのまま書き写さず、"
        "自社の商品情報を正として書いてください。"
        "カラー展開や仕様がライバルと違う場合は必ず自社の情報を優先します。\n\n"
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
