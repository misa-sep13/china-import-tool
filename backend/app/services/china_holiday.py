"""中国の長期休暇で工場が止まるぶん、発注のリードタイムを自動で延ばす。

春節と国慶節は工場が長期間止まるので、その前に多めに発注しておかないと
在庫が切れる。かといって一年中多めに持つと資金が寝るので、休暇が
近づいたときだけ自動で発注数が増える形にしている。

やっていることは「発注してから入荷するまでの間に工場の休みが何日
入るかを数えて、そのぶんリードタイムに足す」だけ。休みを過ぎれば
足す日数が0に戻るので、終わったあとの戻し忘れが起きない。
"""
from dataclasses import dataclass
from datetime import date, timedelta

# 春節（旧正月）の元日。旧暦なので毎年ずれる。
CNY_DATES = {
    2025: date(2025, 1, 29),
    2026: date(2026, 2, 17),
    2027: date(2027, 2, 6),
    2028: date(2028, 1, 26),
    2029: date(2029, 2, 13),
    2030: date(2030, 2, 3),
    2031: date(2031, 1, 23),
    2032: date(2032, 2, 11),
    2033: date(2033, 1, 31),
    2034: date(2034, 2, 19),
    2035: date(2035, 2, 8),
}

# 国慶節は毎年10月1日から。法定休日は7日間。
NATIONAL_DAY_MONTH = 10
NATIONAL_DAY_DAY = 1


@dataclass
class ClosedPeriod:
    name:  str
    start: date
    end:   date   # この日まで止まる（この日を含む）

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def overlap_days(self, start: date, end: date) -> int:
        """[start, end] と重なる日数。"""
        s = max(self.start, start)
        e = min(self.end, end)
        return (e - s).days + 1 if e >= s else 0


def closed_periods(
    year_from: int,
    year_to: int,
    cny_before: int = 7,
    cny_after: int = 15,
    national_days: int = 7,
) -> list[ClosedPeriod]:
    """工場が止まる期間の一覧。

    春節は法定休日より長く止まる工場が多いので、前後に日数を足せるように
    している（既定は前7日・後15日のおよそ3週間）。
    """
    out: list[ClosedPeriod] = []
    for y in range(year_from, year_to + 1):
        cny = CNY_DATES.get(y)
        if cny:
            out.append(ClosedPeriod(
                name=f"春節{y}",
                start=cny - timedelta(days=max(0, cny_before)),
                end=cny + timedelta(days=max(0, cny_after)),
            ))
        if national_days > 0:
            nd = date(y, NATIONAL_DAY_MONTH, NATIONAL_DAY_DAY)
            out.append(ClosedPeriod(
                name=f"国慶節{y}",
                start=nd,
                end=nd + timedelta(days=national_days - 1),
            ))
    out.sort(key=lambda p: p.start)
    return out


@dataclass
class LeadTimeEffect:
    base_lead_days:      int
    effective_lead_days: int                 # 今日発注したぶんが実際に入荷するまでの日数
    plan_lead_days:      int                 # 発注数の計算に使う日数（次回発注の遅れも織り込む）
    extra_days:          int                 # plan - base
    reason:              str | None          # 効いている休暇の名前
    arrival_date:        date | None         # 今日発注したぶんの入荷見込み日
    next_period:         ClosedPeriod | None # 次に来る休暇（まだ効いていなくても返す）


def lead_time_effect(
    today: date,
    base_lead_days: int,
    cny_before: int = 7,
    cny_after: int = 15,
    national_days: int = 7,
) -> LeadTimeEffect:
    """今日発注したら何日で入荷するかを、工場の休みを考慮して出す。

    リードタイムを延ばすと入荷日が後ろにずれ、ずれた先にさらに休みが
    かかることがあるので、変化しなくなるまで数回まわして収束させる。
    """
    periods = closed_periods(today.year - 1, today.year + 2,
                             cny_before, cny_after, national_days)
    lead = max(0, base_lead_days)
    hit: list[str] = []
    for _ in range(10):
        arrival = today + timedelta(days=lead)
        extra = 0
        hit = []
        for p in periods:
            # 発注日の翌日から入荷予定日までに挟まる休みを数える
            d = p.overlap_days(today + timedelta(days=1), arrival)
            if d > 0:
                extra += d
                hit.append(p.name)
        new_lead = max(0, base_lead_days) + extra
        if new_lead == lead:
            break
        lead = new_lead

    future = [p for p in periods if p.end >= today]
    return LeadTimeEffect(
        base_lead_days=max(0, base_lead_days),
        effective_lead_days=lead,
        plan_lead_days=lead,
        extra_days=lead - max(0, base_lead_days),
        reason="・".join(dict.fromkeys(hit)) if hit else None,
        arrival_date=today + timedelta(days=lead),
        next_period=future[0] if future else None,
    )


def order_lead_effect(
    today: date,
    base_lead_days: int,
    review_days: int,
    cny_before: int = 7,
    cny_after: int = 15,
    national_days: int = 7,
) -> LeadTimeEffect:
    """発注数の計算に使うリードタイム。

    今日のぶんの遅れだけを見ていると、休み前に間に合う最後の発注が
    通常数量のままになり、その次の入荷までの穴が埋まらない。

    かといって「今日」と「review_days後」の2点だけを比べると、
    休みの直前に数量がいったん下がってまた跳ね上がる谷ができる。
    次に発注するまでの間（0〜review_days日後）のどこで発注しても
    足りるように、その期間でいちばん長くなる日数を採用する。

    入荷見込み日（arrival_date）は今日のぶんの実際の日付を返す。
    発注数に使うのは plan_lead_days のほう。
    """
    now = lead_time_effect(today, base_lead_days, cny_before, cny_after, national_days)
    plan, reason = now.effective_lead_days, now.reason
    for k in range(1, max(0, review_days) + 1):
        e = lead_time_effect(today + timedelta(days=k), base_lead_days,
                             cny_before, cny_after, national_days)
        if e.effective_lead_days > plan:
            plan, reason = e.effective_lead_days, e.reason
    return LeadTimeEffect(
        base_lead_days=now.base_lead_days,
        effective_lead_days=now.effective_lead_days,
        plan_lead_days=plan,
        extra_days=plan - now.base_lead_days,
        reason=reason,
        arrival_date=now.arrival_date,
        next_period=now.next_period,
    )
