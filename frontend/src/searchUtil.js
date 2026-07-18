export const toHalf = (s) =>
  (s || '').replace(/[Ａ-Ｚａ-ｚ０-９]/g, c => String.fromCharCode(c.charCodeAt(0) - 0xFEE0))

export const normalizeSearch = (s) => toHalf(s).toLowerCase()
