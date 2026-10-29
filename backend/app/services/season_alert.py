"""春節・国慶節に向けた「いつまでに発注するか」を出す。

発注数そのものは china_holiday が自動で増やしている（休みをまたぐぶん
リードタイムが伸びる＝目標在庫が増える）。ただ画面には増えた数字しか
出ないので、「なぜ増えたのか」「あと何日で締切か」が分からなかった。

ここでは数字を変えない。いま何が起きているかを言葉にするだけ。

いちばん大事なのは最終発注日で、これは
    休みが始まる前日 － リードタイム
で決まる。この日を過ぎた発注は、休みが明けるまで工場が動かないので
入荷が3週間以上あとになる。だから「その日までに、休み明けまで持つ量を
積んでおく」必要がある。
"""
from dataclasses import dataclass
from datetime import date, timedelta

from app.services.china_holiday import (ClosedPeriod, closed_periods,
                                        lead_time_effect, order_lead_effect)

# 何日前から画面に出すか。早すぎると見慣れて無視されるし、
# 遅いと間に合わない。最終発注日の60日前から出す
NOTICE_DAYS_BEFORE_DEADLINE = 60


@dataclass
class SiteAlert:
    site: str               # "amazon" / "rakuten"
    label: str
    lead_days: int          # 休みを考えない素のリードタイム
    last_order_day: date    # この日までに発注すれば休み前に届く
    days_left: int          # 最終発注日まであと何日（過ぎていればマイナス）
    extra_days: int         # いま発注数に足されている日数
    resume_arrival: date    # 締切を過ぎて発注したぶんが届く日


def _last_order_day(period: ClosedPeriod, base_lead: int,
                    cny_before: int, cny_after: int,
                    national_days: int) -> date:
    """休みが始まる前に届く、いちばん遅い発注日。

    素直に「開始日−1−リードタイム」でほぼ合うが、その手前に別の休み
    （国慶節など）が挟まると日数が狂う。実際に入荷日を出して確かめる。
    """
    d = period.start - timedelta(days=base_lead + 1)
    for _ in range(60):
        eff = lead_time_effect(d, base_lead, cny_before, cny_after,
                               national_days)
        if eff.arrival_date and eff.arrival_date < period.start:
            return d
        d -= timedelta(days=1)
    return d


def site_alert(site: str, label: str, today: date, base_lead: int,
               review_days: int, cny_before: int, cny_after: int,
               national_days: int,
               period: ClosedPeriod) -> SiteAlert:
    last = _last_order_day(period, base_lead, cny_before, cny_after,
                           national_days)
    eff = order_lead_effect(today, base_lead, review_days,
                            cny_before, cny_after, national_days)
    after = lead_time_effect(last + timedelta(days=1), base_lead,
                             cny_before, cny_after, national_days)
    return SiteAlert(
        site=site, label=label,
        lead_days=base_lead,
        last_order_day=last,
        days_left=(last - today).days,
        extra_days=eff.extra_days,
        resume_arrival=after.arrival_date or period.end,
    )


def next_period(today: date, cny_before: int, cny_after: int,
                national_days: int) -> ClosedPeriod | None:
    """これから来る（または今まっただ中の）休み。"""
    periods = closed_periods(today.year, today.year + 2,
                             cny_before, cny_after, national_days)
    future = [p for p in periods if p.end >= today]
    return future[0] if future else None


def stage_of(today: date, period: ClosedPeriod, days_left: int) -> str:
    """いま何をするときか。画面の文言を決めるのに使う。"""
    if period.start <= today <= period.end:
        return "closed"            # 休みの最中。発注しても動かない
    if days_left < 0:
        return "missed"            # 締切を過ぎた。次に届くのは休み明け
    if days_left <= 14:
        return "urgent"            # 今週中に決める
    if days_left <= NOTICE_DAYS_BEFORE_DEADLINE:
        return "soon"              # そろそろ積み始める
    return "far"


# サイトごとに締切が違うので、画面全体の文言は「今動けば間に合う」
# ものを優先する。過ぎてしまったものを先頭に出しても打つ手が無い
_STAGE_ORDER = ["closed", "urgent", "soon", "missed", "far"]


_STAGE_TEXT = {
    "far":    "まだ先です。いつもどおりで大丈夫です。",
    "soon":   "そろそろです。休み明けまで持つ量を積み始めてください。",
    "urgent": "急ぎです。この日を過ぎた発注は休み明けまで届きません。",
    "missed": "締切を過ぎました。いま発注したぶんは休み明けの入荷になります。",
    "closed": "工場が休みです。発注しても動きません。",
}


def build(today: date, sites_cfg: list[dict]) -> dict | None:
    """画面に出す形にまとめる。

    sites_cfg は [{site,label,lead_days,review_days,cny_before,
                   cny_after,national_days}, ...]。
    AmazonとFBA、楽天でリードタイムも休みの設定も別なので、
    それぞれで最終発注日を出す。
    """
    if not sites_cfg:
        return None
    # 休みの期間は設定で前後に伸ばせるが、いちばん長く止まる見かたを
    # 採用する。短いほうに合わせて締切を見誤るほうが痛い
    p = next_period(today,
                    max(c["cny_before"] for c in sites_cfg),
                    max(c["cny_after"] for c in sites_cfg),
                    max(c["national_days"] for c in sites_cfg))
    if not p:
        return None

    sites = [site_alert(c["site"], c["label"], today, c["lead_days"],
                        c["review_days"], c["cny_before"], c["cny_after"],
                        c["national_days"], p)
             for c in sites_cfg]
    stages = {s.site: stage_of(today, p, s.days_left) for s in sites}
    stage = min(stages.values(), key=_STAGE_ORDER.index)
    return {
        "today": today.isoformat(),
        "period": {
            "name": p.name,
            "start": p.start.isoformat(),
            "end": p.end.isoformat(),
            "days": p.days,
            "days_until_start": (p.start - today).days,
        },
        "stage": stage,
        "message": _STAGE_TEXT[stage],
        "sites": [{
            "site": s.site,
            "label": s.label,
            "lead_days": s.lead_days,
            "last_order_day": s.last_order_day.isoformat(),
            "days_left": s.days_left,
            "extra_days": s.extra_days,
            "resume_arrival": s.resume_arrival.isoformat(),
            "stage": stages[s.site],
            "message": _STAGE_TEXT[stages[s.site]],
        } for s in sites],
        # 画面を出すかどうか。遠いうちから出しても見慣れてしまう
        "show": stage != "far",
    }
