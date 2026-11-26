/**
 * 手でSKUを紐づけるときの歯止め。
 *
 * 配送依頼の明細を手で紐づけるとき、行のURLと選んだSKUのURLが
 * 別のページでも、何も言わずに通っていた。
 *
 * 実際、巾着リュック（10.5元・別ページ）の行が「ランチバッグ y58_black」
 * （2.9元）に紐づけられ、在庫が30個ぶん増え、原価が ¥122 → ¥311 に
 * なっていた。LINEの「大きく動いた原価」で気づくまで分からなかった。
 *
 * 自動照合はURLと色で引くので、こういう取り違えは起こせない。
 * 手で選ぶときだけ穴が開いている。選んだ瞬間に両方のURLを並べて
 * 見せれば、その場で気づける。
 *
 * 同じ商品を別のページで買い直すこと自体はよくあるので、止めはしない。
 * 「進む」を選べるようにして、マスタのURLも直すよう促す。
 */

/** 1688のURLから商品IDだけ取り出す。backend の _url_key と同じ考え方。 */
export function urlKey(url) {
  const value = String(url || '').trim()
  if (!value) return ''
  const offer = value.match(/\/offer\/(\d+)\.html/)
  if (offer) return `1688:${offer[1]}`
  const id = value.match(/[?&]id=(\d+)/)
  if (id) return `id:${id[1]}`
  return value.split('#')[0].replace(/\/+$/, '')
}

function shortUrl(url) {
  const k = urlKey(url)
  return k.startsWith('1688:') ? `1688.com/offer/${k.slice(5)}` : (k || '(URLなし)')
}

function money(v) {
  const n = Number(v)
  return Number.isFinite(n) && n > 0 ? `${n}元` : ''
}

/**
 * 紐づけてよいか確かめる。進めてよければ true。
 *
 * row     … 配送依頼の明細（buy_url / name_cn / qty / unit_price_cny）
 * product … 選んだ商品（sku / name / buy_url / price）
 *
 * どちらかのURLが無いときは比べようがないので黙って通す。
 */
export function confirmLinkMismatch(row, product) {
  if (!row || !product) return true
  const rowKey = urlKey(row.buy_url)
  const skuKey = urlKey(product.buy_url)
  if (!rowKey || !skuKey || rowKey === skuKey) return true

  const rowPrice = money(row.unit_price_cny)
  const skuPrice = money(product.price)
  const qty = Number(row.qty) > 0 ? ` × ${row.qty}個` : ''

  return window.confirm(
    '⚠ 仕入URLが違います\n\n'
    + 'この行のURLと、選んだSKUに登録してあるURLが別のページです。\n'
    + '別の商品を取り違えていないか確かめてください。\n\n'
    + `【この行】${String(row.name_cn || row.name_jp || '(名称なし)').slice(0, 40)}\n`
    + `  ${shortUrl(row.buy_url)}${rowPrice ? `　${rowPrice}${qty}` : qty}\n\n`
    + `【選んだSKU】${product.sku} ${product.name || ''}\n`
    + `  ${shortUrl(product.buy_url)}${skuPrice ? `　${skuPrice}` : ''}\n\n`
    + '同じ商品を別のページで買い直したのなら「OK」。\n'
    + 'そのあと商品マスタのURLも新しいページに直してください\n'
    + '（直さないと次も照合できません）。\n\n'
    + '取り違えなら「キャンセル」。'
  )
}
