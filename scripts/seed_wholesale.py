"""卸発注の初期データを入れる。

過去に送っていた発注書とメールから起こしたもの。
すでに同じ名前があれば飛ばすので、何度実行しても増えない。

使い方（サーバー上で1回だけ）:
  python scripts/seed_wholesale.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "backend"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.core.database import SessionLocal            # noqa: E402
from app.models.wholesale import (                    # noqa: E402
    WholesaleSupplier, WholesaleItem,
)
from app.models.rakuten_product import RakutenProduct  # noqa: E402

# 納品先。同じリビック宛でも商品で送り先が変わるので分けて持つ
MISONO = ("〒337-0024", "埼玉県さいたま市見沼区片柳1092", None)
AZAMI = ("〒337-0026", "埼玉県さいたま市見沼区染谷 2-145",
         "あざみ共同作業所　小野川様宛")
MISONO_NOTE = ("〒337-0024", "埼玉県さいたま市見沼区片柳1092",
               "モミモミは美園工芸社宛でお願いいたします。")

SUPPLIERS = [
    dict(name="株式会社エジソン販売", honorific="御中",
         email_to="order@edisonmama.com",
         email_cc="hayashi@edisonmama.com",
         mail_subject="発注書になります",
         mail_greeting="ご担当者様",
         mail_body="お世話になっております。\n\n発注書になります。\n\n"
                   "お手配のほどよろしくお願いいたします。",
         sort_order=1),
    dict(name="株式会社リビック", honorific="御中",
         email_to="inui.ribic@gmail.com",
         mail_subject="発注書になります",
         mail_greeting="乾様",
         mail_body="お世話になっております。\n\n発注書になります。入金済です。\n\n"
                   "お手数ですが、入荷予定日を教えていただけますと幸いです。\n\n"
                   "お手配のほどよろしくお願いいたします。",
         sort_order=2),
]

# (取引先, JAN, 発注書に出す名前, 卸単価(税抜), 納品先, 楽天SKU)
# 楽天SKUは在庫を画面に出すための紐付け。無くても発注はできる
ITEMS = [
    ("株式会社エジソン販売", "4544742902049", "お箸Ⅰ　ぱんだ　右手", 576, MISONO, "39_panda"),
    ("株式会社エジソン販売", "4544742900465", "お箸KIDS　右手", 576, MISONO, "40"),
    ("株式会社エジソン販売", "4544742900243", "お箸Ⅱ　右手", 576, MISONO, "41"),
    ("株式会社エジソン販売", "4544742993863", "お箸Ⅲ　右手", 720, MISONO, "42"),
    ("株式会社エジソン販売", "4544742903206", "お箸ラストステップ大人用(右手用）", 864, MISONO, "54"),
    ("株式会社エジソン販売", "4544742903183", "お箸ラストステップ子供用(右手用）", 720, MISONO, "53"),
    ("株式会社リビック", None, "ヘアカットモンスターかんたん前髪セルフカッター", 700, AZAMI, "45"),
    ("株式会社リビック", None, "モミモミ　ブラック", 764, MISONO_NOTE, "271"),
    ("株式会社リビック", None, "モミモミ　ラベンダー", 764, MISONO_NOTE, "270"),
]


def main():
    db = SessionLocal()
    try:
        sup = {}
        for d in SUPPLIERS:
            row = (db.query(WholesaleSupplier)
                   .filter(WholesaleSupplier.name == d["name"]).first())
            if row is None:
                row = WholesaleSupplier(**d)
                db.add(row)
                db.flush()
                print(f"取引先を追加: {d['name']}")
            else:
                print(f"取引先はすでにあります: {d['name']}")
            sup[d["name"]] = row

        added = 0
        for sname, jan, name, price, (z, addr, note), sku in ITEMS:
            s = sup[sname]
            exists = (db.query(WholesaleItem)
                      .filter(WholesaleItem.supplier_id == s.id,
                              WholesaleItem.name == name).first())
            if exists:
                continue
            pid = None
            if sku:
                p = (db.query(RakutenProduct)
                     .filter(RakutenProduct.sku == sku).first())
                pid = p.id if p else None
                if not p:
                    print(f"  楽天SKU {sku} が見つかりません（在庫は出ませんが発注はできます）")
            db.add(WholesaleItem(
                supplier_id=s.id, rakuten_product_id=pid,
                jan_code=jan, name=name, unit_price=price,
                deliver_zip=z, deliver_address=addr, deliver_note=note,
                sort_order=added))
            added += 1

        db.commit()
        print(f"商品を{added}件追加しました")
        print(f"合計: 取引先{db.query(WholesaleSupplier).count()}社 / "
              f"商品{db.query(WholesaleItem).count()}件")
    finally:
        db.close()


if __name__ == "__main__":
    main()
