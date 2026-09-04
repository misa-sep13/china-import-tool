from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    APP_NAME: str = "中国輸入管理ツール"
    DATABASE_URL: str = "sqlite:///./china_import.db"
    SECRET_KEY: str = "change-me-in-production"

    # Amazon SP-API
    SP_API_REFRESH_TOKEN: Optional[str] = None
    SP_API_LWA_APP_ID: Optional[str] = None
    SP_API_LWA_CLIENT_SECRET: Optional[str] = None
    SP_API_AWS_ACCESS_KEY: Optional[str] = None
    SP_API_AWS_SECRET_KEY: Optional[str] = None
    SP_API_ROLE_ARN: Optional[str] = None
    SP_API_MARKETPLACE: str = "JP"
    # 出品に使う。セラーセントラルの「出品用アカウント情報」に出ている出品者ID
    SP_API_SELLER_ID: Optional[str] = None

    # Tool4Seller
    TOOL4SELLER_EMAIL: Optional[str] = None
    TOOL4SELLER_PASSWORD: Optional[str] = None
    TOOL4SELLER_SHOP_ID: Optional[str] = None

    # Amazon Ads API
    ADS_API_CLIENT_ID: Optional[str] = None
    ADS_API_CLIENT_SECRET: Optional[str] = None
    ADS_API_REFRESH_TOKEN: Optional[str] = None

    # 楽天ウェブサービス（IchibaItem/Search、SEO順位チェック用）
    RAKUTEN_APP_ID: Optional[str] = None
    RAKUTEN_ACCESS_KEY: Optional[str] = None

    class Config:
        env_file = ".env"
        # .env はバックエンドだけでなくローカルのバッチスクリプトとも共用しており、
        # ここに定義していないキー（AUTH_SERVICE_TOKEN等）が入ることがある。
        # 既定のforbidだと起動自体が落ちるので、知らないキーは無視する
        extra = "ignore"

settings = Settings()
