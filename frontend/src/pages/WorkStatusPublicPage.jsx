import { useMemo } from 'react'
import WorkStatusPage from './WorkStatusPage'

/**
 * 状況確認シートの共有ページ。
 *
 * 外注さんがログインなしで開いて、自分の番のものを見たり、
 * 質問を書いたりできるようにするためのもの。URLに入れた合言葉で通す。
 *
 * 見えるのはこの一覧だけで、他の画面には行けない。サーバー側も
 * work-status 以外は受け付けない。工程・誰の番・メモと質問だけ触れて、
 * SKUや商品名を書き換えたり、行を足したり消したりはできない。
 */
export default function WorkStatusPublicPage() {
  // 合言葉はURLのどこに入っていても拾う。
  // HashRouterなので #/work-public?share=... の形だと ? はハッシュ側に入り、
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
        <b style={{ fontSize: 16, color: '#0f172a' }}>📋 状況確認シート</b>
        <span style={{ fontSize: 12, color: '#64748b', marginLeft: 10 }}>
          いま誰の番かを選び、聞きたいことは「質問」に書いてください
        </span>
      </div>
      <div style={{ padding: 14, maxWidth: 1400, margin: '0 auto' }}>
        {/* 外注さんの画面なので、書いた質問は staff から出たものになる */}
        <WorkStatusPage share={share} me="staff" />
      </div>
    </div>
  )
}
