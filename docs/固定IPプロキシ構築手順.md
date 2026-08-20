# 固定IPプロキシ構築手順（ConoHa VPS + squid）

## なぜ必要か

楽天ウェブサービスのAPIは、アプリごとに「Allowed IP」の登録が必須で、CIDR（範囲指定）に対応していない。
そのため以下の問題が起きていた。

- 自宅回線のIPが変わるたびにAPIが止まる（実際に1日で3回変わった）
- Render・GitHub Actionsの共有IPは毎回変わるため、そもそも登録できない
- 結果、取得処理を自宅PCでしか実行できず、PCの電源に依存していた

VPSの固定IPを経由させることで、登録するIPが1つに固定される。
Renderからも呼べるようになるため、サイト上でのその場検索と、
サーバー側での定期実行（PC不要）が可能になる。

## 構成

```
Render（本番サーバー） ─┐
                        ├─→ ConoHa VPS（固定IP・squid） ─→ 楽天API
自宅PC（バッチ）      ─┘
```

楽天に登録するAllowed IPは、VPSのIP 1つだけになる。

---

## 1. ConoHa VPSを契約する

<https://www.conoha.jp/vps/>

- プラン: **512MB**（月約460円）。プロキシを動かすだけなので最小で足りる
- イメージ: **Ubuntu**（バージョンは最新のLTSでよい）
- rootパスワードとSSHキーは、契約時の画面で設定する

作成後、コントロールパネルに表示される **IPアドレス** を控える。

## 2. VPSにログインする

ConoHaのコントロールパネルにあるコンソール（ブラウザ上の黒い画面）からログインできる。
SSHクライアントを使っても構わない。

## 3. squidを入れる

```bash
sudo apt update
sudo apt install -y squid apache2-utils
```

## 4. 接続用のユーザーを作る

`rakuten` の部分は好きな名前でよい。実行するとパスワードを2回聞かれる。
**このパスワードは後で使うので控えておく**（チャット等には貼らないこと）。

```bash
sudo htpasswd -c /etc/squid/passwd rakuten
```

## 5. squidの設定を書く

設定ファイルをまるごと差し替える。

```bash
sudo tee /etc/squid/squid.conf > /dev/null <<'EOF'
http_port 3128

# 認証（パスワードを知らないと使えない）
auth_param basic program /usr/lib/squid/basic_ncsa_auth /etc/squid/passwd
auth_param basic children 5
auth_param basic realm proxy
auth_param basic credentialsttl 2 hours
acl authenticated proxy_auth REQUIRED

# 宛先を楽天APIだけに限定する。
# 万一パスワードが漏れても、このプロキシは楽天API以外には使えない
acl rakuten dstdomain openapi.rakuten.co.jp

acl SSL_ports port 443
acl Safe_ports port 443
acl CONNECT method CONNECT

http_access deny !Safe_ports
http_access deny CONNECT !SSL_ports
http_access allow authenticated rakuten
http_access deny all

# 送信元を隠す（プロキシ利用であることを楽天側に伝えない）
forwarded_for delete
via off
EOF
```

設定を反映する。

```bash
sudo squid -k parse && sudo systemctl restart squid && sudo systemctl enable squid
```

`sudo squid -k parse` は設定ファイルの文法チェック。エラーが出た場合は再起動せず、内容を確認すること。

## 6. ポートを開ける

```bash
sudo ufw allow 22/tcp
sudo ufw allow 3128/tcp
sudo ufw --force enable
```

ConoHaのコントロールパネルで「セキュリティグループ」を設定している場合は、
そちらでも 3128/TCP の許可が必要になる。

## 7. 楽天にVPSのIPを登録する

<https://webservice.rakuten.co.jp/> の管理画面で、対象アプリの **Allowed IP** に
**VPSのIPアドレス** を追加する。

自宅のIPは消してもよいし、残しておいても構わない。

## 8. 動作確認する

手元のPCで `backend/.env` に次の行を追加する（`.env` はgitignore済み）。

```
RAKUTEN_PROXY_URL=http://rakuten:設定したパスワード@VPSのIP:3128
```

そのうえで実行する。

```bash
python scripts/proxy_test.py
```

「プロキシ経由のIP」がVPSのIPになり、楽天APIが200を返せば成功。

## 9. Renderに設定する

Renderのダッシュボード → 対象サービス → Environment に、同じ値を登録する。

- キー: `RAKUTEN_PROXY_URL`
- 値: `http://rakuten:設定したパスワード@VPSのIP:3128`

---

## 運用メモ

- OSのセキュリティ更新は、たまに `sudo apt update && sudo apt upgrade -y` を実行する
- squidが動いているかの確認: `sudo systemctl status squid`
- 接続ログ: `sudo tail -f /var/log/squid/access.log`
- パスワードを変えたい場合: `sudo htpasswd /etc/squid/passwd rakuten` の後
  `sudo systemctl restart squid`。Renderの環境変数も忘れず更新すること
