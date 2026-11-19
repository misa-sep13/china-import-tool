import { useEffect, useState } from 'react'
import api from '../api/client'
import DepositBreakdownPage from './DepositBreakdownPage'
import FreightByShipmentPage from './FreightByShipmentPage'
import ImportTaxPage from './ImportTaxPage'
import InventoryValuePage from './InventoryValuePage'
import MonthlySummaryPage from './MonthlySummaryPage'
import AccountingDocsPage from './AccountingDocsPage'
import MonthlyAccountingDesignPage from './MonthlyAccountingDesignPage'
import WholesaleInvoicePage from './WholesaleInvoicePage'

/**
 * 月次管理表。会計まわりを1枚にまとめた画面。
 *
 * 試算表がタオタロウへデポジットした日で計上されていて、月ごとの利益の
 * 見え方が振れる。その月に実際に発生したぶんだけを拾う形（発生ベース）に
 * 組み替えるための画面。
 *
 * 設計の全体像は docs/月次管理表_発生ベース会計_設計.md にもある。
 */

const TABS = [
  { key: 'summary',  label: '📈 月次サマリー' },
  { key: 'deposit',  label: '💰 デポジット内訳' },
  { key: 'freight',  label: '🚢 便ごとの送料' },
  { key: 'wholesale', label: '🧾 卸の仕入' },
  { key: 'tax',      label: '🧾 関税・消費税' },
  { key: 'stock',    label: '📦 在庫金額' },
  { key: 'docs',     label: '📑 書類' },
  { key: 'design',   label: '📘 設計' },
]

function ShareLink() {
  // 税理士に渡すURL。実際の売上と利益が出るので、合言葉つきでだけ開く。
  // 作り直せば、いま渡してあるURLはその場で開かなくなる
  const [url, setUrl] = useState(null)
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    api.get('/accounting/share').then(r => setUrl(r.data.url || '')).catch(() => setUrl(''))
  }, [])

  const make = async (again) => {
    if (again && !window.confirm('作り直すと、いま渡してあるURLは開かなくなります。よろしいですか。')) return
    setBusy(true)
    try {
      const r = await api.post('/accounting/share')
      setUrl(r.data.url); setCopied(false)
    } finally { setBusy(false) }
  }

  const stop = async () => {
    if (!window.confirm('公開をやめます。渡してあるURLは開かなくなります。よろしいですか。')) return
    setBusy(true)
    try { await api.delete('/accounting/share'); setUrl('') } finally { setBusy(false) }
  }

  if (url === null) return null
  return (
    <div style={{ fontSize: 12, color: '#475569', marginBottom: 12,
      background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 6, padding: '8px 10px' }}>
      {!url ? (
        <>
          <b>税理士に渡すURL</b>　まだ作っていません。
          <button className="btn btn-sm btn-secondary" style={{ marginLeft: 8 }}
            disabled={busy} onClick={() => make(false)}>作る</button>
          <div style={{ marginTop: 4 }}>
            ログインなしでこの表だけを見られるURLができます。合言葉入りなので、URLを知っている人しか開けません。
          </div>
        </>
      ) : (
        <>
          <b>税理士に渡すURL</b>
          <input readOnly value={url} onFocus={e => e.target.select()}
            style={{ width: '100%', marginTop: 4, padding: '4px 6px', fontSize: 12, fontFamily: 'monospace' }} />
          <div style={{ marginTop: 4, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <button className="btn btn-sm btn-secondary" disabled={busy}
              onClick={() => { navigator.clipboard?.writeText(url); setCopied(true) }}>
              {copied ? 'コピーしました' : 'コピー'}
            </button>
            <button className="btn btn-sm btn-secondary" disabled={busy} onClick={() => make(true)}>作り直す</button>
            <button className="btn btn-sm btn-secondary" disabled={busy} onClick={stop}>公開をやめる</button>
            <span>見るだけのURLです。取り込みや書き換えはできません。</span>
          </div>
        </>
      )}
    </div>
  )
}

export default function AccountingPage() {
  // タブはURLのハッシュに残す。税理士に「このタブを見てください」と
  // URLごと渡せるようにするため
  const [tab, setTab] = useState(() => {
    const m = (window.location.hash || '').match(/[?&]tab=([a-z]+)/)
    return TABS.some(t => t.key === m?.[1]) ? m[1] : 'deposit'
  })

  useEffect(() => {
    const h = window.location.hash || ''
    const base = h.split('?')[0] || '#/accounting'
    const next = `${base}?tab=${tab}`
    if (h !== next) window.history.replaceState(null, '', next)
  }, [tab])

  return (
    <div>
      <h1 style={{ margin: '0 0 4px' }}>📊 月次管理表</h1>
      <div style={{ fontSize: 13, color: '#475569', lineHeight: 1.9, marginBottom: 14 }}>
        その月に実際に発生したぶんだけを拾う形（発生ベース）に組み替えるための画面です。
        チャージ（前払金）は原価に入れません。
      </div>

      <div style={{ display: 'flex', gap: 8, overflowX: 'auto',
        paddingBottom: 10, marginBottom: 14, borderBottom: '1px solid #e2e8f0' }}>
        {TABS.map(t => (
          <button key={t.key}
            className={`btn ${tab === t.key ? 'btn-primary' : 'btn-secondary'}`}
            style={{ whiteSpace: 'nowrap' }}
            onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'deposit' && <DepositBreakdownPage />}

      {tab === 'wholesale' && <WholesaleInvoicePage />}

      {tab === 'design' && (
        <div style={{ margin: '-14px -14px 0' }}>
          <MonthlyAccountingDesignPage />
        </div>
      )}

      {tab === 'summary' && <><ShareLink /><MonthlySummaryPage /></>}

      {tab === 'freight' && <FreightByShipmentPage />}

      {tab === 'tax' && <ImportTaxPage />}

      {tab === 'stock' && <InventoryValuePage />}

      {tab === 'docs' && <AccountingDocsPage />}
    </div>
  )
}
