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
    # タオタロウ（代理購入）のAPI。トークンは "ID|シークレット" の形で、
    # 縦棒を含めた全体で1つ。発注権限そのものなのでサーバー側だけで持つ
    TAOTARO_API_TOKEN: Optional[str] = None
    TAOTARO_API_BASE: str = "https://api.yiwutaro.com"
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

    # Chatwork。画像作成指示書を外注さんへそのまま送るのに使う。
    # トークンはそのアカウントとして書き込める権限そのものなのでサーバー側だけで持つ
    CHATWORK_API_TOKEN: Optional[str] = None
    CHATWORK_API_BASE: str = "https://api.chatwork.com/v2"
    # よく使う送り先。画面で選んだものが優先される
    CHATWORK_DEFAULT_ROOM_ID: Optional[str] = None

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
