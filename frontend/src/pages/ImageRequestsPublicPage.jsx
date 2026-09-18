import { useMemo } from 'react'
import ImageRequestsPage from './ImageRequestsPage'

/**
 * 画像作成の依頼一覧の共有ページ。
 *
 * 外注さんがログインなしで開いて、自分の進み具合を書き換えられるように
 * するためのもの。URLに入れた合言葉で通す。
 *
 * 見えるのは依頼の一覧だけで、他の画面には行けない。サーバー側も
 * image-requests 以外は受け付けない。進み具合・納品先・連絡だけ触れて、
 * 依頼の中身を書き換えたり消したりはできない。
 */
export default function ImageRequestsPublicPage() {
  // 合言葉はURLのどこに入っていても拾う。
  // HashRouterなので #/image-public?share=... の形だと ? はハッシュ側に入り、
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
      <div style={{ padding: 40, color: '#64748b', fontSize: 14, lineHeight: 1.8 }}>
        合言葉が付いていないので開けません。<br />
        共有された URL をそのまま開いてください。
      </div>
    )
  }

  return (
    <div style={{ minHeight: '100vh', background: '#f8fafc' }}>
      <div style={{ padding: '14px 18px', background: '#fff',
        borderBottom: '1px solid #e5e7eb' }}>
        <b style={{ fontSize: 16, color: '#0f172a' }}>🎨 画像作成の依頼</b>
        <span style={{ fontSize: 12, color: '#64748b', marginLeft: 10 }}>
          進み具合を選んでください。完了にすると一覧から消えます
        </span>
      </div>
      <div style={{ padding: 14, maxWidth: 1300, margin: '0 auto' }}>
        <ImageRequestsPage share={share} />
      </div>
    </div>
  )
}
