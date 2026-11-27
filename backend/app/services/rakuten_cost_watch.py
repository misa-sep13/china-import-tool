"""楽天の仕入管理（原価計算）を自動で進める。

これまでは、輸入許可書が届くたびに人が
  1. どの便の許可書かを探す
  2. タオタロウからインボイスを落とす
  3. 2つを突き合わせる
  4. 船便か航空便かを選ぶ
  5. SKUの照合を見る
  6. 計算して保存する
をやっていた。1〜4は機械で決められる（部品はもう揃っていた）。

  ・どの便か … /invoices/match-permit が貨物重量と箱数で当てる
  ・インボイス … /invoices/from-taotaro がAPIで落とす
  ・船か空か … インボイスのシート構成から推測した値が入っている
  ・SKU … URLと配送依頼の明細で照合済み

残るのは「当たらなかったSKU」と「検算が合わないとき」だけなので、
そこで止めて人に回す。黙って進めると、誤った原価が値付けと
発注判断に使われてしまう。

原価は利益に直に効くので、保存したあとに「前より大きく動いたSKU」を
並べて知らせる。
"""
import json
import logging
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.cost_history import CostHistory
from app.models.import_permit import ImportPermit
from app.models.settings import OrderSettings
from app.services import secretary_line

logger = logging.getLogger("rakuten_cost_watch")

JST = timezone(timedelta(hours=9))
# これより古い許可書は相手にしない。入れた初日に過去ぶんが動かないように
WINDOW_DAYS = 45
# 1回の巡回で見る許可書の数。便を当てるのにインボイスを何件か落とすので、
# まとめて走らせるとRenderの時間を使い切る
MAX_PER_TICK = 2
# 原価がこれ以上動いたら名指しで知らせる
BIG_MOVE = 0.3


def _notify(text: str) -> None:
    if not secretary_line.is_configured():
        logger.info(f"[cost-watch] LINE未設定のため送れません: {text}")
        return
    try:
        secretary_line.push(text)
    except Exception as e:
        logger.warning(f"[cost-watch] LINEに送れませんでした: {e}")


def _permit_label(p: ImportPermit) -> str:
    return f"{p.permit_date or '日付なし'} {p.permit_no or p.filename or f'#{p.id}'}"


def _already_saved(db: Session, invoice_no: str) -> bool:
    """この便の原価はもう保存してあるか。手でやったぶんも拾える。"""
    if not invoice_no:
        return False
    return db.query(CostHistory).filter(
        CostHistory.source == "rakuten",
        CostHistory.invoice_no == invoice_no).first() is not None


def _process(db: Session, permit: ImportPermit) -> tuple:
    """許可書1枚を処理する。戻り値は (知らせる文章, 止まった理由)。"""
    from app.api.routes.rakuten import (
        RakutenInvoiceIn, RakutenTaotaroInvoiceIn, _rakuten_build_cost_rows,
        rakuten_invoice_from_taotaro, rakuten_match_permit,
        rakuten_save_invoice, rakuten_stored_permit)
    from app.models.rakuten_product import RakutenProduct

    m = rakuten_match_permit(permit_id=permit.id, db=db)
    sid = m.get("best_sid")
    if not sid:
        near = ""
        for c in (m.get("candidates") or [])[:2]:
            near += f"\n・{c.get('sn') or c.get('sid')}（重量差 {c.get('weight_diff')}kg）"
        return "", ("どの便の許可書か決められませんでした。"
                    "画面で便を選んでください。" + (f"近いもの：{near}" if near else ""))

    # FBA宛の便はAmazonの商品。楽天のマスタにはほぼ無いので、検算（カバー率）で
    # 必ず止まる（2026-11-25 の 721710）。楽天の原価計算は飛ばし、Amazonの
    # 仕入管理で計算するよう1回だけ知らせる
    from app.services import taotaro
    try:
        if taotaro.destination(taotaro.get_send_order(int(sid))) == "fba":
            return (f"ℹ️ {_permit_label(permit)} はFBA宛の便（No.{sid}）でした。\n"
                    "Amazonの商品なので、楽天ではなく Amazon → 仕入管理 で原価を計算してください"), ""
    except Exception:
        pass

    parsed = rakuten_invoice_from_taotaro(
        RakutenTaotaroInvoiceIn(sid=int(sid)), db=db)
    invoice_no = parsed.get("invoice_no") or ""
    if _already_saved(db, invoice_no):
        return f"{invoice_no} はすでに保存済みでした", ""

    # 航空便はイレギュラー（急ぎの分だけ別便にする、通関料が無いなど）なので
    # 自動では進めない。数が少なく、まとめて1つの型に当てはまらない
    if (parsed.get("shipping_method") or "") == "air":
        return "", ("航空便なので自動では進めません。"
                    "画面から進めてください（通関料は無しです）")

    pm = rakuten_stored_permit(permit_id=permit.id, db=db)
    # ここまで来たものは船便。読めなかったときも船便として扱う（通関料あり）
    sea = True
    data = RakutenInvoiceIn(
        invoice_no=invoice_no,
        invoice_date=(permit.permit_date or ""),
        exchange_rate=float(pm.get("exchange_rate") or 0),
        domestic_freight=float(parsed.get("domestic_freight") or 0),
        international_freight=float(parsed.get("international_freight") or 0),
        import_tax_jpy=float(pm.get("import_tax_jpy") or 0),
        items=parsed.get("items") or [],
        permit_columns=pm.get("permit_columns") or [],
        box_data=parsed.get("box_data") or None,
        customs_fee_jpy=(parsed.get("customs_fee_sea_jpy") or 2000) if sea else 0,
    )
    if not data.exchange_rate:
        return "", "許可書から為替レートを読めませんでした"
    if not data.items:
        return "", "インボイスに明細がありません"

    # 商品マスタに当たらない行があるまま保存すると、その行に乗るはずの
    # 送料・関税が他の商品へ回り、全体の原価が水増しされる。
    #
    # 当たらなかった行は rows に入らず手前で落ちるので、rows を見ても
    # 見つからない。カバー率の unknown_indexes から引く。
    # これを見ていなかったせいで、知らせが「検算に失敗：カバー率」としか
    # 出ず、何を登録すればいいのか分からなかった（月子鞋142足の8行）
    calc = _rakuten_build_cost_rows(data, db)
    lost = [data.items[i] for i in (calc["coverage"].get("unknown_indexes") or [])
            if 0 <= i < len(data.items)]
    if lost:
        # 同じ商品が色・サイズで何行にも分かれる。名前でまとめて数える
        by_name: dict = {}
        for x in lost:
            key = (x.name_jp or x.name_cn or x.sku or "名前なし")[:24]
            by_name[key] = by_name.get(key, 0) + 1
        names = "\n".join(f"・{k}（{v}行）" for k, v in list(by_name.items())[:4])
        more = f"\nほか{len(by_name) - 4}種" if len(by_name) > 4 else ""
        rate = calc["coverage"].get("coverage_rate")
        return "", (f"商品マスタに無い明細が{len(lost)}行あります"
                    f"（カバー率{rate}%）\n{names}{more}\n"
                    "この商品を登録してから、もう一度進めてください")

    # 保存の前に、いまの原価を控えて動きを見る
    before = {}
    for r in calc["rows"]:
        p = r["product"]
        if p is not None:
            before[p.sku] = p.cost_jpy or 0

    try:
        res = rakuten_save_invoice(data, db=db)
    except HTTPException as e:
        d = e.detail if isinstance(e.detail, dict) else {"message": str(e.detail)}
        ng = "／".join(str(c.get("name") or c.get("label") or c)
                       for c in (d.get("failed") or [])[:3])
        return "", f"{d.get('message') or '保存できませんでした'}{('：' + ng) if ng else ''}"

    moved = []
    for sku, old in before.items():
        p = db.query(RakutenProduct).filter(RakutenProduct.sku == sku).first()
        new = (p.cost_jpy or 0) if p else 0
        if old and new and abs(new - old) / old >= BIG_MOVE:
            moved.append(f"{sku} ¥{round(old)}→¥{round(new)}")

    lines = [f"🧾 原価を計算しました\n{invoice_no}（{_permit_label(permit)}）",
             f"更新：楽天 {res.get('updated', 0)}件"
             + (f" / Amazon {res.get('updated_amazon')}件"
                if res.get("updated_amazon") else "")]
    if moved:
        lines.append("⚠ 大きく動いた原価\n" + "\n".join("・" + x for x in moved[:8]))
    return "\n".join(lines), ""


def tick(db: Session) -> dict:
    """1回ぶんの巡回。"""
    st = db.query(OrderSettings).first()
    if st is None:
        st = OrderSettings()
        db.add(st)
        db.commit()
        db.refresh(st)
    if not bool(getattr(st, "auto_cost_from_permit", True)):
        return {"skipped": "自動の原価計算を切ってあります"}
    try:
        state = json.loads(getattr(st, "cost_watch", "") or "{}")
    except Exception:
        state = {}

    cutoff = (datetime.now(JST) - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%d")
    permits = (db.query(ImportPermit)
               .filter(ImportPermit.kind == "permit")
               .order_by(ImportPermit.id.desc()).limit(40).all())
    done = failed = 0
    waiting = {}
    budget = MAX_PER_TICK

    for p in permits:
        key = str(p.id)
        if (p.permit_date or "") and p.permit_date < cutoff:
            continue
        # EMS（国際郵便）の課税通知書は、便の原価計算の対象ではない
        # （郵便で届いた分の関税・消費税。インボイスの便が無い）
        if (p.transport or "") == "ems":
            continue
        prev = state.get(key) or {}
        if prev.get("done"):
            continue
        # 便を重さで当てられずに止まった許可書は、許可書の名前から便を決められる
        # ようになったので、もう一度やり直す（2026-11-27）
        if prev.get("why", "").startswith("どの便の許可書か決められません") and not prev.get("retried"):
            prev = {}
            state[key] = {"retried": True}
        # 検算（カバー率）で止まったものは、FBA宛かどうかを見直すために1回だけやり直す
        if "カバー率" in prev.get("why", "") and not prev.get("fba_checked"):
            prev = {}
            state[key] = {"retried": True, "fba_checked": True}
        # 一度止まったものは、次の巡回で毎回やり直さない。
        # 人が直したら画面のボタンでもう一度動かせる
        if prev.get("why"):
            waiting[key] = prev
            continue
        if budget <= 0:
            break
        budget -= 1
        try:
            body, why = _process(db, p)
        except Exception as e:
            db.rollback()
            why, body = f"エラー：{str(e)[:160]}", ""
            logger.warning(f"[cost-watch] 許可書{p.id}でエラー: {e}")
        if why:
            failed += 1
            waiting[key] = {"label": _permit_label(p), "why": why,
                            "at": datetime.now(JST).isoformat(),
                            # やり直したあとにまた止まったものは、毎回は通知しない
                            "retried": bool((state.get(key) or {}).get("retried")),
                            "fba_checked": bool((state.get(key) or {}).get("fba_checked"))}
            _notify(f"🧾 原価を計算できませんでした\n{_permit_label(p)}\n\n{why}\n"
                    "楽天 → 仕入管理 から進めてください")
        else:
            done += 1
            state[key] = {"done": True}
            if body:
                _notify(body)

    for k, v in waiting.items():
        state[k] = v
    st.cost_watch = json.dumps(state, ensure_ascii=False)
    db.commit()
    return {"done": done, "failed": failed, "waiting": len(waiting)}


def waiting_list(db: Session) -> list:
    """自動で進められなかった許可書。画面に出す。"""
    try:
        state = json.loads(
            getattr(db.query(OrderSettings).first(), "cost_watch", "") or "{}")
    except Exception:
        return []
    out = [{"permit_id": int(k), "label": v.get("label") or "",
            "reason": v.get("why") or "", "at": v.get("at")}
           for k, v in state.items() if isinstance(v, dict) and v.get("why")]
    out.sort(key=lambda r: r.get("at") or "", reverse=True)
    return out


def retry(db: Session, permit_id: int) -> dict:
    """止まっていた許可書をもう一度試す。画面のボタンから。"""
    try:
        state = json.loads(
            getattr(db.query(OrderSettings).first(), "cost_watch", "") or "{}")
    except Exception:
        state = {}
    state.pop(str(permit_id), None)
    st = db.query(OrderSettings).first()
    st.cost_watch = json.dumps(state, ensure_ascii=False)
    db.commit()
    return tick(db)
