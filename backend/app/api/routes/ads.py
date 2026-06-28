from fastapi import APIRouter, Query, HTTPException
from app.core.database import SessionLocal
from app.models.ads import (
    AdsCampaign, AdsAdGroup, AdsKeyword, AdsTarget, AdsSearchTerm, AdsSyncLog,
)
from datetime import datetime, timezone, timedelta
import threading, uuid, logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ads", tags=["ads"])

_jobs: dict = {}
_jobs_lock = threading.Lock()


def _update_job(job_id: str, **kw):
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id].update(kw)


def _parse_report_date(value: str, field_name: str):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{field_name}はYYYY-MM-DDで指定してください")


def _resolve_report_range(days: int, start_date: str = None, end_date: str = None):
    if start_date or end_date:
        if not start_date or not end_date:
            raise HTTPException(status_code=400, detail="start_dateとend_dateは両方指定してください")
        start = _parse_report_date(start_date, "start_date")
        end = _parse_report_date(end_date, "end_date")
        if end < start:
            raise HTTPException(status_code=400, detail="end_dateはstart_date以降にしてください")
        report_days = (end - start).days + 1
        if report_days > 90:
            raise HTTPException(status_code=400, detail="取得期間は90日以内にしてください")
        return start.isoformat(), end.isoformat(), report_days

    end = (datetime.utcnow() - timedelta(days=1)).date()
    start = end - timedelta(days=days - 1)
    return start.isoformat(), end.isoformat(), days


def _report_metric(row: dict, name: str, attribution_days: int):
    for key in (f"{name}{attribution_days}d", f"{name}30d", f"{name}14d", f"{name}7d"):
        value = row.get(key)
        if value is not None and value != "":
            return value
    return 0


def _run_ads_sync(
    job_id: str,
    days: int,
    report_start_date: str,
    report_end_date: str,
    attribution_days: int,
):
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "running",
            "progress": f"{report_start_date}〜{report_end_date} 開始",
            "error": None,
        }

    db = SessionLocal()
    sync_log = AdsSyncLog(
        job_id=job_id,
        sync_type=f"full:{report_start_date}:{report_end_date}:attr{attribution_days}d",
        status="started",
    )
    db.add(sync_log)
    db.commit()
    db.refresh(sync_log)

    total_fetched = 0
    total_upserted = 0
    skipped = 0

    try:
        from app.services.amazon_api import (
            fetch_sp_campaigns, fetch_sp_ad_groups, fetch_sp_keywords,
            fetch_sp_targets, fetch_campaign_report, fetch_targeting_report,
            fetch_search_term_report, parse_campaign_name,
        )

        now = datetime.now(timezone.utc)

        # 1. キャンペーン取得・保存
        _update_job(job_id, progress="キャンペーン取得中")
        campaigns = fetch_sp_campaigns()
        total_fetched += len(campaigns)
        for c in campaigns:
            cid = str(c.get("campaignId", ""))
            if not cid:
                logger.warning("Skipping campaign with empty campaignId: %s", c.get("name", "?"))
                skipped += 1
                continue
            name = c.get("name", "")
            campaign_type, parent_asin = parse_campaign_name(name)
            existing = db.query(AdsCampaign).filter(AdsCampaign.campaign_id == cid).first()
            if existing:
                existing.name = name
                existing.campaign_type = campaign_type
                existing.parent_asin = parent_asin
                existing.state = c.get("state")
                existing.targeting_type = c.get("targetingType")
                existing.budget_amount = c.get("budget", {}).get("budget")
                existing.budget_type = c.get("budget", {}).get("budgetType")
                existing.start_date = c.get("startDate")
                existing.end_date = c.get("endDate")
                existing.bidding_strategy = c.get("dynamicBidding", {}).get("strategy")
                existing.synced_at = now
            else:
                db.add(AdsCampaign(
                    campaign_id=cid, name=name,
                    campaign_type=campaign_type, parent_asin=parent_asin,
                    state=c.get("state"),
                    targeting_type=c.get("targetingType"),
                    budget_amount=c.get("budget", {}).get("budget"),
                    budget_type=c.get("budget", {}).get("budgetType"),
                    start_date=c.get("startDate"),
                    end_date=c.get("endDate"),
                    bidding_strategy=c.get("dynamicBidding", {}).get("strategy"),
                    synced_at=now,
                ))
                total_upserted += 1
        db.commit()
        logger.info("Campaigns: fetched=%d, skipped=%d", len(campaigns), skipped)

        # 2. 広告グループ取得・保存
        _update_job(job_id, progress="広告グループ取得中")
        ad_groups = fetch_sp_ad_groups()
        total_fetched += len(ad_groups)
        ag_skipped = 0
        for ag in ad_groups:
            agid = str(ag.get("adGroupId", ""))
            if not agid:
                logger.warning("Skipping adGroup with empty adGroupId")
                ag_skipped += 1
                continue
            existing = db.query(AdsAdGroup).filter(AdsAdGroup.ad_group_id == agid).first()
            if existing:
                existing.campaign_id = str(ag.get("campaignId", ""))
                existing.name = ag.get("name", "")
                existing.state = ag.get("state")
                existing.default_bid = ag.get("defaultBid")
                existing.synced_at = now
            else:
                db.add(AdsAdGroup(
                    ad_group_id=agid,
                    campaign_id=str(ag.get("campaignId", "")),
                    name=ag.get("name", ""),
                    state=ag.get("state"),
                    default_bid=ag.get("defaultBid"),
                    synced_at=now,
                ))
                total_upserted += 1
        skipped += ag_skipped
        db.commit()
        logger.info("AdGroups: fetched=%d, skipped=%d", len(ad_groups), ag_skipped)

        # 3. キーワード取得・保存
        _update_job(job_id, progress="キーワード取得中")
        keywords = fetch_sp_keywords()
        total_fetched += len(keywords)
        kw_skipped = 0
        for kw in keywords:
            kwid = str(kw.get("keywordId", ""))
            if not kwid:
                logger.warning("Skipping keyword with empty keywordId")
                kw_skipped += 1
                continue
            existing = db.query(AdsKeyword).filter(AdsKeyword.keyword_id == kwid).first()
            if existing:
                existing.campaign_id = str(kw.get("campaignId", ""))
                existing.ad_group_id = str(kw.get("adGroupId", ""))
                existing.keyword_text = kw.get("keywordText", "")
                existing.match_type = kw.get("matchType")
                existing.state = kw.get("state")
                existing.bid = kw.get("bid")
                existing.synced_at = now
            else:
                db.add(AdsKeyword(
                    keyword_id=kwid,
                    campaign_id=str(kw.get("campaignId", "")),
                    ad_group_id=str(kw.get("adGroupId", "")),
                    keyword_text=kw.get("keywordText", ""),
                    match_type=kw.get("matchType"),
                    state=kw.get("state"),
                    bid=kw.get("bid"),
                    synced_at=now,
                ))
                total_upserted += 1
        skipped += kw_skipped
        db.commit()
        logger.info("Keywords: fetched=%d, skipped=%d", len(keywords), kw_skipped)

        # 4. ターゲット取得・保存
        _update_job(job_id, progress="ターゲット取得中")
        targets = fetch_sp_targets()
        total_fetched += len(targets)
        tgt_skipped = 0
        for t in targets:
            tid = str(t.get("targetId", ""))
            if not tid:
                logger.warning("Skipping target with empty targetId")
                tgt_skipped += 1
                continue
            expression_list = t.get("expression", [])
            expression_type = expression_list[0].get("type") if expression_list else None
            expression_val = expression_list[0].get("value") if expression_list else None
            resolved_asin = expression_val if expression_type == "asinSameAs" else None

            existing = db.query(AdsTarget).filter(AdsTarget.target_id == tid).first()
            if existing:
                existing.campaign_id = str(t.get("campaignId", ""))
                existing.ad_group_id = str(t.get("adGroupId", ""))
                existing.expression_type = expression_type
                existing.expression = str(expression_list)
                existing.resolved_asin = resolved_asin
                existing.state = t.get("state")
                existing.bid = t.get("bid")
                existing.synced_at = now
            else:
                db.add(AdsTarget(
                    target_id=tid,
                    campaign_id=str(t.get("campaignId", "")),
                    ad_group_id=str(t.get("adGroupId", "")),
                    expression_type=expression_type,
                    expression=str(expression_list),
                    resolved_asin=resolved_asin,
                    state=t.get("state"),
                    bid=t.get("bid"),
                    synced_at=now,
                ))
                total_upserted += 1
        skipped += tgt_skipped
        db.commit()
        logger.info("Targets: fetched=%d, skipped=%d", len(targets), tgt_skipped)

        # 期間指定を切り替えた時に前回同期の実績が混ざらないようにする。
        db.query(AdsCampaign).update({
            AdsCampaign.impressions: 0,
            AdsCampaign.clicks: 0,
            AdsCampaign.cost: 0,
            AdsCampaign.orders: 0,
            AdsCampaign.sales: 0,
        }, synchronize_session=False)
        db.query(AdsKeyword).update({
            AdsKeyword.impressions: 0,
            AdsKeyword.clicks: 0,
            AdsKeyword.cost: 0,
            AdsKeyword.orders: 0,
            AdsKeyword.sales: 0,
            AdsKeyword.acos: None,
            AdsKeyword.cpc: None,
            AdsKeyword.report_days: days,
        }, synchronize_session=False)
        db.query(AdsTarget).update({
            AdsTarget.impressions: 0,
            AdsTarget.clicks: 0,
            AdsTarget.cost: 0,
            AdsTarget.orders: 0,
            AdsTarget.sales: 0,
            AdsTarget.acos: None,
            AdsTarget.cpc: None,
            AdsTarget.report_days: days,
        }, synchronize_session=False)
        db.commit()

        # 5. キャンペーンレポート → パフォーマンス列更新
        _update_job(job_id, progress="キャンペーンレポート取得中")
        camp_report = fetch_campaign_report(
            days=days,
            start_date=report_start_date,
            end_date=report_end_date,
            attribution_days=attribution_days,
        )
        rpt_skipped = 0
        for row in camp_report:
            cid = str(row.get("campaignId", ""))
            if not cid:
                rpt_skipped += 1
                continue
            camp = db.query(AdsCampaign).filter(AdsCampaign.campaign_id == cid).first()
            if camp:
                camp.impressions = int(row.get("impressions") or 0)
                camp.clicks = int(row.get("clicks") or 0)
                camp.cost = float(row.get("cost") or 0)
                camp.orders = int(_report_metric(row, "purchases", attribution_days) or 0)
                camp.sales = float(_report_metric(row, "sales", attribution_days) or 0)
        db.commit()
        logger.info("Campaign report: rows=%d, skipped=%d", len(camp_report), rpt_skipped)

        # 6. ターゲティングレポート → KW/ターゲットのパフォーマンス列更新
        # レポートにkeywordId/targetIdは含まれない。keyword_text + campaign_id + ad_group_idでマッチ
        _update_job(job_id, progress="ターゲティングレポート取得中")
        targeting_report = fetch_targeting_report(
            days=days,
            start_date=report_start_date,
            end_date=report_end_date,
            attribution_days=attribution_days,
        )
        tgt_matched = 0
        tgt_unmatched = 0
        for row in targeting_report:
            impressions = int(row.get("impressions") or 0)
            clicks = int(row.get("clicks") or 0)
            cost = float(row.get("cost") or 0)
            orders = int(_report_metric(row, "purchases", attribution_days) or 0)
            sales = float(_report_metric(row, "sales", attribution_days) or 0)
            acos = (cost / sales * 100) if sales > 0 else None
            cpc = (cost / clicks) if clicks > 0 else None

            cid = str(row.get("campaignId", ""))
            agid = str(row.get("adGroupId", ""))
            kw_type = row.get("keywordType", "")
            targeting_text = row.get("targeting", "")

            matched = False
            if kw_type == "BROAD" or kw_type == "PHRASE" or kw_type == "EXACT":
                kw = db.query(AdsKeyword).filter(
                    AdsKeyword.campaign_id == cid,
                    AdsKeyword.ad_group_id == agid,
                    AdsKeyword.keyword_text == targeting_text,
                ).first()
                if kw:
                    kw.impressions = impressions
                    kw.clicks = clicks
                    kw.cost = cost
                    kw.orders = orders
                    kw.sales = sales
                    kw.acos = acos
                    kw.cpc = cpc
                    kw.report_days = days
                    matched = True
            else:
                tgts = db.query(AdsTarget).filter(
                    AdsTarget.campaign_id == cid,
                    AdsTarget.ad_group_id == agid,
                ).all()
                for tgt in tgts:
                    expr_list = tgt.expression or ""
                    if targeting_text in expr_list or tgt.expression_type == targeting_text:
                        tgt.impressions = (tgt.impressions or 0) + impressions
                        tgt.clicks = (tgt.clicks or 0) + clicks
                        tgt.cost = (tgt.cost or 0) + cost
                        tgt.orders = (tgt.orders or 0) + orders
                        tgt.sales = (tgt.sales or 0) + sales
                        total_cost = tgt.cost or 0
                        total_sales = tgt.sales or 0
                        total_clicks = tgt.clicks or 0
                        tgt.acos = (total_cost / total_sales * 100) if total_sales > 0 else None
                        tgt.cpc = (total_cost / total_clicks) if total_clicks > 0 else None
                        tgt.report_days = days
                        matched = True
                        break

            if matched:
                tgt_matched += 1
            else:
                tgt_unmatched += 1
        db.commit()
        logger.info("Targeting report: rows=%d, matched=%d, unmatched=%d", len(targeting_report), tgt_matched, tgt_unmatched)

        # 7. 検索語句レポート → 入れ替え保存
        _update_job(job_id, progress="検索語句レポート取得中")
        search_terms = fetch_search_term_report(
            days=days,
            start_date=report_start_date,
            end_date=report_end_date,
            attribution_days=attribution_days,
        )
        db.query(AdsSearchTerm).filter(
            AdsSearchTerm.report_start_date == report_start_date,
            AdsSearchTerm.report_end_date == report_end_date,
        ).delete(synchronize_session=False)
        st_skipped = 0
        for row in search_terms:
            cid = str(row.get("campaignId", ""))
            if not cid:
                st_skipped += 1
                continue
            clicks = int(row.get("clicks") or 0)
            cost = float(row.get("cost") or 0)
            sales = float(_report_metric(row, "sales", attribution_days) or 0)
            db.add(AdsSearchTerm(
                campaign_id=cid,
                ad_group_id=str(row.get("adGroupId", "")),
                keyword_id=str(row.get("keyword", "")),
                search_term=row.get("searchTerm", ""),
                match_type=row.get("matchType"),
                impressions=int(row.get("impressions") or 0),
                clicks=clicks,
                cost=cost,
                orders=int(_report_metric(row, "purchases", attribution_days) or 0),
                sales=sales,
                acos=(cost / sales * 100) if sales > 0 else None,
                cpc=(cost / clicks) if clicks > 0 else None,
                report_start_date=report_start_date,
                report_end_date=report_end_date,
                synced_at=now,
            ))
            total_upserted += 1
        total_fetched += len(search_terms)
        skipped += st_skipped
        db.commit()
        logger.info("Search terms: rows=%d, skipped=%d", len(search_terms), st_skipped)

        sync_log.status = "completed"
        sync_log.records_fetched = total_fetched
        sync_log.records_upserted = total_upserted
        sync_log.completed_at = datetime.now(timezone.utc)
        db.commit()

        _update_job(job_id, status="done", progress=f"完了 (取得{total_fetched}, skip{skipped})")

    except Exception as e:
        logger.exception("ads sync failed")
        sync_log.status = "failed"
        sync_log.error_message = str(e)[:500]
        sync_log.completed_at = datetime.now(timezone.utc)
        try:
            db.commit()
        except Exception:
            db.rollback()
        _update_job(job_id, status="error", error=str(e)[:300])
    finally:
        db.close()


@router.post("/sync/start")
def start_ads_sync(
    days: int = Query(default=30, ge=1, le=90),
    start_date: str = Query(default=None),
    end_date: str = Query(default=None),
    attribution_days: int = Query(default=30),
):
    if attribution_days not in (1, 7, 14, 30):
        raise HTTPException(status_code=400, detail="attribution_daysは1, 7, 14, 30のいずれかを指定してください")
    report_start_date, report_end_date, report_days = _resolve_report_range(days, start_date, end_date)
    job_id = str(uuid.uuid4())
    t = threading.Thread(
        target=_run_ads_sync,
        args=(job_id, report_days, report_start_date, report_end_date, attribution_days),
        daemon=True,
    )
    t.start()
    return {
        "job_id": job_id,
        "start_date": report_start_date,
        "end_date": report_end_date,
        "days": report_days,
        "attribution_days": attribution_days,
    }


@router.get("/sync/status/{job_id}")
def ads_sync_status(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job:
        return job
    db = SessionLocal()
    try:
        log = db.query(AdsSyncLog).filter(AdsSyncLog.job_id == job_id).first()
        if not log:
            return {"status": "not_found"}
        return {
            "status": "done" if log.status == "completed" else ("error" if log.status == "failed" else "running"),
            "progress": log.status,
            "error": log.error_message,
        }
    finally:
        db.close()


@router.get("/sync-logs")
def get_sync_logs():
    db = SessionLocal()
    try:
        logs = db.query(AdsSyncLog).order_by(AdsSyncLog.id.desc()).limit(20).all()
        return [
            {
                "id": l.id,
                "job_id": l.job_id,
                "sync_type": l.sync_type,
                "status": l.status,
                "records_fetched": l.records_fetched,
                "records_upserted": l.records_upserted,
                "error_message": l.error_message,
                "started_at": l.started_at.isoformat() if l.started_at else None,
                "completed_at": l.completed_at.isoformat() if l.completed_at else None,
            }
            for l in logs
        ]
    finally:
        db.close()


# ---------- ダッシュボードAPI（読み取り専用） ----------

@router.get("/campaigns")
def list_campaigns(
    campaign_type: str = Query(default=None),
    state: str = Query(default=None),
):
    db = SessionLocal()
    try:
        q = db.query(AdsCampaign)
        if campaign_type:
            q = q.filter(AdsCampaign.campaign_type == campaign_type)
        if state:
            q = q.filter(AdsCampaign.state == state)
        camps = q.order_by(AdsCampaign.campaign_type, AdsCampaign.name).all()
        return [
            {
                "id": c.id,
                "campaign_id": c.campaign_id,
                "name": c.name,
                "campaign_type": c.campaign_type,
                "parent_asin": c.parent_asin,
                "state": c.state,
                "targeting_type": c.targeting_type,
                "budget_amount": c.budget_amount,
                "budget_type": c.budget_type,
                "bidding_strategy": c.bidding_strategy,
                "impressions": c.impressions or 0,
                "clicks": c.clicks or 0,
                "cost": round(c.cost or 0, 1),
                "orders": c.orders or 0,
                "sales": round(c.sales or 0, 1),
                "acos": round((c.cost or 0) / c.sales * 100, 1) if (c.sales or 0) > 0 else None,
                "roas": round((c.sales or 0) / c.cost, 2) if (c.cost or 0) > 0 else None,
                "ctr": round((c.clicks or 0) / c.impressions * 100, 2) if (c.impressions or 0) > 0 else None,
                "cvr": round((c.orders or 0) / c.clicks * 100, 1) if (c.clicks or 0) > 0 else None,
                "cpc": round((c.cost or 0) / c.clicks, 1) if (c.clicks or 0) > 0 else None,
                "synced_at": c.synced_at.isoformat() if c.synced_at else None,
            }
            for c in camps
        ]
    finally:
        db.close()


@router.get("/keywords")
def list_keywords(
    campaign_type: str = Query(default=None),
    match_type: str = Query(default=None),
    search: str = Query(default=None),
):
    db = SessionLocal()
    try:
        q = db.query(AdsKeyword, AdsCampaign.name.label("campaign_name"), AdsCampaign.campaign_type)\
            .outerjoin(AdsCampaign, AdsKeyword.campaign_id == AdsCampaign.campaign_id)
        if campaign_type:
            q = q.filter(AdsCampaign.campaign_type == campaign_type)
        if match_type:
            q = q.filter(AdsKeyword.match_type == match_type)
        if search:
            q = q.filter(AdsKeyword.keyword_text.contains(search))

        rows = q.order_by(AdsKeyword.cost.desc()).all()
        return [
            {
                "id": kw.id,
                "keyword_id": kw.keyword_id,
                "keyword_text": kw.keyword_text,
                "match_type": kw.match_type,
                "state": kw.state,
                "bid": kw.bid,
                "campaign_name": cname,
                "campaign_type": ctype,
                "impressions": kw.impressions or 0,
                "clicks": kw.clicks or 0,
                "cost": round(kw.cost or 0, 1),
                "orders": kw.orders or 0,
                "sales": round(kw.sales or 0, 1),
                "acos": round(kw.acos, 1) if kw.acos is not None else None,
                "cpc": round(kw.cpc, 1) if kw.cpc is not None else None,
                "cvr": round((kw.orders or 0) / kw.clicks * 100, 1) if (kw.clicks or 0) > 0 else None,
            }
            for kw, cname, ctype in rows
        ]
    finally:
        db.close()


@router.get("/targets")
def list_targets(
    campaign_type: str = Query(default=None),
    search: str = Query(default=None),
):
    db = SessionLocal()
    try:
        q = db.query(AdsTarget, AdsCampaign.name.label("campaign_name"), AdsCampaign.campaign_type)\
            .outerjoin(AdsCampaign, AdsTarget.campaign_id == AdsCampaign.campaign_id)
        if campaign_type:
            q = q.filter(AdsCampaign.campaign_type == campaign_type)
        if search:
            q = q.filter(AdsTarget.expression.contains(search))

        rows = q.order_by(AdsTarget.cost.desc()).all()
        return [
            {
                "id": t.id,
                "target_id": t.target_id,
                "expression_type": t.expression_type,
                "expression": t.expression,
                "resolved_asin": t.resolved_asin,
                "state": t.state,
                "bid": t.bid,
                "campaign_name": cname,
                "campaign_type": ctype,
                "impressions": t.impressions or 0,
                "clicks": t.clicks or 0,
                "cost": round(t.cost or 0, 1),
                "orders": t.orders or 0,
                "sales": round(t.sales or 0, 1),
                "acos": round(t.acos, 1) if t.acos is not None else None,
                "cpc": round(t.cpc, 1) if t.cpc is not None else None,
            }
            for t, cname, ctype in rows
        ]
    finally:
        db.close()


@router.get("/search-terms")
def list_search_terms(
    min_clicks: int = Query(default=None),
    min_orders: int = Query(default=None),
    search: str = Query(default=None),
):
    db = SessionLocal()
    try:
        q = db.query(AdsSearchTerm, AdsCampaign.name.label("campaign_name"))\
            .outerjoin(AdsCampaign, AdsSearchTerm.campaign_id == AdsCampaign.campaign_id)
        if min_clicks is not None:
            q = q.filter(AdsSearchTerm.clicks >= min_clicks)
        if min_orders is not None:
            q = q.filter(AdsSearchTerm.orders >= min_orders)
        if search:
            q = q.filter(AdsSearchTerm.search_term.contains(search))

        rows = q.order_by(AdsSearchTerm.cost.desc()).limit(500).all()
        return [
            {
                "id": st.id,
                "search_term": st.search_term,
                "match_type": st.match_type,
                "campaign_name": cname,
                "impressions": st.impressions or 0,
                "clicks": st.clicks or 0,
                "cost": round(st.cost or 0, 1),
                "orders": st.orders or 0,
                "sales": round(st.sales or 0, 1),
                "acos": round(st.acos, 1) if st.acos is not None else None,
                "cpc": round(st.cpc, 1) if st.cpc is not None else None,
            }
            for st, cname in rows
        ]
    finally:
        db.close()


@router.get("/dashboard")
def ads_dashboard():
    db = SessionLocal()
    try:
        camps = db.query(AdsCampaign).all()
        summary = {}
        for c in camps:
            ct = c.campaign_type or "other"
            if ct not in summary:
                summary[ct] = {"count": 0, "cost": 0, "sales": 0, "orders": 0, "clicks": 0, "impressions": 0}
            s = summary[ct]
            s["count"] += 1
            s["cost"] += c.cost or 0
            s["sales"] += c.sales or 0
            s["orders"] += c.orders or 0
            s["clicks"] += c.clicks or 0
            s["impressions"] += c.impressions or 0

        for ct, s in summary.items():
            s["cost"] = round(s["cost"], 1)
            s["sales"] = round(s["sales"], 1)
            s["acos"] = round(s["cost"] / s["sales"] * 100, 1) if s["sales"] > 0 else None
            s["roas"] = round(s["sales"] / s["cost"], 2) if s["cost"] > 0 else None

        last_sync = db.query(AdsSyncLog).filter(
            AdsSyncLog.status == "completed"
        ).order_by(AdsSyncLog.id.desc()).first()

        return {
            "summary": summary,
            "last_synced_at": last_sync.completed_at.isoformat() if last_sync and last_sync.completed_at else None,
        }
    finally:
        db.close()
