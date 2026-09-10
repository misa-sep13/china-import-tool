export const toHalf = (s) =>
  (s || '').replace(/[Ａ-Ｚａ-ｚ０-９]/g, c => String.fromCharCode(c.charCodeAt(0) - 0xFEE0))

export const normalizeSearch = (s) => toHalf(s).toLowerCase()

// 絞り込みを手元で行うための判定。
// サーバーに q を投げると1文字打つたびに一覧を取り直すことになり、
// 就労支援では毎回661KBが流れていた。全件が手元にあるならここで絞る。
// 見る項目は、サーバーがWHEREに並べていたものと必ず揃えること
// （減らすと、今まで引っかかっていた言葉で出てこなくなる）。
export const matchesQuery = (q, fields) => {
  if (!q) return true
  const n = normalizeSearch(q)
  return fields.some(v => normalizeSearch(String(v || '')).includes(n))
}
