"""ドラフトを楽天へ登録する。手元のPCで実行する。

楽天の商品APIは書込みに有料オプションが要り、未契約だと401（GA0001）に
なる。Compassにログインしたブラウザから内部APIへ送れば追加費用なしで
登録できるので、その方法を使う。ブラウザが要るためサーバーでは動かない。

  1. サーバーから登録待ちのドラフトを取ってくる
  2. Compassにログイン済みのブラウザで、内部APIへ3本送る
  3. 結果をサーバーへ戻す

使い方:
  python register.py                    # 登録待ちを全部
  python register.py --dry-run          # 送らずに中身だけ見る
  python register.py --limit 1          # 1件だけ試す
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_BASE = "https://china-import-tool.onrender.com/api"
CONF = os.path.join(os.path.expanduser("~"), ".rakuten_register.json")

# 連続で叩くと429になる。手順書の実測に合わせて間隔を空ける
WAIT_BETWEEN_ITEMS = 6.0      # 商品と商品のあいだ
WAIT_BETWEEN_CALLS = 1.2      # 在庫APIはQPS制限が厳しい（GA0003）
RETRY_WAIT = 20.0             # 429が出たときに待つ秒数


def load_conf():
    if os.path.exists(CONF):
        try:
            with open(CONF, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def api(base, path, token, method="GET", body=None):
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {token}"},
        method=method)
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise SystemExit("認証エラー: トークンを取り直してください")
        raise SystemExit(f"APIエラー {e.code}: {e.read().decode()[:300]}")


# 属性は3種類に分かれる（実物のy112を見て分類した）。
#   全商品で共通  … ブランド名・原産国。雛形から引き継ぐ
#   商品ごと      … メーカー型番（SKU）・シリーズ名。今回の値で作る
#   枝ごと        … カラー・代表カラー。バリエーションから作る
COMMON_ATTRS = ("ブランド名", "原産国／製造国", "原産国/製造国")
PER_ITEM_ATTRS = ("メーカー型番", "シリーズ名")
PER_VARIANT_ATTRS = ("カラー", "代表カラー", "サイズ")


def build_attributes(d, tmpl_variant, label1, label2, axis1, axis2,
                     allowed_names=None):
    """バリエーション1枝ぶんの属性を組み立てる。

    ブランド名や原産国はどの商品でも同じなので雛形から引き継ぐ。
    型番・シリーズ名・カラーは商品や枝ごとに変わるので作り直す。
    引き継いだ値をそのまま残すと、別商品の型番やカラーが入ってしまう。

    allowed_names を渡すと、そのジャンルに存在する属性だけに絞る。
    存在しない属性名を送ると 400 IE1002 で落ちるため
    （「良かれと思って代表カラーを全商品に入れる」が事故のもと）。
    """
    attrs = []

    def put(name, value):
        v = str(value or "").strip()
        if not v:
            return
        if allowed_names is not None and name not in allowed_names:
            return          # そのジャンルに無い属性は送らない
        attrs.append({"name": name, "values": [v]})

    # 共通のものを雛形から
    for a in (tmpl_variant or {}).get("attributes", []):
        if a.get("name") in COMMON_ATTRS:
            for v in (a.get("values") or []):
                put(a["name"], v)

    # 商品ごとのもの
    put("メーカー型番", d["sku"])
    put("シリーズ名", d.get("series_name"))

    # ジャンルごとの商品仕様（ペットグッズの素材・本体横幅 など）
    for name, value in (d.get("item_specs") or {}).items():
        if name not in ("メーカー型番", "シリーズ名"):
            put(name, value)

    # 枝ごとのもの。軸の名前がそのまま属性名になる
    def add_axis(axis, label):
        if not axis or not label:
            return
        name = axis.strip()
        put(name, label)
        # 色の絞り込みに使う「代表カラー」。ただし持っているジャンルだけ。
        # 無いジャンルに送ると 400 IE1002 になる
        if name in ("カラー", "色"):
            put("代表カラー", label)

    add_axis(axis1, label1)
    add_axis(axis2, label2)
    return attrs


def collect_allowed_attrs(tmpl):
    """そのジャンルに存在する属性名を集める。

    楽天にジャンル定義を返すAPIが無いので、雛形の商品が持っている
    属性を「存在する属性」とみなす。無い属性名を送ると 400 IE1002。

    枝によって持っている属性が違うことがあるので、全部の枝から集める。
    """
    if not tmpl:
        return None          # 雛形が無ければ絞らない（今までどおり）
    names = set()
    for v in (tmpl.get("variants") or {}).values():
        for a in (v.get("attributes") or []):
            if a.get("name"):
                names.add(a["name"])
    return names or None


def build_variants(d, tmpl_variant=None, allowed_names=None):
    """バリエーションを楽天の形に組み立てる。

    楽天は variantSelectors（選択肢の定義）と variants（各枝）で持つ。
    軸は2つまで（Key0・Key1）。サイズ×種類のような組み合わせになる。

    送料・納期・属性などは項目が多く手で埋めると漏れるので、雛形に
    した既存商品の枝から引き継ぐ（tmpl_variant）。価格と選択肢だけ
    今回の値で上書きする。
    """
    sku = d["sku"]
    base_price = d["price"]
    rows = d.get("variants") or []
    axis1 = (d.get("variant_axis") or "").strip()
    axis2 = (d.get("variant_axis2") or "").strip()

    # 雛形から引き継ぐもの。選択肢・価格・自社SKU番号は毎回変わるので除く
    carry = {}
    if tmpl_variant:
        for k in ("restockOnCancel", "backOrderFlag", "normalDeliveryDateId",
                  "backOrderDeliveryDateId", "articleNumber", "shipping",
                  "features"):
            if k in tmpl_variant:
                carry[k] = tmpl_variant[k]

    # 配送方法セット。指定があれば雛形より優先する
    #   4=ネコポス / 宅急便・宅急便コンパクトは店舗の設定番号
    ship_set = str(d.get("shipping_set") or "").strip()

    def make(vid, selector_values, label_for_sku, price, l1="", l2=""):
        v = dict(carry)
        if ship_set and v.get("shipping"):
            v["shipping"] = {**v["shipping"], "shippingMethodGroup": ship_set}
        v.update({
            "standardPrice": int(price or base_price),
            "merchantDefinedSkuId": label_for_sku,
            "hidden": False,
            "attributes": build_attributes(d, tmpl_variant, l1, l2,
                                           axis1, axis2, allowed_names),
        })
        if selector_values:
            v["selectorValues"] = selector_values
        return vid, v

    if not axis1 or not rows:
        # 単品。バリエーションIDは商品番号と揃えておく
        vid, v = make(sku, None, sku, base_price)
        return None, {vid: v}

    selectors = [{"key": "Key0", "displayName": axis1, "values": []}]
    if axis2:
        selectors.append({"key": "Key1", "displayName": axis2, "values": []})

    variants = {}
    seen1, seen2 = [], []
    for i, r in enumerate(rows):
        l1 = str(r.get("label") or "").strip()
        if not l1:
            continue
        l2 = str(r.get("label2") or "").strip()
        if axis2 and not l2:
            continue

        # 選択肢は重複させない。同じサイズが何度も出るため
        if l1 not in seen1:
            seen1.append(l1)
            selectors[0]["values"].append({"displayValue": l1})
        if axis2 and l2 not in seen2:
            seen2.append(l2)
            selectors[1]["values"].append({"displayValue": l2})

        sv = {"Key0": l1}
        if axis2:
            sv["Key1"] = l2
        suffix = str(r.get("suffix") or "").strip() or f"v{i + 1}"
        # 自社SKU番号は「M-キャット」の形。あとで在庫を紐づけるときの目印
        name = f"{l1}-{l2}" if axis2 else l1
        vid, v = make(f"{sku}_{suffix}", sv, name, r.get("price"), l1, l2)
        variants[vid] = v

    if not variants:
        raise ValueError("バリエーションの中身が空です")
    return selectors, variants


async def fetch_template(page, tmpl_sku, shop_url):
    """雛形にする既存商品を読む。

    送料・納期・属性・レイアウトなど項目が多く、手で埋めると必ず漏れる。
    実績のある商品から引き継ぐ方が確実で早い。
    """
    r = await page.evaluate(
        JS_SEND, ["GET",
                  f"/api/rms/v1/es/2.0/ext/items/manage-numbers/{tmpl_sku}"
                  f"?shopUrl={shop_url}", None])
    if r["status"] != 200:
        raise RuntimeError(
            f"雛形の商品 {tmpl_sku} を読めません（{r['status']}）: {r['body'][:200]}")
    return json.loads(r["body"])


# 雛形から引き継ぐ、商品まるごとの設定。
# 商品ごとに変わるもの（タイトル・説明・画像・価格・バリエーション）は含めない
TEMPLATE_KEYS = ("itemType", "hideItem", "unlimitedInventoryFlag",
                 "features", "payment", "itemDisplaySequence", "layout")


def build_item_body(d, shop_url, tmpl=None):
    """商品本体（①のPUT）に送る中身を組み立てる。

    PUTは全項目置換なので、送らなかった項目は消える。新規登録なので
    問題ないが、既存商品に流用してはいけない。

    雛形があれば、そこから共通の設定を引き継ぐ。
    """
    tmpl_variant = None
    if tmpl:
        vs = tmpl.get("variants") or {}
        # どの枝でも共通の設定は同じなので、先頭を見本にする
        tmpl_variant = next(iter(vs.values()), None)

    selectors, variants = build_variants(d, tmpl_variant,
                                         collect_allowed_attrs(tmpl))

    body = {}
    if tmpl:
        for k in TEMPLATE_KEYS:
            if k in tmpl:
                body[k] = tmpl[k]
        # ジャンルは雛形と違うことがあるので、指定があればそちらを使う
        if tmpl.get("genreId"):
            body["genreId"] = tmpl["genreId"]

    body.update({
        "title": d["rakuten_title"],
        "productDescription": {"pc": d.get("description_pc") or ""},
        "variants": variants,
    })
    if selectors:
        body["variantSelectors"] = selectors

    # 画像。R-Cabinetに上げたURLを渡す。楽天は location で持つ。
    # altには商品名を入れる（既存商品がそうなっている）
    imgs = [u for u in (d.get("image_urls") or []) if u]
    if imgs:
        alt = (d.get("rakuten_title") or "")[:100]
        body["images"] = [{"type": "CABINET", "location": u, "alt": alt}
                          for u in imgs]
        # 白背景画像は1枚目を使う。検索結果に出る画像なので必須に近い
        body["whiteBgImage"] = {"type": "CABINET", "location": imgs[0]}

    if d.get("catchcopy"):
        body["tagline"] = d["catchcopy"]
    if d.get("description_sp"):
        body["productDescription"]["sp"] = d["description_sp"]
    if d.get("genre_id"):
        body["genreId"] = str(d["genre_id"])
    return body


JS_SEND = r"""
async ([method, path, body]) => {
  // Compassの内部APIへ送る。fetchはブロックされることがあるのでXHRを使う。
  // 認証はログイン済みのCookieに乗るので、APIキーは要らない。
  const token = (() => {
    const m = document.querySelector('meta[name="csrf-token"]');
    if (m) return m.content;
    return window.__csrf || '';
  })();
  return await new Promise((resolve) => {
    const x = new XMLHttpRequest();
    x.open(method, path, true);
    x.setRequestHeader('Content-Type', 'application/json;charset=UTF-8');
    if (token) x.setRequestHeader('X-CSRF-Token', token);
    x.onload = () => resolve({ status: x.status, body: x.responseText.slice(0, 800) });
    x.onerror = () => resolve({ status: 0, body: 'ネットワークエラー' });
    x.send(body === null ? null : JSON.stringify(body));
  });
}
"""


async def fetch_csrf(page):
    """CSRFトークンを用意する。

    metaタグに無いことがあるので、その場合は任意のGETの応答ヘッダから拾う。
    """
    got = await page.evaluate(
        """async () => {
             const m = document.querySelector('meta[name="csrf-token"]');
             if (m) return m.content;
             const r = await fetch(location.pathname, {credentials:'same-origin'});
             return r.headers.get('csrf-token') || '';
           }""")
    if got:
        await page.evaluate("t => { window.__csrf = t }", got)
    return got


def explain_error(body):
    """楽天のエラー本文から、何をすればよいかを読み取る。

    コードだけ見ても分からないので、実際に踏んだものを訳す。
    """
    if not body:
        return ""
    if "IE0418" in body or "invalidAllMandatoryAttributes" in body:
        # 応答に足りない属性名が入っている
        m = re.findall(r'"([^"]+)"', body)
        names = [x for x in m if not x.isascii()]
        s = "、".join(dict.fromkeys(names)) if names else ""
        return (f"このジャンルの必須項目が足りません{('：' + s) if s else ''}。"
                "画面の「商品仕様」に入れてください")
    if "IE1002" in body or "Could not find the attribute" in body:
        return ("このジャンルに無い属性を送っています。"
                "雛形のSKUが同じジャンルのものか確認してください")
    if "IE0002" in body or "Unrecognized field" in body:
        return "送ってはいけない項目が入っています（読み取り専用の項目）"
    if "GA0001" in body or "Un-Authorised" in body:
        return "Compassのログインが切れています"
    if "GA0003" in body:
        return "呼びすぎです。少し時間を空けてください"
    return ""


async def send(page, method, path, body, label):
    """1本送る。429なら1回だけ待って再試行する。"""
    for attempt in (1, 2):
        r = await page.evaluate(JS_SEND, [method, path, body])
        if r["status"] != 429:
            break
        print(f"      429（混み合っています）。{RETRY_WAIT:.0f}秒待って再試行します")
        time.sleep(RETRY_WAIT)
    ok = 200 <= r["status"] < 300
    mark = "OK " if ok else "★NG"
    print(f"    {mark} {label}: {r['status']}")
    if not ok:
        print(f"        {r['body'][:300]}")
        # 楽天のエラーは原因が本文に入っている。読み解いて次の手を示す
        hint = explain_error(r["body"])
        if hint:
            print(f"        → {hint}")
    return {"label": label, "method": method, "path": path,
            "status": r["status"], "body": r["body"][:500], "ok": ok}


SEARCH_API = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701"


def fetch_genre_id(conf, item_code):
    """ライバル商品からジャンルIDを引く。

    楽天のジャンルIDは自分で調べると手間だが、参考にした商品から
    取れる。同じ商品を売るなら同じジャンルになるはずで、実際に
    売れている商品のジャンルなら間違いが少ない。

    楽天APIはIP制限がかかっていてサーバーからは呼べない（403
    CLIENT_IP_NOT_ALLOWED）。手元のPCからなら通るので、ここで引く。
    """
    app_id = conf.get("rakuten_app_id", "")
    access_key = conf.get("rakuten_access_key", "")
    if not app_id or not access_key:
        return None, "楽天APIのキーが設定されていません（setup.pyで登録）"

    q = urllib.parse.urlencode({
        "applicationId": app_id, "accessKey": access_key,
        "itemCode": item_code, "hits": 1, "format": "json"})
    try:
        with urllib.request.urlopen(f"{SEARCH_API}?{q}", timeout=30) as r:
            j = json.load(r)
    except urllib.error.HTTPError as e:
        return None, f"楽天から取れません（{e.code}）: {e.read().decode()[:150]}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"

    items = j.get("Items") or []
    if not items:
        return None, "その商品が見つかりません（削除された可能性）"
    item = items[0].get("Item") or items[0]
    gid = str(item.get("genreId") or "")
    return (gid, None) if gid else (None, "ジャンルIDが入っていません")


async def upload_draft_images(page, base, token, d, parent_folder):
    """預かっている画像をR-Cabinetへ上げて、URLを返す。

    SKUごとにフォルダを分ける運用なので、SKU名のフォルダを作って
    そこへ入れる。すでに上げてある画像はそのまま使う。
    """
    import upload_images as up

    imgs = api(base, f"/product-drafts/{d['id']}/images", token)
    if not imgs:
        return []

    done = [i for i in imgs if i.get("cabinet_url")]
    todo = [i for i in imgs if not i.get("cabinet_url")]
    urls = [i["cabinet_url"] for i in done]
    if not todo:
        return urls

    # SKU名のフォルダを用意する
    r = await page.evaluate(up.JS_GET, f"{up.CAB}/folders/get")
    if r["status"] != 200:
        raise RuntimeError(f"R-Cabinetのフォルダ一覧が取れません（{r['status']}）")
    folders = up.parse_folders(r["body"])
    same = [f for f in folders if f["name"] == d["sku"]]
    if same:
        folder_id = same[0]["id"]
    else:
        r = await page.evaluate(
            up.JS_POST_XML,
            [f"{up.CAB}/folder/insert", up.build_folder_xml(d["sku"], parent_folder)])
        m = re.search(r"<FolderId>(\d+)</FolderId>", r["body"])
        if r["status"] != 200 or not m:
            raise RuntimeError(f"フォルダを作れません: {r['body'][:200]}")
        folder_id = m.group(1)
        print(f"    フォルダを作りました: {d['sku']} → {folder_id}")

    for n, i in enumerate(todo):
        if n:
            time.sleep(1.5)
        full = api(base, f"/product-drafts/{d['id']}/images/{i['id']}/data", token)
        xml = up.build_xml(folder_id, os.path.splitext(i["file_name"])[0],
                           i["file_name"])
        r = await page.evaluate(
            up.JS_UPLOAD,
            [f"{up.CAB}/file/insert", xml, i["file_name"],
             full["data"], i.get("mime") or "image/jpeg"])
        info = up.parse_result(r["body"])
        if r["status"] != 200 or not info.get("url"):
            raise RuntimeError(
                f"画像 {i['file_name']} を上げられません: "
                f"{info.get('message') or r['body'][:200]}")
        print(f"    画像OK {i['file_name']} → {info['url']}")
        urls.append(info["url"])
        # サーバー側にも記録する。次回上げ直さないように
        api(base, f"/product-drafts/{d['id']}/images/{i['id']}/uploaded",
            token, "POST", {"cabinet_url": info["url"]})

    return urls


async def register_one(page, d, shop_url, dry_run, base=None, token=None,
                       parent_folder="", conf=None):
    """1商品を登録する。手順書どおり3本を順に送る。

    画面から預かった画像があれば、先にR-Cabinetへ上げる。商品より
    先に上げないと、商品側から参照できないため。
    """
    mn = d["sku"]

    # 雛形の商品を読む。送料・納期・属性など項目が多いので引き継ぐ
    tmpl = None
    if d.get("template_sku"):
        try:
            tmpl = await fetch_template(page, d["template_sku"], shop_url)
            print(f"    雛形: {d['template_sku']} から引き継ぎます")
        except Exception as e:
            return {"ok": False, "log": [], "error": f"雛形を読めません: {e}"}

    # ジャンルIDが空なら、参考にした商品から引く。楽天APIはIP制限が
    # あってサーバーからは呼べないので、ここで取る
    if not d.get("genre_id") and d.get("rival_item_code") and conf:
        gid, err = fetch_genre_id(conf, d["rival_item_code"])
        if gid:
            d = {**d, "genre_id": gid}
            print(f"    ジャンルID {gid}（ライバル商品から）")
        else:
            print(f"    ジャンルIDは取れませんでした: {err}")

    if not dry_run and base and token:
        try:
            urls = await upload_draft_images(page, base, token, d, parent_folder)
            if urls:
                d = {**d, "image_urls": (d.get("image_urls") or []) + urls}
        except Exception as e:
            return {"ok": False, "log": [], "error": f"画像の登録で失敗: {e}"}

    item_body = build_item_body(d, shop_url, tmpl)
    n_var = len(item_body["variants"])
    suffix = f"（{n_var}バリエーション）" if n_var > 1 else ""
    print(f"  {mn}: {d['rakuten_title'][:40]}{suffix}")

    calls = [
        ("PUT",
         f"/api/rms/v1/es/2.0/ext/items/manage-numbers/{mn}?shopUrl={shop_url}",
         item_body,
         "① 商品本体"),
        ("POST",
         "/api/rms/v1/es/2.1/inventories/bulk-upsert",
         # 全バリエーションぶん送る。入荷前なので0で作っておき、
         # 実際の在庫は既存の在庫連携が入れる
         {"inventories": [
             {"manageNumber": mn, "variantId": vid,
              # mode は必須。省略すると失敗する
              "quantity": 0, "mode": "ABSOLUTE"}
             for vid in item_body["variants"].keys()]},
         "② 在庫"),
        ("PUT",
         f"/api/rms/v1/es/2.0/categories/item-mappings/manage-numbers/{mn}",
         {"categoryIds": ["1"]},
         "③ 店舗内カテゴリ"),
    ]

    if dry_run:
        for method, path, body, label in calls:
            print(f"    [dry-run] {label}: {method} {path}")
            print(f"              {json.dumps(body, ensure_ascii=False)[:160]}")
        return {"ok": True, "log": [], "dry_run": True}

    log = []
    for i, (method, path, body, label) in enumerate(calls):
        if i:
            time.sleep(WAIT_BETWEEN_CALLS)
        r = await send(page, method, path, body, label)
        log.append(r)
        if not r["ok"]:
            # 商品本体が失敗したら在庫もカテゴリも意味がないので止める
            return {"ok": False, "log": log,
                    "error": f"{label}が{r['status']}で失敗しました"}
    return {"ok": True, "log": log}


def preflight(ready):
    """登録を始める前に、全部そろっているか確かめる。

    途中まで登録して失敗するのが一番後始末が大変なので、1件でも
    足りなければ1件も登録しない。
    """
    problems = []
    for d in ready:
        miss = []
        if not d.get("template_sku"):
            miss.append("雛形SKU（送料・納期・属性が入りません）")
        if not d.get("genre_id") and not d.get("template_sku"):
            miss.append("ジャンルID")
        if not (d.get("description_pc") or "").strip():
            miss.append("商品説明")
        if not (d.get("image_urls") or []) and not d.get("_has_images"):
            miss.append("画像")
        if miss:
            problems.append((d.get("sku") or f"id={d.get('id')}", miss))
    return problems


async def run(args):
    from playwright.async_api import async_playwright
    import compass

    conf = load_conf()
    base = args.base or conf.get("base") or DEFAULT_BASE
    token = args.token or conf.get("token", "")
    shop_url = args.shop_url or conf.get("shop_url", "")
    if not token:
        raise SystemExit("トークンがありません。setup.py を実行してください")
    if not shop_url:
        raise SystemExit("店舗URL名がありません。setup.py を実行してください")

    # 楽天APIのキーはサーバーが持っているので、そこから借りる。
    # 手元にも持たせると、変わったときに入れ直しが要るため
    if not conf.get("rakuten_app_id"):
        try:
            k = api(base, "/product-drafts/meta/rakuten-keys", token)
            conf["rakuten_app_id"] = k.get("app_id", "")
            conf["rakuten_access_key"] = k.get("access_key", "")
        except SystemExit:
            raise
        except Exception:
            pass

    print("登録待ちを取りに行きます…")
    j = api(base, f"/product-drafts/pending-register?limit={args.limit or 20}", token)
    ready, incomplete = j["ready"], j["incomplete"]
    print(f"  登録できる: {len(ready)}件 / 項目が足りない: {len(incomplete)}件")
    for d in incomplete:
        print(f"    - {d.get('sku') or '(SKUなし)'}: {'・'.join(d['missing'])}がありません")
    if not ready:
        print("登録するものがありません")
        return 0

    # 画像を預けているかどうかも見る（サーバーに預けた分は image_urls に入らない）
    for d in ready:
        try:
            d["_has_images"] = bool(
                api(base, f"/product-drafts/{d['id']}/images", token))
        except Exception:
            d["_has_images"] = False

    problems = preflight(ready)
    if problems and not args.force:
        print()
        print("足りないものがあるので、登録を始めません:")
        for sku, miss in problems:
            print(f"  {sku}: {'・'.join(miss)}")
        print()
        print("直してから、もう一度実行してください。")
        print("（承知のうえで進めるなら --force を付けます）")
        return 1

    async with async_playwright() as pw:
        ctx, page = await compass.open_compass(pw)
        await fetch_csrf(page)

        done = failed = 0
        for n, d in enumerate(ready):
            if n:
                time.sleep(WAIT_BETWEEN_ITEMS)
            try:
                r = await register_one(page, d, shop_url, args.dry_run,
                                       base, token,
                                       conf.get('cabinet_parent', '0'), conf)
            except Exception as e:
                r = {"ok": False, "log": [], "error": f"{type(e).__name__}: {e}"}
                print(f"    ★NG {e}")
            if args.dry_run:
                continue
            api(base, f"/product-drafts/{d['id']}/register-result", token, "POST",
                {"ok": r["ok"], "error": r.get("error"), "log": r["log"]})
            done += r["ok"]
            failed += (not r["ok"])

        await compass.close(ctx)

    if args.dry_run:
        print()
        print("--dry-run なので何も送っていません")
        return 0

    print()
    print(f"完了: 登録{done}件 / 失敗{failed}件")
    if done:
        print("楽天の検索に出るまで20〜30分かかります。すぐ確認したいときは")
        print(f"  https://soko.rms.rakuten.co.jp/{shop_url}/<商品管理番号>/")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="")
    ap.add_argument("--token", default="")
    ap.add_argument("--shop-url", default="", help="店舗URL名")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="足りないものがあっても進める")
    args = ap.parse_args()

    import asyncio
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
