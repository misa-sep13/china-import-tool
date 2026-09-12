"""発注ロジック（日別実績版）。

これまでは7/15/30/60/90日の集計値を重み付けして平均していたが、
それだと「その日どうだったか」が分からず、次のどれも扱えなかった。

  ・在庫が無かった日を平均に入れてしまう
      → 実力を低く見る → 発注を絞る → また欠品する
  ・Vine（レビュー用の無料配布）を需要として数えてしまう
  ・1人のまとめ買いを日常の実力と見なして在庫を持ちすぎる
  ・セール日をそのまま数えると膨らみ、除外すると崖ができる

ここでは日別を前提に組み直す。中心にあるのは非対称の考え方で、
**需要が増えた証拠は疑い、減った証拠は素直に受ける**。
少なく間違えれば翌営業日に足せるが、多く仕入れた在庫は返せない。
毎日発注しているから成り立つ設計で、月1回の発注なら別の形になる。

    発注数 = 日販D × 目標日数T − 現在庫Y
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional

# ---- 既定値。すべて1つ変えれば前の挙動へ戻せるようにしておく ----

WINDOW_DAYS = 60          # 日販を見る窓
TREND_DAYS = 7            # 直近の勢いを見る日数（暦ではなく「数えられる日」）
TREND_MIN = 0.7           # 失速は素直に絞る
TREND_MAX = 1.05          # 伸びは疑う（上限をほぼ1に置く）
SPIKE_MULT = 3.0          # まとめ買いの頭打ち: 平常平均×3
SPIKE_FLOOR = 3.0         #   ただし最低3個までは通す（低回転品向け）
SALE_CAP_MULT = 1.2       # セール換算値の頭打ち: 平常日販×1.2
SALE_RAMP_DAYS = 30       # 信用度 = 1 − 平常日数/これ
BASE_TARGET_DAYS = 60     # 目標日数の基礎
TRIGGER_SLACK = 5         # 目標より5日分以上足りなくなってから動く
MIN_ORDER_QTY = 10        # 小口発注除け
SALE_MULT_MIN = 1.0       # 実測倍率のクランプ
SALE_MULT_MAX = 4.0


@dataclass
class LogicSettings:
    window_days: int = WINDOW_DAYS
    trend_days: int = TREND_DAYS
    trend_min: float = TREND_MIN
    trend_max: float = TREND_MAX
    spike_mult: float = SPIKE_MULT
    spike_floor: float = SPIKE_FLOOR
    sale_cap_mult: float = SALE_CAP_MULT      # 0で頭打ちなし
    sale_ramp_days: int = SALE_RAMP_DAYS      # 0でランプ無効（割り戻しのみ）
    base_target_days: int = BASE_TARGET_DAYS
    trigger_slack: int = TRIGGER_SLACK
    min_order_qty: int = MIN_ORDER_QTY
    # 0にすると「セール日は除外」の旧方式に戻る
    sale_rescale: bool = True


@dataclass
class DayRow:
    """1日ぶんの実績。DBの daily_sales をそのまま写したもの。"""
    day: date
    units: int = 0
    vine_units: int = 0
    in_stock: bool = True
    is_sale: bool = False        # セール期間内か
    sale_mult: float = 1.0       # その日に使う実効倍率


@dataclass
class DailyBreakdown:
    """日販がどう積み上がったか。画面で1行ずつ説明できるようにする。

    式が長いので、結果の数字だけ見せられても検算できない。
    どの日をどう扱ったかを残す。
    """
    daily: float = 0.0
    plain_daily: float = 0.0      # D0: セールを全部除いた平常日販
    counted_days: int = 0         # 平均の分母に入れた日数
    plain_days: int = 0           # 在庫があってセールでない日
    skipped_oos: int = 0          # 在庫切れで飛ばした日
    vine_removed: int = 0         # 引いたVineの数
    spike_capped: int = 0         # まとめ買いで頭打ちにした日数
    sale_days: int = 0            # 割り戻して算入したセール日数
    sale_capped: int = 0          # そのうちランプで抑えた日数
    confidence: float = 0.0       # 換算値をどれだけ信じたか（0〜1）
    notes: List[str] = field(default_factory=list)


def _effective_units(r: DayRow) -> float:
    """Vineを引いた実売。無料配布は有償の需要ではない。"""
    return max(0.0, (r.units or 0) - (r.vine_units or 0))


def plain_daily(rows: List[DayRow], s: LogicSettings) -> float:
    """平常日販 D0。セール日を全部除いて出す。

    セール換算値をどこまで信じるかの物差しになる。
    在庫あり・Vine控除・まとめ買いの頭打ちは同じ扱いをする。
    """
    plain = [r for r in rows if r.in_stock and not r.is_sale]
    if not plain:
        return 0.0
    vals = [_effective_units(r) for r in plain]
    base = sum(vals) / len(vals)
    cap = max(s.spike_floor, base * s.spike_mult)
    capped = [min(v, cap) for v in vals]
    return sum(capped) / len(capped)


def daily_sales(rows: List[DayRow], s: LogicSettings,
                first_sale_day: Optional[date] = None) -> DailyBreakdown:
    """日販D。窓内の各日を次のように扱って平均する。

      在庫切れの日   ノーカウント（分子にも分母にも入れない）
      Vine           日別に実配布数を引く
      まとめ買いの日  max(3, 平常平均×3) で頭打ち
      セール日        実測倍率で平常日に換算し、ランプで抑えて算入

    新商品は窓を発売からの日数に縮めるだけで、別の式は持たない。
    """
    b = DailyBreakdown()
    if not rows:
        return b

    # 新商品は発売前の日を数えない（窓を縮めるのと同じこと）
    if first_sale_day:
        rows = [r for r in rows if r.day >= first_sale_day]
    if not rows:
        return b

    d0 = plain_daily(rows, s)
    b.plain_daily = round(d0, 3)
    b.plain_days = len([r for r in rows if r.in_stock and not r.is_sale])

    # まとめ買いの頭打ちは平常日の水準を基準にする
    spike_cap = max(s.spike_floor, d0 * s.spike_mult) if d0 > 0 else None

    # 換算値をどこまで信じるか。疑いの強さ＝反証データの量。
    # 実績0日（セール中に出した新商品・欠品明け）は他に材料が無いので
    # 換算値をそのまま信じ、実績が積まれるほど実績主義へ寄せる
    if s.sale_ramp_days > 0:
        b.confidence = max(0.0, 1.0 - b.plain_days / s.sale_ramp_days)
    else:
        b.confidence = 1.0

    total = 0.0
    count = 0
    for r in rows:
        if not r.in_stock:
            b.skipped_oos += 1
            continue

        v = _effective_units(r)
        b.vine_removed += (r.vine_units or 0)

        if r.is_sale:
            if not s.sale_rescale:
                # 旧方式。セール日は無かったことにする
                continue
            mult = min(max(r.sale_mult or 1.0, SALE_MULT_MIN), SALE_MULT_MAX)
            q = v / mult if mult > 0 else v
            if s.sale_cap_mult > 0:
                # 倍率は全店平均なので、平均より大きく伸びた商品には
                # 膨張が残る。実績があるほど平常×1.2で頭を押さえる
                cap = max(d0 * s.sale_cap_mult, q * b.confidence)
                if q > cap:
                    q = cap
                    b.sale_capped += 1
            total += q
            count += 1
            b.sale_days += 1
            continue

        if spike_cap is not None and v > spike_cap:
            v = spike_cap
            b.spike_capped += 1
        total += v
        count += 1

    b.counted_days = count
    b.daily = round(total / count, 3) if count else 0.0

    if b.skipped_oos:
        b.notes.append(f"在庫切れ {b.skipped_oos}日を数えていません")
    if b.vine_removed:
        b.notes.append(f"Vine {b.vine_removed}個を引きました")
    if b.spike_capped:
        b.notes.append(f"まとめ買い {b.spike_capped}日を頭打ちにしました")
    if b.sale_days:
        msg = f"セール {b.sale_days}日を平常日に換算しました"
        if b.sale_capped:
            msg += f"（うち{b.sale_capped}日は実績で抑えました）"
        b.notes.append(msg)
    return b


def trend(rows: List[DayRow], s: LogicSettings, daily: float) -> float:
    """直近の勢い。60日の日販に対する直近7日の比。

    7日は暦ではなく「数えられる日」を新しい方から拾う。暦で切ると、
    セール期間の位置しだいで有効日数が0〜1日になり、全商品のトレンドが
    一斉に下限へ張り付いたり1.0に戻ったりして、発注が日をまたいで
    半減→倍増する崖が起きる。

    非対称にしてあるのは、失速は素直に絞り、伸びは疑うため。
    """
    if daily <= 0:
        return 1.0
    usable = [r for r in sorted(rows, key=lambda x: x.day, reverse=True)
              if r.in_stock and not r.is_sale]
    if len(usable) < 3:
        # 材料が少なすぎるときは動かさない
        return 1.0
    recent = usable[:s.trend_days]
    vals = [_effective_units(r) for r in recent]
    recent_daily = sum(vals) / len(vals)
    return max(s.trend_min, min(s.trend_max, recent_daily / daily))


def target_days(s: LogicSettings, trend_value: float,
                sale_extra_days: float = 0.0,
                holiday_extra_days: float = 0.0) -> float:
    """目標日数T。

        T = (基礎 + セール上乗せ + 連休上乗せ) × トレンド

    上乗せにもトレンドを掛けるのは次元を合わせるため。上乗せは
    「日販の何日分か」で表した量なので、売れ方がトレンド倍に変われば
    上乗せも同じ倍率で変わるべき。
    """
    base = s.base_target_days + sale_extra_days + holiday_extra_days
    return base * trend_value


def sale_extra_days(remaining_sale_days: int, mult: float) -> float:
    """セールで上乗せする日数。残り日数 ×（倍率−1）。"""
    if remaining_sale_days <= 0:
        return 0.0
    m = min(max(mult or 1.0, SALE_MULT_MIN), SALE_MULT_MAX)
    return remaining_sale_days * (m - 1.0)


def holiday_extra_days(remaining_holiday_days: int, mult: float = 1.0) -> float:
    """中国の長期休暇で工場が止まる分を先に積む。"""
    if remaining_holiday_days <= 0:
        return 0.0
    return remaining_holiday_days * max(mult, 1.0)


@dataclass
class OrderResult:
    daily: float
    trend: float
    target_days: float
    stock: int
    days_left: float
    need: int              # 本来必要な数（門で見送っても出す）
    qty: int               # 実際に発注する数（セット単位）
    qty_pieces: int
    ordered: bool          # 発注書に載せるか
    hold_reason: str = ""  # 載せない理由
    breakdown: Optional[DailyBreakdown] = None


def calc_order(rows: List[DayRow], stock: int, set_size: int,
               s: LogicSettings,
               first_sale_day: Optional[date] = None,
               sale_extra: float = 0.0,
               holiday_extra: float = 0.0) -> OrderResult:
    """1商品ぶんの発注数を出す。

        発注数 = 日販D × 目標日数T − 現在庫Y

    Yは FBA販売可 + 輸送中 + 梱包中 + 中国倉庫 の合計。
    発注済みを全部数えないと二重に発注してしまう。

    発注書に載せる条件は2つ。
      1. 残日数 ≦ T − 5   （目標より5日分以上足りなくなってから動く）
      2. 発注個数 ≧ 10    （小口発注除け）
    載せない行も「本来必要な数」は返す。消すと状況が見えなくなる。
    """
    set_size = max(1, set_size)
    b = daily_sales(rows, s, first_sale_day)
    d = b.daily
    t_mult = trend(rows, s, d)
    t_days = target_days(s, t_mult, sale_extra, holiday_extra)

    days_left = (stock / d) if d > 0 else 9999.0
    need = max(0, round(d * t_days) - stock)

    ordered = False
    reason = ""
    qty = 0
    qty_pieces = 0

    if need <= 0:
        reason = "在庫が足りています"
    elif days_left > t_days - s.trigger_slack:
        reason = (f"まだ余裕があります"
                  f"（残り{days_left:.0f}日 / 目標{t_days:.0f}日）")
    else:
        sets = -(-need // set_size)          # 切り上げ
        pieces = sets * set_size
        if pieces < s.min_order_qty:
            reason = f"{pieces}個は最小発注数{s.min_order_qty}個に届きません"
        else:
            ordered = True
            qty = sets
            qty_pieces = pieces

    return OrderResult(
        daily=d, trend=round(t_mult, 3), target_days=round(t_days, 1),
        stock=stock, days_left=round(days_left, 1), need=need,
        qty=qty, qty_pieces=qty_pieces, ordered=ordered,
        hold_reason=reason, breakdown=b,
    )


def measured_sale_mult(sale_units: float, plain_daily_sum: float) -> Optional[float]:
    """セールの実測倍率。全店合計で出す。

        M = Σセール日の実売（Vine控除） ÷ Σ各商品の平常日販

    商品ごとの倍率は持たない。割り算がその商品の個性を消してしまい、
    「よく伸びた商品ほど平常に見える」というおかしなことになるため。
    分母が小さすぎるときは None を返し、呼び出し側で見込み値へ退避する。
    """
    if plain_daily_sum <= 0:
        return None
    m = sale_units / plain_daily_sum
    if m < SALE_MULT_MIN or m > SALE_MULT_MAX * 2:
        # 明らかにおかしい値は使わない（黙って膨らませない）
        return None
    return min(max(m, SALE_MULT_MIN), SALE_MULT_MAX)
