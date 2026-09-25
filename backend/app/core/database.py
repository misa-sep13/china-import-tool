from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from app.core.config import settings

db_url = settings.DATABASE_URL

# 使うドライバを URL に書いておく。SQLAlchemy 2.1 から postgresql:// の
# 既定が psycopg2 から psycopg（v3）に変わり、入れていない psycopg を
# 読みに行って起動できなくなった。既定に任せず、こちらで指定する
if db_url.startswith("postgres://"):          # 古い書き方のURLも通す
    db_url = "postgresql+psycopg2://" + db_url[len("postgres://"):]
elif db_url.startswith("postgresql://"):
    db_url = "postgresql+psycopg2://" + db_url[len("postgresql://"):]

connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}

engine = create_engine(db_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
