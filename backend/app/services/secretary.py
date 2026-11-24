"""秘書。くり返しの決まりから、その月の実体を生やす。

生やすのは画面を開いたときとメールの取り込みのとき。別立てのバッチは置かない。
見に行く月は先月・今月・来月の3つだけにしてある。月末が期限のものを
数日前から出すと月をまたぐので、来月も見る必要がある。
"""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

# RenderはUTCで動く。朝9時までは日付が前日のままになるので、
# 「今日やること」は必ず日本時間で数える
JST = timezone(timedelta(hours=9))


def today_jst() -> date:
    return datetime.now(JST).date()


def now_jst() -> datetime:
    """記録用の「今」。日本時間の壁時計をそのまま入れる。

    タイムゾーン付きで入れるとPostgresがUTCに直して返すので、画面に
    9時間ずれた時刻が出る（楽天まわりと同じ扱いに揃えてある）。
    """
    return datetime.now(JST).replace(tzinfo=None)

from app.models.secretary import SecretaryTask, SecretaryRun, month_last_day


def period_str(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def shift_month(year: int, month: int, offset: int):
    """月を offset だけずらす。offset は負でもよい。"""
    total = (year * 12 + (month - 1)) + offset
    return total // 12, total % 12 + 1


def due_date_for(task: SecretaryTask, year: int, month: int):
    """その月の期限。当てはまらない月なら None。"""
    if task.cadence == "adhoc":
        return None
    if task.cadence == "yearly" and task.month and task.month != month:
        return None

    day = task.day_of_month
    if day is None:
        return None
    last = month_last_day(year, month)
    # 0 は月末。31日を指定しても短い月では最終日に寄せる
    day = last if day == 0 else min(int(day), last)
    return date(year, month, day)


def ensure_runs(db: Session, today: date = None) -> int:
    """先月・今月・来月の実体を、無ければ作る。作った数を返す。"""
    today = today or today_jst()
    created = 0

    tasks = db.query(SecretaryTask).filter(SecretaryTask.active.is_(True)).all()
    if not tasks:
        return 0

    months = []
    for offset in (-1, 0, 1):
        months.append(shift_month(today.year, today.month, offset))

    # 既にある分を一度に引いて、1件ずつ問い合わせないようにする
    periods = [period_str(y, m) for y, m in months]
    existing = {
        (r.task_id, r.period)
        for r in db.query(SecretaryRun.task_id, SecretaryRun.period)
        .filter(SecretaryRun.period.in_(periods))
        .filter(SecretaryRun.task_id.isnot(None))
        .all()
    }

    for task in tasks:
        for year, month in months:
            period = period_str(year, month)
            if (task.id, period) in existing:
                continue
            due = due_date_for(task, year, month)
            if due is None:
                continue
            # 決まりを作った月より前には遡らない。遡ると、入れた直後に
            # 先月分までまとめて「期限切れ」で出てきてしまう。
            # 作った月の中は、日が過ぎていても出す（やったかどうかは本人が知っている）
            if task.created_at and period < period_str(task.created_at.year,
                                                       task.created_at.month):
                continue
            ty, tm = shift_month(year, month, task.target_month_offset or 0)
            db.add(SecretaryRun(
                task_id=task.id,
                title=task.title,
                area=task.area,
                period=period,
                target_period=period_str(ty, tm) if task.target_month_offset else None,
                due_date=due,
                lead_days=task.lead_days or 0,
                status="open",
                source="auto",
                checklist=task.checklist,
                ref_url=task.link_url,
            ))
            created += 1

    if created:
        db.commit()
    return created


def visible_from(run: SecretaryRun) -> date:
    """いつから「やること」に出すか。"""
    return run.due_date - timedelta(days=run.lead_days or 0)


# ---------------------------------------------------------------- 初期の決まり
# 画面から足せるが、何も無い状態だと使い始められないので最初に入れておく。
# 日付は聞き取りから置いたもので、画面で直せる。
SEED = [
    # ---- 建設
    dict(area="construction", sort_order=10, title="勤怠表を印刷する",
         cadence="monthly", day_of_month=0, lead_days=3),
    dict(area="construction", sort_order=20, title="請求書を作って送る",
         cadence="monthly", day_of_month=0, lead_days=5,
         checklist="請求書を作る\n送る\n送った控えを税理士ドライブに入れる"),
    dict(area="construction", sort_order=30,
         title="届いた請求書をスキャンして税理士ドライブに入れる",
         cadence="monthly", day_of_month=5, lead_days=4, target_month_offset=-1,
         checklist="メールで届いた分\n紙で届いた分をスキャン",
         note="月初に届く。メール・紙の両方がそろってから入れる"),
    dict(area="construction", sort_order=40,
         title="三井住友カードの明細を見て、フォルダに入れる",
         cadence="monthly", day_of_month=5, lead_days=4, target_month_offset=-1,
         checklist="身に覚えのない加盟店が無いか\n金額が飛んでいないか\n同じ店で二重に引かれていないか\n明細をフォルダに入れる",
         note="不正利用の確認もここで行う"),
    dict(area="construction", sort_order=50,
         title="給与明細の詳細をLINEで送る",
         cadence="monthly", day_of_month=7, lead_days=2),
    dict(area="construction", sort_order=60,
         title="税理士ドライブの債権管理データを見る",
         cadence="monthly", day_of_month=15, lead_days=3),

    # ---- 物販
    dict(area="resale", sort_order=110, title="2か月前の締めをする",
         cadence="monthly", day_of_month=15, lead_days=0, target_month_offset=-2,
         checklist="RMS店舗別内訳書を入れる\nヤマトの請求書を入れる\nアップサイダーの明細を入れる\n月次管理表の「書類」で欠けが無いか見る",
         link_url="#/accounting"),
    dict(area="resale", sort_order=120,
         title="アップサイダーの明細を月次管理表に入れる",
         cadence="monthly", day_of_month=15, lead_days=3, target_month_offset=-1,
         checklist="明細を落とす\n身に覚えのない加盟店が無いか見る\n月次管理表の「書類」に入れる",
         link_url="#/accounting",
         note="法人カード。不正利用の確認もここで行う"),
    dict(area="resale", sort_order=130,
         title="マレフィオーレの請求書が月次管理表に入っているか見る",
         cadence="monthly", day_of_month=15, lead_days=3, target_month_offset=-1,
         link_url="#/accounting",
         note="LINEで都度届く。ダウンロードフォルダに落としたものを書類に入れる"),

    # ---- お金まわり（振込。漏れると困るもの）
    dict(area="money", sort_order=210, title="あざみ就労支援の請求を振り込む",
         cadence="monthly", day_of_month=10, lead_days=7, target_month_offset=-1,
         note="月初に azami@kounuma-hukusikai.or.jp から請求メールが届く"),
    dict(area="money", sort_order=220, title="エジソンの請求を入金予約する",
         cadence="monthly", day_of_month=0, lead_days=10, target_month_offset=-1,
         checklist="請求書の金額を確かめる\n入金予約する\n請求書を月次管理表に入れる",
         link_url="#/accounting",
         note="seikyu@edisonmama.com から届く。月末締め翌月末払い"),
]


def seed_if_empty(db: Session) -> int:
    """決まりが1件も無いときだけ、聞き取りの内容を入れる。"""
    if db.query(SecretaryTask.id).first():
        return 0
    for row in SEED:
        db.add(SecretaryTask(**row))
    db.commit()
    return len(SEED)
