"""書類が何月分かを、中身とファイル名から読み取る。

税理士へ渡す書類（ヤマトの請求書・RMS店舗別内訳書など）を入れるとき、
ファイルを開いて何月分か確かめるのが手間で、どれが何月分か分からなくなる。
よくある書き方を順に当てて、いちばん確かなものを使う。

  1. 「2026年10月分」「令和8年10月度」…その月（確か）
  2. 「請求期間 2026/10/01～2026/10/31」…期間の終わりの月（締め日の月）
  3. ファイル名の「202610」「2026-10」「2026年10月」…その月
  4. 「請求日／発行日 2026/11/05」だけ …発行月の前月（推定）
読めなければ None。呼び出し側で選んだ月を使う。
"""
import io
import re
from typing import Optional

_SEP = r"\s*[年/\-.]\s*"


def _y(s: str) -> Optional[int]:
    """西暦か令和を西暦にする。"""
    s = s.strip()
    m = re.match(r"(?:令和|R)\s*(\d{1,2}|元)", s)
    if m:
        n = 1 if m.group(1) == "元" else int(m.group(1))
        return 2018 + n
    if re.fullmatch(r"\d{4}", s):
        y = int(s)
        return y if 2000 <= y <= 2100 else None
    return None


_YEAR = r"(\d{4}|(?:令和|R)\s*(?:\d{1,2}|元))"


def _ym(y, m) -> Optional[str]:
    yy = _y(y) if isinstance(y, str) else y
    mm = int(m)
    if yy and 1 <= mm <= 12:
        return f"{yy}-{mm:02d}"
    return None


def _prev(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def text_of(content: bytes, filename: str) -> str:
    name = (filename or "").lower()
    if name.endswith(".pdf") or content[:4] == b"%PDF":
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                # 何月分かは1〜2ページ目に書いてある。全部読むと重い
                return "\n".join((p.extract_text() or "") for p in pdf.pages[:2])
        except Exception:
            return ""
    if name.endswith((".csv", ".txt")):
        for enc in ("utf-8-sig", "cp932"):
            try:
                return content[:200000].decode(enc)
            except UnicodeDecodeError:
                continue
    if name.endswith((".xlsx", ".xlsm")):
        try:
            from openpyxl import load_workbook
            wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
            out = []
            for ws in wb.worksheets[:2]:
                for i, row in enumerate(ws.iter_rows(values_only=True)):
                    if i > 40:
                        break
                    out.append(" ".join(str(v) for v in row if v is not None))
            return "\n".join(out)
        except Exception:
            return ""
    return ""


def _most(months: list) -> Optional[str]:
    from collections import Counter
    ms = [m for m in months if m]
    return Counter(ms).most_common(1)[0][0] if ms else None


def _rakuten(t: str) -> Optional[dict]:
    if "集約版帳票" in t.replace(" ", "") or "集 約 版 帳 票" in t:
        ym = _most([_ym(y, m) for y, m in re.findall(r"(\d{4})\s*年\s*(\d{1,2})\s*月", t)])
        if ym:
            return {"period": ym, "how": f"楽天の集約版帳票（課金月 {ym}）", "sure": True}
    if "店舗別内訳書No" in t or "店 舗 別 内 訳 書" in t:
        # 入金（■支払額）の期間は除き、■請求額 の明細の開始月だけを数える
        body = t.split("■請求額", 1)[1] if "■請求額" in t else t
        ym = _most([_ym(y, m) for y, m in re.findall(r"(\d{4})/(\d{1,2})/\d{1,2}\s*～", body)])
        if ym:
            return {"period": ym, "how": f"楽天の店舗別内訳書（精算対象期間 {ym}）", "sure": True}
    return None


def detect(content: bytes, filename: str, kind: str = "") -> dict:
    """{"period": "2026-10" | None, "how": 読み取った根拠, "sure": 確かか}

    kind="wholesale"（卸請求書）のときは、請求日をそのまま計上月にする。
    マレフィオーレは納品のたびに請求書を出していて、請求日＝到着日。
    ほかの請求書のように「前月分」と推定すると、まるごと1か月ずれる。
    """
    text = text_of(content, filename)
    t = re.sub(r"[ 　]+", " ", text)

    if kind == "wholesale":
        m = re.search(r"(?:請求日|発行日|作成日)\s*[:：]?\s*" + _YEAR + _SEP + r"(\d{1,2})", t)
        if m:
            ym = _ym(m.group(1), m.group(2))
            if ym:
                return {"period": ym, "how": f"{m.group(0).strip()}（納品日）", "sure": True}

    # 0. 楽天の店舗別内訳書・集約版帳票。利用した月（課金月）の約2か月後に届き、
    #    入金（支払額）の期間や翌月分の利用料も載るので、ほかの規則では月を外す。
    #    請求の明細でいちばん多い月＝何月分か、にする
    r = _rakuten(t)
    if r:
        return r

    # 1. ◯月分・◯月度
    m = re.search(_YEAR + r"\s*年\s*(\d{1,2})\s*月\s*(?:分|度|ご請求|請求)", t)
    if m:
        ym = _ym(m.group(1), m.group(2))
        if ym:
            return {"period": ym, "how": m.group(0).strip(), "sure": True}

    # 2. 期間（～で区切られた2つの日付）。締め日の月にする
    d = _YEAR + _SEP + r"(\d{1,2})" + _SEP.replace("年", "月") + r"(\d{1,2})\s*日?"
    m = re.search(d + r"\s*[～〜~\-ー－から]+\s*(?:" + _YEAR + _SEP + r")?(\d{1,2})"
                  + _SEP.replace("年", "月") + r"(\d{1,2})", t)
    if m:
        end_y = m.group(4) or m.group(1)
        ym = _ym(end_y, m.group(5))
        if ym:
            return {"period": ym, "how": m.group(0).strip(), "sure": True}

    # 3. ファイル名
    fn = filename or ""
    # 締め日が8桁で入っている名前（ヤマトの webseikyu_19675_20251031.pdf など）。
    # 中身の文字が読めないPDFでも、これで何月分か分かる。締め日の月にする
    m = re.search(r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])([0-3]\d)(?!\d)", fn)
    if m and 1 <= int(m.group(3)) <= 31:
        ym = _ym(m.group(1), m.group(2))
        if ym:
            return {"period": ym, "how": f"ファイル名の締め日 {m.group(1)}/{m.group(2)}/{m.group(3)}",
                    "sure": True}
    m = (re.search(r"(20\d{2})\s*年\s*(\d{1,2})\s*月", fn)
         or re.search(r"(20\d{2})[-_.]?(0[1-9]|1[0-2])(?!\d)", fn))
    if m:
        ym = _ym(m.group(1), m.group(2))
        if ym:
            return {"period": ym, "how": f"ファイル名「{fn}」", "sure": True}

    # 4. 請求日・発行日だけ。請求書はふつう翌月に出るので前月分と推定
    m = re.search(r"(?:請求日|発行日|作成日|請求書発行日)\s*[:：]?\s*" + _YEAR + _SEP + r"(\d{1,2})", t)
    if m:
        ym = _ym(m.group(1), m.group(2))
        if ym:
            return {"period": _prev(ym), "how": f"{m.group(0).strip()} の前月と推定", "sure": False}

    return {"period": None, "how": "読み取れませんでした" + ("" if text else "（文字の無いPDFか画像）"),
            "sure": False}
