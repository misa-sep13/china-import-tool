import { useMemo } from 'react'
import KeepClaimsPage from './KeepClaimsPage'

/**
 * 商品キープの共有ページ。
 *
 * 相手（別の会社の人）がログインなしで開いて、自分のキープを
 * 登録できるようにするためのもの。URLに入れた合言葉で通す。
 *
 * 見えるのはキープの一覧だけで、他の画面には行けない。
 * サーバー側も keep-claims 以外は受け付けない。
 */
export default function KeepClaimsPublicPage() {
  // 合言葉はURLのどこに入っていても拾う。
  // HashRouterなので #/keep-public?share=... の形だと ? はハッシュ側に入り、
  // location.search には出てこない。両方見る
  const share = useMemo(() => {
    const pick = (qs) => {
      const p = new URLSearchParams(qs)
      return p.get('share') || p.get('token') || ''
    }
    const fromSearch = pick(window.location.search)
    if (fromSearch) return fromSearch
    const hash = window.location.hash || ''
    const i = hash.indexOf('?')
    return i >= 0 ? pick(hash.slice(i + 1)) : ''
  }, [])

  if (!share) {
    return (
      <div style={{ padding: 40, color: '#64748b', fontSize: 14,
        lineHeight: 1.8 }}>
        合言葉が付いていないので開けません。<br />
        共有された URL をそのまま開いてください。
      </div>
    )
  }

  return (
    <div style={{ minHeight: '100vh', background: '#f8fafc' }}>
      <div style={{ padding: '14px 18px', background: '#fff',
        borderBottom: '1px solid #e5e7eb' }}>
        <b style={{ fontSize: 16, color: '#0f172a' }}>🤝 商品キープ</b>
        <span style={{ fontSize: 12, color: '#64748b', marginLeft: 10 }}>
          先に登録したほうが独占。親ASIN単位／60日以内に発送しないと消滅
        </span>
      </div>
      <div style={{ padding: 14, maxWidth: 1100, margin: '0 auto' }}>
        <KeepClaimsPage share={share} />
      </div>
    </div>
  )
}
