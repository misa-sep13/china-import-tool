"""配達が終わった便を見つけて、取り込み・入荷まで進める。

楽天の荷物は就労支援の作業所に届く。先方から「届きました」と言われる
まで配送依頼を取り込んでいなかったので、在庫に立つのが遅れたり、
そのまま抜け落ちたりしていた。

見張るのはタオタロウの配送依頼そのもの。こちらの shipment_orders は
「取り込み＝入荷」で同時に作られるため、入荷待ちの行が残らず、
そこを見ていても何も見つからない（最初そう作って気づいた）。

判定は追跡の文言。状態（state）は配達されても「出荷済み」のままで、
こちらが受領を押すまで「受け取り済み」にならないので使えない。
  「さいたま営業所(配達完了)」      → 配達済
  「(配達は終了致しました。)」       → 配達済（日本郵便の言い方）
  「(配送委託業者ステータス更新 配達中)」→ まだ
  「本日、配達にお伺いする予定です」  → まだ

やること
  1. 配達完了を見つけたらLINEで知らせる
  2. 明細がすべて商品マスタと照合できたら、取り込んで入荷まで進める。
     できなかったときは理由もLINEで知らせ、画面にも残す
  3. 配達済のまま取り込まれない便は、既定2日で催促を1回だけ送る

自動入荷は order_settings.auto_receive_on_delivery で止められる。
覚えた状態は order_settings.delivery_watch にJSONで持つ（テーブルを
増やすほどのものではない。消えても次の巡回で入り直る）。
"""
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.settings import OrderSettings
from app.models.shipment_order import ShipmentOrder, ShipmentOrderItem
from app.services import secretary_line, taotaro

logger = logging.getLogger("delivery_watch")

JST = timezone(timedelta(hours=9))
# 何ページぶん見るか。1ページ50件
PAGES = 3
PAGE_SIZE = 50
# これより古い配達は相手にしない。Excelで取り込んでいた時代の便が
# 70件ほど残っていて、入れた初日にまとめて鳴ってしまうため
WINDOW_DAYS = 60
# 一覧に追跡が付かない便は詳細を取り直す。全部に行くと便の数だけ
# APIを叩くので、1回の巡回で見る数を区切る
DETAIL_MAX = 15


def _parse_jst(text: str):
    """「2026-11-17 11:31:00」を日本時間として読む。"""
    t = (text or "").strip().replace("T", " ").replace("Z", "")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S",
                "%Y/%m/%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(t[:len(fmt) + 4], fmt).replace(tzinfo=JST)
        except ValueError:
            continue
    return None


def _imported_keys(db: Session) -> set:
    """取り込み済みの便の見分け。

    配送依頼Noは、昔の取り込みでは sid（709053）、いまは sn（VIP…）が
    入っている。どちらでも当たるよう、両方を鍵にする。
    """
    keys = set()
    for a, b in db.query(ShipmentOrder.order_no,
                         ShipmentOrder.tracking_no).all():
        for v in (a, b):
            s = str(v or "").strip()
            if s:
                keys.add(s)
    return keys


def _notify(text: str) -> None:
    """LINEへ1通。送れなくても巡回は止めない。"""
    if not secretary_line.is_configured():
        logger.info(f"[delivery-watch] LINE未設定のため送れません: {text}")
        return
    try:
        secretary_line.push(text)
    except Exception as e:
        logger.warning(f"[delivery-watch] LINEに送れませんでした: {e}")


def _delivered_at(x: dict, allow_detail: list) -> str:
    """この便の配達完了日時。一覧に無ければ詳細を取り直す。"""
    got = x.get("delivered_at") or ""
    if got:
        return got
    # 出荷より手前の便は、まだ配達されようがない
    if int(x.get("state") or 0) not in (2, 3):
        return ""
    if not allow_detail:
        return ""
    allow_detail.pop()
    try:
        return taotaro.get_send_order(int(x.get("sid"))).get("delivered_at") or ""
    except Exception as e:
        logger.warning(f"[delivery-watch] 追跡が取れません {x.get('sid')}: {e}")
        return ""


async def _import_and_receive(db: Session, sid: int) -> tuple:
    """配送依頼を取り込んで入荷まで進める。

    戻り値は (知らせる文章, 止まった理由)。理由が入っていれば在庫は
    動かしていない。
    """
    from app.api.routes.shipment_orders import (_apply_receive, match_products)

    d = taotaro.send_order_shipment(sid)
    items = d.get("items") or []
    if not items:
        return "", "この配送依頼に明細がありません"

    m = match_products(items, db)
    unmatched = m.get("unmatched") or []
    if unmatched:
        # 未照合のまま入れると、その行だけ落ちて数が合わなくなる。
        # どの行か分からないと直せないので、中国語名を添える
        names = "／".join((u.get("name_cn") or "名前なし")[:18]
                          for u in unmatched[:3])
        more = f" ほか{len(unmatched) - 3}行" if len(unmatched) > 3 else ""
        return "", f"商品マスタと照合できない行が{len(unmatched)}件あります（{names}{more}）"

    order = ShipmentOrder(
        tracking_no=d.get("tracking_no") or "",
        order_no=d.get("order_no") or str(sid),
        shipped_date=d.get("shipped_date") or "",
        box_count=d.get("box_count") or 0,
        total_weight_kg=d.get("total_weight_kg") or 0,
        note="配達完了を見つけて自動で取り込みました",
        status="pending",
    )
    db.add(order)
    db.flush()
    rows = []
    for it in m.get("matched") or []:
        row = ShipmentOrderItem(
            shipment_order_id=order.id,
            product_id=it.get("product_id"),
            name_cn=it.get("name_cn", ""),
            color=it.get("color", ""),
            size=it.get("size", ""),
            buy_url=it.get("buy_url", ""),
            unit_price_cny=it.get("unit_price_cny", 0),
            qty=it.get("qty", 0),
            is_matched=True,
        )
        db.add(row)
        rows.append(row)
    db.commit()

    r = await _apply_receive(db, order, rows, mark_received=True)
    lines = [f"在庫に入れました：{r.get('updated', 0)}件"]
    if r.get("skipped"):
        why = "／".join(f"{x.get('name_cn') or '名前なし'}（{x.get('reason')}）"
                        for x in (r.get("skipped_rows") or [])[:3])
        lines.append(f"⚠ 入らなかった行が{r['skipped']}件：{why}")
    if r.get("rms_push_fail"):
        lines.append(f"⚠ 楽天への在庫反映が{r['rms_push_fail']}件失敗しています")
    return "\n".join(lines), ""


async def tick(db: Session) -> dict:
    """1回ぶんの巡回。"""
    if not taotaro.is_configured():
        return {"skipped": "タオタロウのトークンが未設定"}

    st = db.query(OrderSettings).first()
    if st is None:
        st = OrderSettings()
        db.add(st)
        db.commit()
        db.refresh(st)
    auto_on = bool(getattr(st, "auto_receive_on_delivery", True))
    remind_days = getattr(st, "receive_remind_days", 2) or 2
    try:
        state = json.loads(getattr(st, "delivery_watch", "") or "{}")
    except Exception:
        state = {}

    try:
        items = []
        for page in range(1, PAGES + 1):
            d = taotaro.list_send_orders(page=page, limit=PAGE_SIZE)
            items.extend(d.get("items") or [])
            if not d.get("has_more_pages"):
                break
    except Exception as e:
        logger.warning(f"[delivery-watch] 配送依頼の一覧が取れません: {e}")
        return {"error": str(e)}

    keys = _imported_keys(db)
    now = datetime.now(JST)
    budget = [None] * DETAIL_MAX
    found = received = failed = reminded = 0
    waiting = {}

    for x in items:
        sid = str(x.get("sid") or "").strip()
        sn = str(x.get("sn") or "").strip()
        if not sid:
            continue
        # 取り込み済み＝入荷済み。覚えていたものは落とす
        if sn in keys or sid in keys:
            state.pop(sid, None)
            continue
        # FBA宛はAmazonの荷物。楽天の在庫に入れてはいけないので触らない
        dest = taotaro.destination(x)
        if dest == "fba":
            state.pop(sid, None)
            continue
        when = _parse_jst(_delivered_at(x, budget))
        if not when or when < now - timedelta(days=WINDOW_DAYS):
            continue

        label = f"{sn or sid}（{x.get('order_count') or 0}注文）"
        head = (f"📦 配達が終わりました\n{label}\n"
                f"{when.strftime('%m/%d %H:%M')} 配達完了")
        prev = state.get(sid) or {}
        first = not prev

        if first:
            found += 1
            reason = ""
            if dest == "unknown":
                # 知らない受取人。楽天の荷物とはかぎらないので入れない
                reason = (f"受取人が見慣れません（{(x.get('consignee') or '空欄')[:30]}）。"
                          "楽天の荷物か確かめてから取り込んでください")
            elif not auto_on:
                reason = "自動入荷を切ってあります"
            body = ""
            if not reason and auto_on:
                try:
                    body, reason = await _import_and_receive(db, int(sid))
                except Exception as e:
                    db.rollback()
                    reason = f"取り込みでエラー：{str(e)[:160]}"
                    logger.warning(f"[delivery-watch] 自動入荷に失敗 {sid}: {e}")
            if reason:
                failed += 1
                state[sid] = {"sn": sn, "at": when.isoformat(),
                              "n": x.get("order_count") or 0, "why": reason,
                              "to": (x.get("consignee") or "")[:40]}
                _notify(head + f"\n\n⚠ 自動で入荷できませんでした\n{reason}\n"
                               "配送依頼タブから取り込んでください")
            else:
                received += 1
                state.pop(sid, None)
                _notify(head + "\n\n" + body)
                continue
        # --- 配達済のまま取り込まれていない便の催促。1便に1回だけ ---
        cur = state.get(sid)
        if not cur:
            continue
        waiting[sid] = cur
        if cur.get("remind"):
            continue
        if when > now - timedelta(days=remind_days):
            continue
        cur["remind"] = now.isoformat()
        reminded += 1
        _notify(f"⏰ まだ入荷が立っていません\n{label}\n"
                f"{when.strftime('%m/%d %H:%M')} 配達完了"
                f"（{(now - when).days}日経過）\n{cur.get('why') or ''}")

    st.delivery_watch = json.dumps(waiting, ensure_ascii=False)
    db.commit()
    return {"checked": len(items), "found": found, "received": received,
            "failed": failed, "reminded": reminded, "waiting": len(waiting)}


def waiting_list(db: Session) -> list:
    """配達済なのに取り込まれていない便。画面に出す。"""
    try:
        state = json.loads(
            getattr(db.query(OrderSettings).first(), "delivery_watch", "")
            or "{}")
    except Exception:
        return []
    out = []
    for sid, v in state.items():
        out.append({"sid": sid, "sn": v.get("sn") or sid,
                    "delivered_at": v.get("at"), "order_count": v.get("n"),
                    "consignee": v.get("to") or "",
                    "reason": v.get("why") or "", "reminded": v.get("remind")})
    out.sort(key=lambda r: r.get("delivered_at") or "", reverse=True)
    return out
