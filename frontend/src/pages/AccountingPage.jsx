import { useEffect, useState } from 'react'
import DepositBreakdownPage from './DepositBreakdownPage'
import FreightByShipmentPage from './FreightByShipmentPage'
import ImportTaxPage from './ImportTaxPage'
import InventoryValuePage from './InventoryValuePage'
import MonthlySummaryPage from './MonthlySummaryPage'
import AccountingDocsPage from './AccountingDocsPage'
import MonthlyAccountingDesignPage from './MonthlyAccountingDesignPage'

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
  { key: 'tax',      label: '🧾 関税・消費税' },
  { key: 'stock',    label: '📦 在庫金額' },
  { key: 'docs',     label: '📑 書類' },
  { key: 'design',   label: '📘 設計' },
]

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

      {tab === 'design' && (
        <div style={{ margin: '-14px -14px 0' }}>
          <MonthlyAccountingDesignPage />
        </div>
      )}

      {tab === 'summary' && <MonthlySummaryPage />}

      {tab === 'freight' && <FreightByShipmentPage />}

      {tab === 'tax' && <ImportTaxPage />}

      {tab === 'stock' && <InventoryValuePage />}

      {tab === 'docs' && <AccountingDocsPage />}
    </div>
  )
}
