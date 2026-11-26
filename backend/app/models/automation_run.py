"""自動で動いたものの記録。

「何が勝手に動くか」の説明より、「いつ何をしたか」のほうが知りたい。
巡回のたびに書くと1分おきの在庫同期で埋まるので、実際に何かを
したときだけ残す（見つけた・入れた・止まった・送った）。
"""
from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from app.core.database import Base


class AutomationRun(Base):
    __tablename__ = "automation_runs"

    id = Column(Integer, primary_key=True, index=True)
    job = Column(String, index=True)      # automations.py の id と同じ
    area = Column(String, index=True)     # amazon / rakuten / both
    # ok=やった / stopped=止まって人待ち / error=失敗
    status = Column(String, index=True, default="ok")
    summary = Column(Text)                # 1行で読める形
    created_at = Column(DateTime(timezone=True),
                        server_default=func.now(), index=True)
