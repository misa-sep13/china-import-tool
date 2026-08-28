"""Amazon競合リサーチの原価計算。

もらったリサーチツール（HTML1枚）の計算式をそのまま移植したもの。
設計の肝は2つ:

1. 中国側の上乗せを「倍率」ではなく「比例＋固定費」で持つ
   ラベル貼り・国内送料・箱袋代は1点いくらの定額で、1688単価に比例しない。
   実測では倍率が単価2元未満で2.10倍、25元超で1.05倍と激変する。
   倍率だけのモデルは安い商品の原価を必ず過小評価する。

2. 三辺・実重量・1688単価が欠けたら計算しない
   欠けたまま計算すると決済重量を小さく見積もり、大型商品の原価を
   大幅に過小評価するため。「計算できない(要確認)」と
   「計算はできたが怪しい(⚠)」を別物として扱う。

初期値はタオタロウの実測（もらったツールはラクマート実績）:
  輸送単価 7.00元/kg  = 国際送料1,022元 ÷ 計費重量146kg
  輸入関連費 15.4%    =（納税額5,774円 + 通関料の按分352円）÷ 課税前原価39,687円
  容積除数 6000       = 実データで確認
1便からの実測なので、便が貯まったら画面から直せるようにしてある。
"""
import json

VOLUME_DIVISOR = 6000   # 容積重量の除数。業者・便で変わることがある


def _f(v, default=0.0):
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _has(v):
    return v is not None and v != "" and _f(v) > 0


def _load_list(v):
    if not v:
        return []
    if isinstance(v, list):
        return v
    try:
        d = json.loads(v)
        return d if isinstance(d, list) else []
    except (ValueError, TypeError):
        return []


def settle_rate(settings) -> float:
    """決済レート = 市場為替 × (1 + 補正%)。

    送金手数料やチャージ手数料の分だけ実際の支払いは市場為替より高くなるので、
    リサーチ時点では補正を掛けて安全側に見る。
    """
    base = _f(getattr(settings, "exchange_rate", None))
    adj = _f(getattr(settings, "rate_adjust", 0))
    if base <= 0:
        return 0.0
    return base * (1 + adj / 100)


def judge_tier(item) -> dict | None:
    """FBAサイズ区分（日本）。原価計算には使わず、手数料を調べる手がかりとして出す。

    小型: 25x18x2.0cm以内 かつ 250g以内
    標準: 45x35x20cm以内 かつ 9kg以内
    それ以外は大型（三辺合計で段階が分かれる）
    """
    dims = sorted([_f(item.len_a), _f(item.len_b), _f(item.len_c)], reverse=True)
    kg = _f(item.weight)
    if not all(dims):
        return None
    g = kg * 1000
    if dims[0] <= 25 and dims[1] <= 18 and dims[2] <= 2.0 and 0 < g <= 250:
        return {"tier": "small", "label": "小型"}
    if dims[0] <= 45 and dims[1] <= 35 and dims[2] <= 20 and kg <= 9:
        return {"tier": "standard", "label": "標準"}
    total = sum(dims)
    step = next((s for s in (60, 80, 100, 120, 140, 160, 170) if total <= s), None)
    return {"tier": "oversize", "label": "大型" + (f"({step}cm)" if step else "(170cm超)")}


def parts_total(item) -> float:
    """1販売単位あたりの1688代金（元）。セット商品は部材ごとに合算する。"""
    total = 0.0
    for p in _load_list(item.parts):
        if not isinstance(p, dict):
            continue
        total += _f(p.get("price")) * _f(p.get("qty"), 1)
    return total


def options_total(item) -> float:
    """代行業者に頼む加工の費用（元/販売単位）。"""
    total = 0.0
    for o in _load_list(item.options):
        if isinstance(o, dict):
            total += _f(o.get("price"))
        else:
            total += _f(o)
    return total


def risk_warnings(item, goods_yuan, billable_kg, vol_kg, ship_share) -> list[str]:
    """入力は揃っているが、実測で誤差が大きいと分かっているパターン。

    「計算できない(要確認)」とは分けて、計算はしたうえで注意を促す。
    """
    w = []
    if 0 < goods_yuan <= 2:
        w.append("1688単価が2元以下（このゾーンは誤差が大きい）")
    if vol_kg and _f(item.weight) and vol_kg > _f(item.weight) * 1.5:
        w.append("容積重量が実重量の1.5倍超（梱包次第で送料が動く）")
    if billable_kg and billable_kg >= 2:
        w.append("決済重量2kg以上（輸送方法で原価が大きく変わる）")
    if ship_share and ship_share >= 30:
        w.append("送料が原価の30%以上")
    if len(_load_list(item.parts)) > 1:
        w.append("複数部材のセット（入数の取り違えに注意）")
    return w


def compute(item, settings) -> dict:
    """1行ぶんの原価と粗利を出す。

    戻り値の missing が空でなければ「要確認」＝原価も粗利も出さない。
    """
    rate = settle_rate(settings)
    auto = judge_tier(item)
    tier = item.size_type or (auto["tier"] if auto else "")
    tier_label = ({"small": "小型", "standard": "標準", "oversize": "大型"}.get(item.size_type)
                  if item.size_type else (auto["label"] if auto else None))

    dims_ok = all(_has(v) for v in (item.len_a, item.len_b, item.len_c, item.weight))
    default_pack = _f(getattr(settings, "pack_factor", 100), 100)
    pack = (_f(item.pack_factor, default_pack) or default_pack) / 100 or 1
    raw_vol = (_f(item.len_a) * _f(item.len_b) * _f(item.len_c) / VOLUME_DIVISOR) if dims_ok else None
    vol_kg = raw_vol * pack if raw_vol is not None else None
    billable_kg = max(vol_kg, _f(item.weight)) if dims_ok else None

    goods_yuan = parts_total(item)

    missing = []
    if not all(_has(v) for v in (item.len_a, item.len_b, item.len_c)):
        missing.append("三辺")
    if not _has(item.weight):
        missing.append("実重量")
    if not goods_yuan:
        missing.append("1688単価")
    if rate <= 0:
        missing.append("為替")

    base = {
        "billable_kg": round(billable_kg, 3) if billable_kg else None,
        "vol_kg": round(vol_kg, 3) if vol_kg else None,
        "tier": tier, "tier_label": tier_label,
        "missing": missing,
        "china_jpy": None, "ship_jpy": None, "cost_jpy": None,
        "profit_jpy": None, "profit_rate": None, "ship_share": None,
        "warns": [],
    }
    if missing:
        return base

    # 中国側 = 1688代金 + 1点あたり定額の基本作業費 + オプション代
    china_yuan = goods_yuan + _f(settings.china_fixed) + options_total(item)
    china_jpy = china_yuan * rate
    ship_jpy = (billable_kg or 0) * _f(settings.ship_yuan) * rate
    cost = (china_jpy + ship_jpy) * (1 + _f(settings.tariff_rate) / 100)

    # 送料比率は輸入関連費を掛ける前どうしで出す（分母をそろえるため）
    denom = china_jpy + ship_jpy
    ship_share = (ship_jpy / denom * 100) if denom > 0 else 0

    price = _f(item.price)
    fee = _f(item.fee)
    profit = (price - cost - fee) if price > 0 else None
    profit_rate = (profit / price * 100) if (profit is not None and price > 0) else None

    base.update({
        "china_jpy": round(china_jpy, 1),
        "ship_jpy": round(ship_jpy, 1),
        "cost_jpy": round(cost, 1),
        "profit_jpy": round(profit, 1) if profit is not None else None,
        "profit_rate": round(profit_rate, 1) if profit_rate is not None else None,
        "ship_share": round(ship_share, 1),
        "warns": risk_warnings(item, goods_yuan, billable_kg, vol_kg, ship_share),
    })
    return base
