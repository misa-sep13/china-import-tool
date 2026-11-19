/**
 * 税理士向けの公開ページかどうか。
 *
 * 公開ページは合言葉つきのURLで開く。中で使う画面はツール内のものと
 * 同じなので、ここを見て「読むだけ」に切り替える。
 *   ・APIの呼び出しに合言葉を足す（api/client.js）
 *   ・取り込みや確定のボタンを出さない（各画面）
 */

export const PUBLIC_PATH = '/accounting-public'

export function shareToken() {
  const h = window.location.hash || ''
  if (!h.includes(PUBLIC_PATH) && !window.location.pathname.endsWith(PUBLIC_PATH)) return ''
  const q = h.split('?')[1] || window.location.search.replace(/^\?/, '')
  return new URLSearchParams(q).get('share') || ''
}

export function isPublicView() {
  return !!shareToken()
}
