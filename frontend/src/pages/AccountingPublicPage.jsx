import MonthlySummaryPage from './MonthlySummaryPage'

/**
 * 月次管理表の公開ページ。税理士にURLを渡して見てもらうためログイン不要。
 *
 * 実際の売上と利益が出るので、誰でも開ける形にはしていない。
 * URLに入っている合言葉が合ったときだけ、サーバーが数字を返す。
 * 合言葉を作り直せば、前のURLはその場で開かなくなる。
 *
 * 見るだけのページで、取り込みや書き換えはできない（サーバー側でも
 * GETしか通していない）。
 */

export default function AccountingPublicPage() {
  const share = (window.location.hash || '').match(/[?&]share=([^&]+)/)?.[1] || ''

  if (!share) {
    return (
      <div style={{ maxWidth: 640, margin: '60px auto', padding: 24, fontFamily: 'sans-serif' }}>
        <h1 style={{ fontSize: 20, margin: '0 0 10px' }}>月次管理表</h1>
        <p style={{ color: '#475569', lineHeight: 1.9 }}>
          このページは、お渡ししたURLからお開きください。
          URLの末尾（<code>?share=…</code>）が欠けていると開けません。
        </p>
      </div>
    )
  }

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto', padding: '20px 16px 60px', fontFamily: 'sans-serif' }}>
      <h1 style={{ fontSize: 22, margin: '0 0 4px' }}>📊 月次管理表（発生ベース）</h1>
      <div style={{ fontSize: 13, color: '#475569', lineHeight: 1.9, marginBottom: 18 }}>
        株式会社美園工芸社　通販部門。その月に実際に発生したぶんだけを拾う形に組み替えた表です。
        タオタロウ（代行会社）へのチャージは前払金なので原価に入れていません。
        考え方は <a href="#/accounting-design-public" style={{ color: '#1d4ed8' }}>設計のページ</a> にあります。
      </div>
      <MonthlySummaryPage share={share} />
    </div>
  )
}
