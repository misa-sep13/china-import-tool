"""手元の画像をR-Cabinetへ上げる。

Compassは楽天の旧Cabinet APIを es/1.0/cabinet/ で中継している
（実測: usage/get・folders/get が200、file/insert が405＝POST待ち）。
商品APIと同じくログイン済みのブラウザから送るので、APIキーは要らない。

旧Cabinet APIはXMLでやりとりする。multipart/form-data の
  file  … 画像そのもの
  xml   … <request>…</request>
の2つを送る形。

使い方:
  python upload_images.py --list                     # フォルダ一覧を見る
  python upload_images.py --folder 12345 画像1.jpg 画像2.jpg
  python upload_images.py --folder 12345 --dir C:\\画像フォルダ
"""
import argparse
import base64
import json
import os
import re
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CONF = os.path.join(os.path.expanduser("~"), ".rakuten_register.json")
CAB = "/api/rms/v1/es/1.0/cabinet"
EXTS = (".jpg", ".jpeg", ".png", ".gif")

# 連続で叩くと弾かれる。商品登録と同じくらい間を空ける
WAIT = 1.5


JS_GET = r"""
async (path) => {
  const m = document.querySelector('meta[name="csrf-token"]');
  const token = m ? m.content : (window.__csrf || '');
  return await new Promise((resolve) => {
    const x = new XMLHttpRequest();
    x.open('GET', path, true);
    if (token) x.setRequestHeader('X-CSRF-Token', token);
    x.onload = () => resolve({ status: x.status, body: x.responseText });
    x.onerror = () => resolve({ status: 0, body: 'ネットワークエラー' });
    x.send(null);
  });
}
"""

# 画像はmultipartで送る。JSON化できないので、base64で渡して
# ブラウザ側でバイナリに戻す
JS_UPLOAD = r"""
async ([path, xml, fileName, b64, mime]) => {
  const m = document.querySelector('meta[name="csrf-token"]');
  const token = m ? m.content : (window.__csrf || '');

  const bin = atob(b64);
  const buf = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);

  const fd = new FormData();
  fd.append('xml', xml);
  fd.append('file', new Blob([buf], { type: mime }), fileName);

  return await new Promise((resolve) => {
    const x = new XMLHttpRequest();
    x.open('POST', path, true);
    if (token) x.setRequestHeader('X-CSRF-Token', token);
    // Content-Type は指定しない。FormDataがboundary付きで設定する
    x.onload = () => resolve({ status: x.status, body: x.responseText.slice(0, 1200) });
    x.onerror = () => resolve({ status: 0, body: 'ネットワークエラー' });
    x.send(fd);
  });
}
"""


def parse_folders(xml):
    """フォルダ一覧のXMLから、IDと名前とパスを拾う。"""
    out = []
    for block in re.findall(r"<folder>(.*?)</folder>", xml, re.S):
        def pick(tag):
            m = re.search(rf"<{tag}>(.*?)</{tag}>", block, re.S)
            return (m.group(1).strip() if m else "")
        out.append({"id": pick("FolderId"), "name": pick("FolderName"),
                    "path": pick("FolderPath"),
                    "files": pick("FileCount")})
    return out


def parse_result(xml):
    """アップロード結果のXMLから、状態とファイルのパスを拾う。"""
    def pick(tag):
        m = re.search(rf"<{tag}>(.*?)</{tag}>", xml, re.S)
        return (m.group(1).strip() if m else "")
    return {"status": pick("systemStatus") or pick("resultCode"),
            "message": pick("message"),
            "fileId": pick("FileId"),
            "url": pick("FileUrl") or pick("FilePath")}


JS_POST_XML = r"""
async ([path, xml]) => {
  const m = document.querySelector('meta[name="csrf-token"]');
  const token = m ? m.content : (window.__csrf || '');
  const fd = new FormData();
  fd.append('xml', xml);
  return await new Promise((resolve) => {
    const x = new XMLHttpRequest();
    x.open('POST', path, true);
    if (token) x.setRequestHeader('X-CSRF-Token', token);
    x.onload = () => resolve({ status: x.status, body: x.responseText.slice(0, 1200) });
    x.onerror = () => resolve({ status: 0, body: 'ネットワークエラー' });
    x.send(fd);
  });
}
"""


def build_folder_xml(name, parent_id):
    """フォルダ作成のXML。"""
    safe = re.sub(r"[<>&]", "", name)[:50]
    return ("<request><folderInsertRequest><folder>"
            f"<folderName>{safe}</folderName>"
            f"<folderParentId>{parent_id}</folderParentId>"
            "</folder></folderInsertRequest></request>")


def build_xml(folder_id, name, file_name):
    """アップロード用のXML。旧Cabinet APIの形式。"""
    # 名前に < > & が入るとXMLが壊れるので落としておく
    safe = re.sub(r"[<>&]", "", name)[:50]
    return ("<request><fileInsertRequest><file>"
            f"<fileName>{safe}</fileName>"
            f"<folderId>{folder_id}</folderId>"
            "<filePath></filePath>"
            "<overWrite>false</overWrite>"
            "</file></fileInsertRequest></request>")


async def run(args):
    from playwright.async_api import async_playwright
    import compass

    # 送る画像を集める
    files = []
    if args.dir:
        for n in sorted(os.listdir(args.dir)):
            if n.lower().endswith(EXTS):
                files.append(os.path.join(args.dir, n))
    files += [f for f in args.files if os.path.exists(f)]
    missing = [f for f in args.files if not os.path.exists(f)]
    for f in missing:
        print(f"  ★ 見つかりません: {f}")

    if not args.list and not files:
        raise SystemExit("送る画像がありません。ファイル名か --dir を指定してください")

    async with async_playwright() as pw:
        ctx, page = await compass.open_compass(pw)
        await compass.csrf_token(page)

        # フォルダ一覧
        r = await page.evaluate(JS_GET, f"{CAB}/folders/get")
        if r["status"] != 200:
            await compass.close(ctx)
            raise SystemExit(f"フォルダ一覧が取れませんでした（{r['status']}）")
        folders = parse_folders(r["body"])

        # フォルダを作る。SKUごとに分ける運用なので、新商品のたびに
        # Compassの画面で作らずに済むようにする
        if args.new_folder:
            parent = args.parent or "0"
            same = [f for f in folders if f["name"] == args.new_folder]
            if same:
                print(f"  同じ名前のフォルダがすでにあります: {same[0]['id']}")
                args.folder = same[0]["id"]
            else:
                r = await page.evaluate(
                    JS_POST_XML,
                    [f"{CAB}/folder/insert", build_folder_xml(args.new_folder, parent)])
                info = parse_result(r["body"])
                new_id = re.search(r"<FolderId>(\d+)</FolderId>", r["body"])
                if r["status"] == 200 and new_id:
                    args.folder = new_id.group(1)
                    print(f"  フォルダを作りました: {args.new_folder} → {args.folder}")
                else:
                    await compass.close(ctx)
                    raise SystemExit(
                        f"フォルダを作れませんでした（{r['status']}）: "
                        f"{info.get('message') or r['body'][:200]}")

        if args.list or not args.folder:
            print()
            print("R-Cabinetのフォルダ:")
            for f in folders:
                print(f"  {f['id']:>10}  {f['name']}  （{f['files']}件）  {f['path']}")
            print()
            if args.list:
                input("  … Enterで終了: ")
                await compass.close(ctx)
                return 0
            print("--folder にフォルダIDを指定して、もう一度実行してください")
            input("  … Enterで終了: ")
            await compass.close(ctx)
            return 1

        print()
        print(f"フォルダ {args.folder} へ {len(files)}枚 上げます")
        print()
        results = []
        for i, path in enumerate(files):
            if i:
                time.sleep(WAIT)
            name = os.path.basename(path)
            with open(path, "rb") as fp:
                data = fp.read()
            mime = ("image/png" if name.lower().endswith(".png")
                    else "image/gif" if name.lower().endswith(".gif")
                    else "image/jpeg")
            b64 = base64.b64encode(data).decode()
            xml = build_xml(args.folder, os.path.splitext(name)[0], name)

            if args.dry_run:
                print(f"  [dry-run] {name}（{len(data)//1024}KB）")
                continue

            r = await page.evaluate(
                JS_UPLOAD, [f"{CAB}/file/insert", xml, name, b64, mime])
            info = parse_result(r["body"])
            ok = r["status"] == 200 and info["status"] in ("OK", "")
            print(f"  {'OK ' if ok else '★NG'} {name}"
                  f"  {info.get('url') or info.get('message') or r['body'][:120]}")
            results.append({"file": name, "ok": ok, **info})

        await compass.close(ctx)

    if args.dry_run:
        print()
        print("--dry-run なので何も送っていません")
        return 0

    ok = sum(1 for r in results if r["ok"])
    print()
    print(f"完了: {ok}枚 / 失敗 {len(results) - ok}枚")
    if ok:
        print()
        print("商品に使うURLは、この形になります:")
        for r in results:
            if r["ok"] and r.get("url"):
                print(f"  {r['url']}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", help="上げる画像ファイル")
    ap.add_argument("--dir", default="", help="フォルダごと上げる")
    ap.add_argument("--folder", default="", help="R-CabinetのフォルダID")
    ap.add_argument("--list", action="store_true", help="フォルダ一覧を見るだけ")
    ap.add_argument("--new-folder", default="",
                    help="このフォルダを作ってから上げる（SKU名など）")
    ap.add_argument("--parent", default="",
                    help="親フォルダのID。既定は基本フォルダ直下")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    import asyncio
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
