from sqlalchemy import Column, Integer, String, Float, Boolean, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.core.database import Base


class AmazonResearch(Base):
    """Amazonの競合リサーチ（案件の単位）。

    カテゴリや思いつきごとに1つ作り、その中に候補商品を並べていく。
    """
    __tablename__ = "amazon_researches"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    note = Column(Text)
    is_archived = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AmazonResearchItem(Base):
    """候補商品1件（シートの1行）。

    リサーチ段階で手に入る情報だけから原価と粗利率を出すのが目的。
    原価はサーバー側で計算して持たせる（画面ごとに計算式がずれないように）。
    """
    __tablename__ = "amazon_research_items"

    id = Column(Integer, primary_key=True, index=True)
    research_id = Column(Integer, ForeignKey("amazon_researches.id"), index=True)
    sort_order = Column(Integer, default=0)

    # 起点
    asin = Column(String, index=True)
    image_url = Column(Text)            # 画像。data URL も入る
    competitor_name = Column(Text)      # ライバル商品名

    # セラースカウトから入る（SP-APIでは取れない）
    monthly_sales = Column(Integer)     # 月間販売個数
    review_count = Column(Integer)
    review_rate = Column(Float)

    # 手で調べて入れる
    winning_factors = Column(Text)      # 勝てる要素（JSON配列）
    note = Column(Text)

    # SP-APIで入る
    len_a = Column(Float)               # 長辺cm
    len_b = Column(Float)               # 中辺cm
    len_c = Column(Float)               # 短辺cm
    weight = Column(Float)              # 実重量kg
    size_type = Column(String)          # small/standard/oversize。空なら自動判定
    price = Column(Float)               # 売価
    fulfill = Column(String)            # FBA / 自己発送
    fee = Column(Float)                 # 販売手数料 + FBA配送代行手数料
    seller_count = Column(Integer)
    spec = Column(Text)                 # 商品仕様
    rank_text = Column(String)          # ランキング

    # 中国側（手入力）
    urls_1688 = Column(Text)            # JSON配列
    parts = Column(Text)                # JSON配列 [{price, qty}] 単価(元)×入数
    options = Column(Text)              # JSON配列 [{label, price}] オプション代(元)
    pack_factor = Column(Integer)       # 箱詰め係数(%)。未設定なら既定を使う

    # 計算結果（サーバーで出して保存する。一覧の並べ替えや検索に使うため）
    billable_kg = Column(Float)         # 決済重量
    china_jpy = Column(Float)           # 中国側原価（円）
    ship_jpy = Column(Float)            # 国際送料（円）
    cost_jpy = Column(Float)            # 原価（円）
    profit_jpy = Column(Float)          # 粗利
    profit_rate = Column(Float)         # 粗利率(%)

    status = Column(String, default="researching", index=True)  # researching/ordered/rejected
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AmazonResearchSettings(Base):
    """原価計算の前提。全リサーチで共通。

    初期値はタオタロウの実績から出している（もらったツールはラクマート実績だった）:
      輸送単価7.00元/kg = 国際送料1,022元 ÷ 計費重量146kg
      輸入関連費15.4%   =（納税額5,774円 + 通関料の按分）÷ 課税前原価39,687円
    1便からの実測なので、便が貯まったら画面から直せるようにしてある。
    """
    __tablename__ = "amazon_research_settings"

    id = Column(Integer, primary_key=True)
    exchange_rate = Column(Float)          # 市場為替（円/元）
    rate_adjust = Column(Float, default=6) # 決済レート補正(%)。送金手数料などの上乗せ
    china_fixed = Column(Float, default=0.50)   # 中国側の基本作業費（元/点）
    tariff_rate = Column(Float, default=15.4)   # 輸入関連費(%)
    pack_factor = Column(Integer, default=100)  # 箱詰め係数(%)の既定
    ship_yuan = Column(Float, default=7.0)      # 輸送単価（元/kg）
    ship_mode = Column(String, default="sea")   # sea / air
    customs_fee_jpy = Column(Float, default=2000)  # 通関料（船便のみ・便あたり）
    rate_updated_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AmazonResearchSheet(Base):
    """競合リサーチシート（HTML版）の保存先。

    もらったHTMLは1枚で完結していて、状態を丸ごとJSONで持っている。
    そのHTMLをそのまま画面に埋め込み、保存先だけ localStorage から
    ここへ差し替える。ブラウザの5MB制限を受けず、別のPCからも同じものが見える。

    workspace は共有の単位（HTMLの #w=xxx と同じ考え方）。
    既定は "default"。
    """
    __tablename__ = "amazon_research_sheets"

    id = Column(Integer, primary_key=True, index=True)
    workspace = Column(String, index=True, default="default")
    data = Column(Text)                 # シート全体のJSON
    size_bytes = Column(Integer, default=0)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AmazonResearchSheetBackup(Base):
    """シートの世代バックアップ。

    保存のたびに丸ごと上書きするので、誤操作で消したときに戻せるよう
    一定間隔で世代を残す（もらったHTMLの控えJSONと同じ考え方）。
    """
    __tablename__ = "amazon_research_sheet_backups"

    id = Column(Integer, primary_key=True, index=True)
    workspace = Column(String, index=True, default="default")
    data = Column(Text)
    size_bytes = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
