# Supabaseの容量が足りなくなったとき

画像・動画・PDF・シートのバックアップをデータベースに直接入れているので、
容量はここから増える。まず何が大きいかを見てから減らす。

## 1. 何が大きいか見る

SupabaseのSQL Editorに貼って実行する。

```sql
select
  relname as "テーブル",
  pg_size_pretty(pg_total_relation_size(c.oid)) as "合計",
  to_char(c.reltuples::bigint, 'FM999,999,999') as "行数(概算)"
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relkind = 'r'
order by pg_total_relation_size(c.oid) desc
limit 15;
```

容量を食いやすいのは次の5つ。

| テーブル | 中身 | 消していいか |
| --- | --- | --- |
| `amazon_research_sheet_backups` | リサーチシートの世代控え | 古い世代は消してよい |
| `image_request_files` | 納品データ（画像ZIP・動画） | 完了したものは消してよい |
| `image_request_photos` | 画像依頼の参考画像 | 完了したものは消してよい |
| `amazon_listing_images` | 出品用の商品画像（base64） | 出品が通ったものは消してよい |
| `import_permits` | 輸入許可書のPDF | **消さない**（控えが要る） |

## 2. すぐ減らせるもの

### シートの世代控え（たいていここが一番大きい）

直近12世代だけ残して消す。ツール側も12世代に変えてあるので、
次に保存した時点で自動的にこの状態になる。

```sql
delete from amazon_research_sheet_backups
where id not in (
  select id from amazon_research_sheet_backups
  order by created_at desc limit 12
);
```

### 完了した画像依頼の写真・納品データ

ツールが起動時に消すので、普通は手で消す必要はない。
すぐ空けたいときだけ実行する。

```sql
delete from image_request_photos
where request_id in (select id from image_requests where status = 'done');

delete from image_request_files
where request_id in (select id from image_requests where status = 'done');
```

### 出品が終わった商品画像

Amazonは取り込みが済めば自社サーバーの画像を見に来ない。
出品が `live` になったものは消してよい。

```sql
delete from amazon_listing_images
where listing_id in (select id from amazon_listings where status = 'live');
```

## 3. 消したあとの注意

Postgresは行を消しても、そのぶんのファイルがすぐ縮むわけではない。
空き容量に反映されないときは、SQL Editorで次を実行する。

```sql
vacuum full amazon_research_sheet_backups;
vacuum full image_request_photos;
vacuum full image_request_files;
vacuum full amazon_listing_images;
```

`vacuum full` は実行中そのテーブルを触れなくするので、使っていない時間に行う。

## 4. 通信量（Egress）が原因のとき

容量ではなく転送量で超えることもある。心当たりは次の2つ。

- 画像を開くたびにデータベースから読み出している
  （出品用の画像は24時間のキャッシュ指定済み）
- 毎日のDBスナップショット（`backups/` に入るJSON）

どちらも効かないときは、画像だけSupabase Storageへ移すのが本筋。
データベースに入れているかぎり、読むたびに転送量を使う。
