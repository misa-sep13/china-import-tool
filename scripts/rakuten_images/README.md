# 楽天の画像アップロード（手元のPCで実行）

商品画像をR-Cabinetへまとめて上げます。SKUごとのフォルダも作れます。

## なぜ手元のPCなのか

R-Cabinetへの書き込みは、Compassにログインしたブラウザからしか
できません。サーバー（Render）からは送れないため、手元で実行します。

## 最初の1回だけ

```
pip install playwright
python setup.py
```

トークンと店舗URL名を保存します。Compassのパスワードは保存しません
（ブラウザに一度ログインすればCookieが残るため）。

## 使い方

```
python upload_images.py --list                    # フォルダ一覧を見る
python upload_images.py --folder 12345 a.jpg b.jpg
python upload_images.py --folder 12345 --dir C:\画像フォルダ
```

上げ終わるとURLが出るので、RMSの商品登録で使ってください。

### SKUごとにフォルダを作る

「商品画像」（フォルダID 9094036）の下にSKU名のフォルダを作る運用
なので、その場で作れます。

```
python upload_images.py --new-folder y97 --parent 9094036 --dir C:\y97画像
```

同じ名前があれば作らずにそこへ入れます。

## 気をつけること

- 1枚2MBまで（R-Cabinetの上限）
- 連続で上げると弾かれるので、1.5秒あけています
- ブラウザが開きます。ログインが切れていたら画面でログインしてください
