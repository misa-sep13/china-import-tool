"""秘書。毎月・毎年くり返す仕事と、都度の仕事をまとめて持つ。

やることを自分で覚えておくのをやめたい、というのが始まり。
建設と物販の両方が混ざるので、area で分けて表示する。

考え方:
  - ツールは判断しない。「いつ・何を」を出すところまでが仕事で、
    やるかどうか・中身の良し悪しは人が決める
  - くり返しの決まり（SecretaryTask）から、その月の実体（SecretaryRun）が
    自動で生える。実体に完了を記録するので、履歴がそのまま残る
  - 都度の仕事は task_id を持たない実体として直接立てる
"""
import calendar

from sqlalchemy import (Column, Integer, String, Text, Date, DateTime,
                        Boolean, Float, ForeignKey, LargeBinary)
from sqlalchemy.sql import func

from app.core.database import Base


# どちらの仕事か
AREA_LABELS = {
    "construction": "建設",
    "resale": "物販",
    "money": "お金まわり",
}

# くり返しの型
#   monthly … 毎月 day_of_month 日（0 なら月末）
#   yearly  … 毎年 month 月 day_of_month 日
#   adhoc   … 自動で生やさない。都度こちらで立てる
CADENCES = ("monthly", "yearly", "adhoc")

STATUSES = ("open", "done", "skipped")


class SecretaryTask(Base):
    """くり返す仕事の決まり。"""

    __tablename__ = "secretary_tasks"

    id = Column(Integer, primary_key=True)

    title = Column(String, nullable=False)
    area = Column(String, nullable=False, default="construction", index=True)

    cadence = Column(String, nullable=False, default="monthly")
    # 何日が期限か。0 は「月末」を表す（月によって28〜31日と変わるため）
    day_of_month = Column(Integer, nullable=True)
    # yearly のときだけ使う
    month = Column(Integer, nullable=True)

    # 期限の何日前から「やること」に出すか。0 なら当日から
    lead_days = Column(Integer, nullable=False, default=3)

    # 対象の月を何か月ずらすか。「15日に2か月前の締めをする」なら -2。
    # 画面には「9月分の締め」のように出す
    target_month_offset = Column(Integer, nullable=False, default=0)

    # 手順。改行で1行ずつ
    checklist = Column(Text)
    # 開く場所（RMSの画面、カード会社の明細ページ、ドライブのフォルダなど）
    link_url = Column(String)
    note = Column(Text)

    active = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=100)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class SecretaryRun(Base):
    """その月の実体。完了の記録もここに残る。"""

    __tablename__ = "secretary_runs"

    id = Column(Integer, primary_key=True)

    # くり返しから生えたものは決まりを指す。都度の仕事は空
    task_id = Column(Integer, ForeignKey("secretary_tasks.id"), nullable=True, index=True)

    # 決まりが消えても履歴が読めるように、題と区分は実体にも持たせる
    title = Column(String, nullable=False)
    area = Column(String, nullable=False, default="construction", index=True)

    # 期限が属する月。"2026-11"。同じ決まりから二重に生えるのを防ぐ鍵
    period = Column(String, nullable=False, index=True)
    # 何月分の仕事か。締めや請求のように対象月がずれるとき用。"2026-09"
    target_period = Column(String, nullable=True)

    due_date = Column(Date, nullable=False, index=True)
    # 期限の何日前から出すか。決まりから写す（あとで決まりを変えても過去は動かさない）
    lead_days = Column(Integer, nullable=False, default=3)

    status = Column(String, nullable=False, default="open", index=True)
    done_at = Column(DateTime(timezone=True), nullable=True)
    done_note = Column(Text)

    # 振込待ちなど、金額が絡むもの
    amount = Column(Float, nullable=True)
    # auto（決まりから）／manual（手で足した）／mail（メールから拾った）
    source = Column(String, nullable=False, default="auto")
    ref_url = Column(String)
    checklist = Column(Text)

    # メールから拾ったものを二度立てないための鍵（Message-IDと添付名の組）
    source_key = Column(String, index=True)
    # 書類棚（import_permits）に入れた原本。画面からそのまま開ける
    permit_id = Column(Integer, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class SecretarySender(Base):
    """請求が届くメールの差出人。ここに登録した相手だけを見に行く。

    件名では絞らない。相手が件名を変えた時点で拾えなくなるため、
    差出人のアドレスで見る（permit_mail が差出人を見ないのと逆向きだが、
    請求書は「誰から来たか」が種別そのものなので、こちらが確実）。
    """

    __tablename__ = "secretary_senders"

    id = Column(Integer, primary_key=True)

    name = Column(String, nullable=False)          # あざみ就労支援
    # 差出人に含まれていれば一致とみなす。小文字で持つ
    match_from = Column(String, nullable=False)
    area = Column(String, nullable=False, default="money")

    # 書類棚（import_permits）に入れるときの種別
    doc_kind = Column(String, nullable=False, default="wholesale")

    # 支払期限の決め方
    #   eom      … 届いた月の月末（月末締め翌月末払いはこれ）
    #   eom_next … 翌月末
    #   day      … 届いた月の due_day 日（過ぎていれば翌月）
    #   days     … 届いた日から due_day 日後
    due_rule = Column(String, nullable=False, default="eom")
    due_day = Column(Integer, nullable=False, default=10)
    lead_days = Column(Integer, nullable=False, default=7)

    # 対応するくり返しの決まり。あれば、その月の実体に金額と原本を入れる
    # （同じ仕事が二重に並ばないようにするため）
    task_id = Column(Integer, nullable=True, index=True)

    note = Column(Text)
    active = Column(Boolean, nullable=False, default=True)
    last_found_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class SecretaryNotify(Base):
    """毎朝の知らせの設定。1行しか持たない。

    LINEのトークンはここに置かない（サーバーの環境変数で持つ）。
    ここにあるのは「何時に」「何日先まで」といった、見られて困らないもの。
    """

    __tablename__ = "secretary_notify"

    id = Column(Integer, primary_key=True, default=1)

    enabled = Column(Boolean, nullable=False, default=True)
    # 日本時間の何時に送るか
    hour = Column(Integer, nullable=False, default=7)
    # 知らせる前に請求メールを見に行くか
    fetch_mail = Column(Boolean, nullable=False, default=True)
    # 何日先の分まで入れるか。0 なら今日の分と遅れている分だけ
    ahead_days = Column(Integer, nullable=False, default=0)
    # やることが無い日も送るか。既定は送らない（鳴りすぎると見なくなる）
    send_when_empty = Column(Boolean, nullable=False, default=False)

    # 1日に何度も送らないための控え（日本時間の日付）
    last_sent_on = Column(String)
    last_sent_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class SecretaryForward(Base):
    """メールで届いたものを、そのまま別の場所へ流した記録。

    いまのところタオタロウの動画をチャットワークへ送るのに使う。
    同じメールを二度送らないための控えでもあるので、添付が無かった
    メールも「見た」として残す（次から中身を落とさずに済む）。
    """

    __tablename__ = "secretary_forwards"

    id = Column(Integer, primary_key=True)

    kind = Column(String, nullable=False, default="taotaro_video", index=True)
    mail_message_id = Column(String, index=True)
    mail_subject = Column(String)
    mail_from = Column(String)
    mail_date = Column(String)

    filename = Column(String)
    size_bytes = Column(Integer, default=0)

    # sent=そのまま送った / drive=ドライブに置いてリンクを送った
    # too_large=大きすぎて送れない / none=添付なし / error=失敗
    status = Column(String, nullable=False, default="sent", index=True)
    room_id = Column(String)
    error = Column(Text)

    # 5MBを超えてチャットワークに載らないものは、ドライブに置いて
    # リンクだけ送る。あとから見返せるようにURLを残す
    drive_url = Column(String)
    drive_file_id = Column(String)

    sent_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class SecretaryVideo(Base):
    """チャットワークに載らない動画の置き場。

    5MBを超える動画は、ツールが預かってURLで渡す。外注さんにログインは
    渡せないので、URLに入れた合言葉（長いランダム文字列）だけで開ける。
    本体を別の表にしてあるのは、一覧を引くたびに数MBを読まないため。
    """

    __tablename__ = "secretary_videos"

    id = Column(Integer, primary_key=True)
    forward_id = Column(Integer, index=True)

    # URLに入る合言葉。これを知っている人だけが開ける
    token = Column(String, nullable=False, unique=True, index=True)

    filename = Column(String, nullable=False)
    content_type = Column(String, nullable=False, default="video/mp4")
    size_bytes = Column(Integer, default=0)
    content = Column(LargeBinary)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


DUE_RULES = ("eom", "eom_next", "day", "days")


def month_last_day(year: int, month: int) -> int:
    """その月の最終日。月末が期限の仕事のために使う。"""
    return calendar.monthrange(year, month)[1]
