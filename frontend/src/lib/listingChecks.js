/**
 * 出品原稿のチェック。リサーチシートの「🏷 出品原稿をつくる」と同じ判定。
 *
 * 商品登録タブとリサーチシートは同じ中身を扱うので、判定も揃えておく。
 * シートは1枚で完結する配布用HTMLなので読み込みを共有できず、
 * NG_KEYWORDS は frontend/public/research/sheet.html にも同じものがある。
 * 片方だけ直すとずれるので、直すときは両方を直すこと。
 */

const NG_KEYWORDS = [
  // 配送・価格の訴求
  '無料', '送料込', '最低価格', '最安', '激安', '格安', '安い', '特価', '特売', '特別価格',
  '半額', '割引', '値下げ', 'お得', 'お買い得', 'バーゲン', 'アウトレット', 'クリアランス',
  'セール', '破格', 'プライスダウン', '%オフ', '％オフ', '%off', '％off',
  // 主観的・最上級の主張
  '最高', '最強', '最上級', '世界一', '世界初', '業界初', '日本一', '決定版',
  '高品質', '品質保証', '効果絶大', '優位性', '権威', '完璧', 'ベストセラー',
  'no.1', 'ナンバーワン', '素晴らしい',
  // 人気・評判・レビューへの言及
  '人気', '売れ筋', '話題', 'ランキング', '口コミ', 'レビュー', '体験談', '愛用',
  'おすすめ', 'オススメ', 'お勧め', 'お薦め', 'おススメ', '推奨', '推選',
  // 一時的・希少性の訴求
  '限定', '新作', '新発売', '最新', '即納', '入荷', '在庫限り', '先着', '早い者勝ち',
  '注文殺到', '今なら', '年末商戦', '希少', '現行モデル',
  // Amazonへの言及・他社比較・保証
  'amazon', 'アマゾン', '他社', '保証付',
]
const NG_ASIN = /^b0[a-z0-9]{8}$/     // 自社・他社を問わずASINは入れられない

/** 語が禁止語を含むか。含むならその語を返す */
export function ngHit(word) {
  const w = String(word || '').normalize('NFKC').toLowerCase()
  if (NG_ASIN.test(w)) return 'ASIN'
  return NG_KEYWORDS.find(ng => w.includes(ng)) || ''
}

/** 文を語に切る。区切り記号はシートと同じ */
export function wordsOf(text) {
  return String(text || '')
    .replace(/[【】[\]（）()「」『』・,、。/|｜･:：;；!！?？\n]/g, ' ')
    .split(/[\s　]+/)
    .filter(Boolean)
}

/**
 * 同じ語が3回以上出てくるものを返す。
 * Amazonの商品仕様エラー99300の原因になるので数える。
 */
export function repeatedWords(text, minLen = 2) {
  const cnt = new Map()
  wordsOf(text).forEach(w => {
    const k = w.normalize('NFKC').toLowerCase()
    if (k.length < minLen) return
    cnt.set(k, (cnt.get(k) || 0) + 1)
  })
  return [...cnt.entries()].filter(([, n]) => n >= 3)
}

/**
 * 親タイトルの末尾が色や個数になっていないか。
 * 親は選択肢をまとめる器なので、色は子だけに付ける。
 * 入れたまま子へコピーすると、子に色が2つ並んでしまう。
 */
export function parentColorLeft(title, childValues = []) {
  const last = String(title || '').trim().split(/\s+/).pop()
  if (!last) return ''
  const vals = childValues.map(v => String(v || '').trim()).filter(Boolean)
  return (looksLikeColor(last) || vals.includes(last)) ? last : ''
}

/** 商品タイトル1行ぶんの問題点。シートの③と同じ内容を返す */
export function titleProblems(title, max = 75) {
  const s = String(title || '').trim()
  const out = []
  if (s.length > max) out.push(`${s.length}字（${max}字まで）`)
  const ng = wordsOf(s.replace(/[【】[\]（）()]/g, ' '))
    .map(w => [w, ngHit(w)]).filter(x => x[1])
  if (ng.length) out.push('禁止語: ' + ng.map(x => `${x[0]}（${x[1]}）`).join('・'))
  const rep = repeatedWords(s)
  if (rep.length) {
    out.push('3回以上の重複: ' + rep.map(r => `${r[0]}×${r[1]}`).join('・')
      + '（エラー99300の原因）')
  }
  return out
}

/** 検索キーワードのバイト数。Amazonの上限はバイトで決まる */
export function byteLen(s) {
  return new TextEncoder().encode(String(s || '')).length
}

/**
 * 検索キーワード欄の上限。カテゴリーで違う。
 * シートのパネルと同じ2種類だけ持つ。
 */
export const KW_LIMITS = [
  { v: 500, l: 'ふつう（ホーム＆キッチン・スポーツ・おもちゃ など）500バイト未満' },
  { v: 250, l: '服・シューズ・ジュエリー・時計 250バイト未満' },
]

/**
 * 子の商品タイトルの末尾に色を入れる。シートの③と同じ考え方。
 *
 * 前の値を推測して外すと、変換中の文字が積み上がってしまうので、
 * 「色を外した土台」を覚えておき、毎回そこから作り直す。
 */
const COLOR_WORDS = [
  'ブラック', 'ホワイト', 'グレー', 'ネイビー', 'ブルー', 'レッド', 'ピンク',
  'グリーン', 'イエロー', 'ベージュ', 'ブラウン', 'パープル', 'オレンジ',
  'シルバー', 'ゴールド', 'カーキ', 'アイボリー', 'クリア', 'モカ',
  'グレージュ', 'ワインレッド', 'ライトグレー', 'ダークグレー',
  '黒', '白', '灰', '青', '赤', '緑', '黄', '紫', '茶', '銀', '金', '透明',
]

function looksLikeColor(word) {
  const w = String(word || '').trim()
  if (!w) return false
  const parts = w.split(/[/／・]/).map(x => x.trim()).filter(Boolean)
  return parts.some(p => COLOR_WORDS.some(c => p === c || p.endsWith(c)))
}

/** 末尾の色を外す。分かっている値があればそれを優先して外す */
export function stripColor(title, value) {
  const t = String(title || '').trim()
  const v = String(value || '').trim()
  if (v && t.endsWith(v)) return t.slice(0, t.length - v.length).trim()
  const parts = t.split(/\s+/)
  while (parts.length > 1 && looksLikeColor(parts[parts.length - 1])) parts.pop()
  return parts.join(' ')
}

/** 土台＋色で子タイトルを作る */
export function childTitle(base, value) {
  const b = String(base || '').trim()
  const v = String(value || '').trim()
  return v ? (b ? b + ' ' + v : v) : b
}
