"""配達が終わった便を見つけて、入荷まで進める。

楽天の荷物は就労支援の作業所に届く。先方から「届きました」と言われる
まで入荷を押していなかったので、在庫に立つのが遅れたり、そのまま
抜け落ちたりしていた。

タオタロウの追跡に「さいたま営業所（配達完了）2026-11-17 11:31:00」と
出るので、それを10分おきに見に行く。状態（state）は配達されても
「出荷済み」のままで、こちらが受領を押すまで「受け取り済み」に
ならないため使えない。

やること
  1. 配達完了を見つけたら LINE で知らせる
  2. 自動で入荷（在庫加算）する。できなかったときは理由も LINE で知らせる
  3. 配達済のまま入荷されない便は、既定2日で催促を1回だけ送る

自動入荷は order_settings.auto_receive_on_delivery で止められる。
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.settings import OrderSettings
from app.models.shipment_order import ShipmentOrder, ShipmentOrderItem
from app.services import secretary_line, taotaro

logger = logging.getLogger("delivery_watch")

JST = timezone(timedelta(hours=9))
# 何ページぶん見るか。1ページ50件で、入荷待ちの便はたいてい直近にある
PAGES = 3
PAGE_SIZE = 50


def _parse_jst(text: str):
    """「2026-11-17 11:31:00」を日本時間として読む。"""
    t = (text or "").strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S",
                "%Y/%m/%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(t[:len(fmt) + 4], fmt).replace(tzinfo=JST)
        except ValueError:
            continue
    return None


def _briefs() -> dict:
    """配送依頼No（sn）→ 一覧の1件。追跡まで入っている。"""
    out = {}
    for page in range(1, PAGES + 1):
        d = taotaro.list_send_orders(page=page, limit=PAGE_SIZE)
        for x in d.get("items") or []:
            for key in (x.get("sn"), x.get("sid")):
                k = str(key or "").strip()
                if k:
                    out.setdefault(k, x)
        if not d.get("has_more_pages"):
            break
    return out


def _label(order: ShipmentOrder) -> str:
    """便の呼び名。番号だけだとどれか分からないので2つとも出す。"""
    parts = [p for p in [order.tracking_no, order.order_no] if p]
    return "／".join(parts) or f"#{order.id}"


def _notify(text: str) -> None:
    """LINEへ1通。送れなくても見回りは止めない。"""
    if not secretary_line.is_configured():
        logger.info(f"[delivery-watch] LINE未設定のため送れません: {text}")
        return
    try:
        secretary_line.push(text)
    except Exception as e:
        logger.warning(f"[delivery-watch] LINEに送れませんでした: {e}")


def _blocked_reason(db: Session, order: ShipmentOrder) -> str:
    """自動で入荷できない理由。空なら進めてよい。"""
    items = (db.query(ShipmentOrderItem)
             .filter(ShipmentOrderItem.shipment_order_id == order.id).all())
    live = [i for i in items if not i.is_excluded]
    if not live:
        return "入荷する行がありません（すべて対象外）"
    unmatched = [i for i in live if not i.product_id]
    if unmatched:
        # 未照合のまま入れると、その行だけ落ちて数が合わなくなる。
        # どの行か分からないと直せないので、中国語名を添える
        names = "／".join((i.name_cn or "名前なし")[:20] for i in unmatched[:3])
        more = f" ほか{len(unmatched) - 3}行" if len(unmatched) > 3 else ""
        return f"商品マスタと未照合の行が{len(unmatched)}件あります（{names}{more}）"
    if not [i for i in live if not i.is_reflected]:
        return "すでに在庫へ反映済みです"
    return ""


async def _auto_receive(db: Session, order: ShipmentOrder) -> str:
    """入荷まで進める。戻り値は知らせる文章。"""
    from app.api.routes.shipment_orders import _apply_receive
    items = (db.query(ShipmentOrderItem)
             .filter(ShipmentOrderItem.shipment_order_id == order.id).all())
    r = await _apply_receive(db, order, items, mark_received=True)
    lines = [f"在庫に入れました：{r.get('updated', 0)}件"]
    if r.get("skipped"):
        rows = r.get("skipped_rows") or []
        why = "／".join(f"{x.get('name_cn') or '名前なし'}（{x.get('reason')}）"
                        for x in rows[:3])
        lines.append(f"⚠ 入らなかった行が{r['skipped']}件：{why}")
    if r.get("rms_push_fail"):
        lines.append(f"⚠ 楽天への在庫反映が{r['rms_push_fail']}件失敗しています")
    return "\n".join(lines)


async def tick(db: Session) -> dict:
    """1回ぶんの見回り。"""
    if not taotaro.is_configured():
        return {"skipped": "タオタロウのトークンが未設定"}

    st = db.query(OrderSettings).first()
    auto_on = True if st is None else bool(
        getattr(st, "auto_receive_on_delivery", True))
    remind_days = (getattr(st, "receive_remind_days", 2) or 2) if st else 2

    pending = (db.query(ShipmentOrder)
               .filter(ShipmentOrder.status != "received").all())
    if not pending:
        return {"pending": 0}

    try:
        briefs = _briefs()
    except Exception as e:
        logger.warning(f"[delivery-watch] 配送依頼の一覧が取れません: {e}")
        return {"error": str(e)}

    found, received, failed, reminded = 0, 0, 0, 0
    now = datetime.now(JST)

    for order in pending:
        # --- 新しく配達が終わった便を見つける ---
        if order.delivered_at is None:
            x = briefs.get(str(order.order_no or "").strip())
            if not x:
                continue
            when = _parse_jst(x.get("delivered_at") or "")
            # 一覧には追跡が付かないことがある。出荷済みの便だけ詳細を取り直す。
            # 全部に取りに行くと、入荷待ちの数だけAPIを叩くことになる
            if not when and int(x.get("state") or 0) in (2, 3):
                try:
                    d = taotaro.get_send_order(int(x.get("sid")))
                    when = _parse_jst(d.get("delivered_at") or "")
                except Exception as e:
                    logger.warning(
                        f"[delivery-watch] 追跡が取れません {x.get('sid')}: {e}")
            if not when:
                continue
            order.delivered_at = when
            db.commit()
            found += 1
            head = (f"📦 配達が終わりました\n{_label(order)}\n"
                    f"{when.strftime('%m/%d %H:%M')} 配達完了")

            if not auto_on:
                _notify(head + "\n\n自動入荷は切ってあります。画面から入荷を押してください")
                continue
            reason = _blocked_reason(db, order)
            if reason:
                order.auto_receive_note = reason
                db.commit()
                failed += 1
                _notify(head + f"\n\n⚠ 自動で入荷できませんでした\n{reason}\n"
                               "画面で直してから入荷を押してください")
                continue
            try:
                body = await _auto_receive(db, order)
                order.auto_receive_note = None
                db.commit()
                received += 1
                _notify(head + "\n\n" + body)
            except Exception as e:
                db.rollback()
                msg = str(e)[:200]
                order.auto_receive_note = f"自動入荷でエラー：{msg}"
                db.commit()
                failed += 1
                logger.warning(f"[delivery-watch] 自動入荷に失敗 {order.id}: {e}")
                _notify(head + f"\n\n⚠ 自動で入荷できませんでした\n{msg}\n"
                               "画面から入荷を押してください")
            continue

        # --- 配達済のまま入荷されていない便の催促。1便に1回だけ ---
        if order.reminded_at is not None:
            continue
        # DBによっては時差の付かない値が返る。付けてから比べる
        done = order.delivered_at
        if done.tzinfo is None:
            done = done.replace(tzinfo=JST)
        if done > now - timedelta(days=remind_days):
            continue
        days = (now - done).days
        order.reminded_at = now
        db.commit()
        reminded += 1
        _notify(f"⏰ 入荷がまだです\n{_label(order)}\n"
                f"{done.strftime('%m/%d %H:%M')} 配達完了"
                f"（{days}日経過）\n"
                + (order.auto_receive_note or "画面から入荷を押してください"))

    return {"pending": len(pending), "found": found, "received": received,
            "failed": failed, "reminded": reminded}
