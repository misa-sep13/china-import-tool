"""春節・国慶節のお知らせ。

発注数は china_holiday が勝手に増やしてくれるが、画面には増えた数字しか
出ないので、何が起きているか分からなかった。ここは数字を変えず、
「いつまでに発注するか」を言葉で返すだけ。

AmazonとFBA、楽天でリードタイムも休みの設定も別なので、それぞれの
最終発注日を出す。
"""
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.rakuten_settings import RakutenSettings
from app.models.settings import OrderSettings
from app.services import season_alert, seasonal

router = APIRouter(prefix="/season", tags=["season"])


def _cfg(row, site: str, label: str, lead_default: int,
         review_attr: str, review_default: int) -> dict:
    """review_days は「次に発注するまでの間隔」。

    発注計算が使っている設定をそのまま渡す。Amazonは threshold_days、
    楽天は target_days。ここがずれると、画面に出る上乗せ日数と
    実際の発注数が合わなくなる。
    """
    return {
        "site": site,
        "label": label,
        "lead_days": _int(row, "lead_days", lead_default),
        "review_days": _int(row, review_attr, review_default),
        "cny_before": _int(row, "cny_closed_before", 7),
        "cny_after": _int(row, "cny_closed_after", 15),
        "national_days": _int(row, "national_closed_days", 7),
    }


def _int(row, name: str, default: int) -> int:
    v = getattr(row, name, None) if row is not None else None
    return default if v in (None, "") else int(v)


@router.get("/alert")
def alert(today: str | None = None, db: Session = Depends(get_db)):
    """次に来る中国の長期休暇と、サイトごとの最終発注日。

    today を渡せば、その日に立ったつもりで出す（確認用）。
    """
    day = date.fromisoformat(today) if today else date.today()
    amz = db.query(OrderSettings).first()
    rak = db.query(RakutenSettings).first()
    out = season_alert.build(day, [
        _cfg(amz, "amazon", "Amazon", 75, "threshold_days", 75),
        _cfg(rak, "rakuten", "楽天", 20, "target_days", 30),
    ])
    return out or {"show": False}


@router.get("/seasonal")
def seasonal_candidates(site: str = "rakuten", today: str | None = None,
                        db: Session = Depends(get_db)):
    """いま仕入れるべき季節商品の候補。

    「いま発注すると届くころ」に、去年平月の何倍売れていたかで見る。
    去年の実績が無いうちは enough_data=false を返す。
    適当な候補を出すより、出せないと言うほうが安全。
    """
    day = date.fromisoformat(today) if today else date.today()
    if site == "amazon":
        rows, names = seasonal.amazon_rows(db)
        row = db.query(OrderSettings).first()
        lead = _int(row, "lead_days", 75)
    else:
        rows, names = seasonal.rakuten_rows(db)
        row = db.query(RakutenSettings).first()
        lead = _int(row, "lead_days", 20)
    out = seasonal.find_candidates(rows, names, day, lead)
    out["site"] = site
    out["lead_days"] = lead
    return out
