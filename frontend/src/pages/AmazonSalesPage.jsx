import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '../api/client'
import { normalizeSearch } from '../searchUtil'
import PeriodInventoryPanel from '../components/PeriodInventoryPanel'

/**
 * Amazonの売上管理（暫定）。
 *
 * 楽天のようにCSVを取り込むのではなく、日ごとに溜めている実績
 * （daily_sales）を月でまとめて出す。広告費と返品は入っていないので、
 * 画面にもその旨を出す。
 */

const C = {
  line: '#e5e7eb', sub: '#64748b', text: '#0f172a',
  good: '#16a34a', warn: '#b45309', bad: '#dc2626', key: '#2563eb',
}

const yen = (v) => `¥${Math.round(Number(v) || 0).toLocaleString()}`

function currentMonth() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

const th = { padding: '6px 8px', fontSize: 11, color: C.sub, background: '#f8fafc',
  whiteSpace: 'nowrap' }
const td = { padding: '5px 8px', fontSize: 12, borderTop: `1px solid ${C.line}` }
const num = { ...td, textAlign: 'right', whiteSpace: 'nowrap' }

export default function AmazonSalesPage() {
  const [period, setPeriod] = useState(currentMonth())
  const [search, setSearch] = useState('')

  const monthsQ = useQuery({
    queryKey: ['amazon-sales-months'],
    queryFn: () => api.get('/amazon-sales/months').then(r => r.data),
  })

  const q = useQuery({
    queryKey: ['amazon-sales-summary', period],
    queryFn: () => api.get('/amazon-sales/summary', { params: { period } })
      .then(r => r.data),
    enabled: !!period,
  })

  const t = q.data?.totals
  const rows = useMemo(() => {
    const items = q.data?.items || []
    const s = normalizeSearch(search.trim())
    if (!s) return items
    return items.filter(i => normalizeSearch(`${i.sku} ${i.name}`).includes(s))
  }, [q.data, search])

  return (
    <div style={{ padding: 2, minWidth: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12,
        marginBottom: 12, flexWrap: 'wrap' }}>
        <h2 style={{ fontSize: 18, margin: 0 }}>📈 Amazon 売上管理</h2>
        <input type="month" value={period}
          onChange={e => setPeriod(e.target.value)}
          style={{ fontSize: 13, width: 150 }} />
        {(monthsQ.data?.months || []).length > 0 && (
          <select value="" onChange={e => e.target.value && setPeriod(e.target.value)}
            style={{ fontSize: 12, width: 150 }}>
            <option value="">実績のある月から選ぶ</option>
            {monthsQ.data.months.map(m => <option key={m} value={m}>{m}</option>)}
          </select>
        )}
        <span style={{ fontSize: 11, color: C.warn }}>
          暫定版：広告費と返品・返金は入っていません
        </span>
      </div>

      <PeriodInventoryPanel platform="amazon" title="📦 期末在庫金額（Amazon）" />

      {q.isLoading && (
        <div className="card" style={{ color: C.sub }}>読み込み中…</div>
      )}

      {t && (
        <>
          <div style={{ display: 'grid', marginBottom: 16, gap: 12,
            gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
            <Card label="売上" value={yen(t.revenue)} color={C.key} />
            <Card label="利益（暫定）" value={yen(t.profit)} color={C.good} />
            <Card label="利益率" value={`${t.profit_rate}%`} color={C.good} />
            <Card label="販売数" value={Number(t.units).toLocaleString()} />
            <Card label="原価" value={yen(t.cost)} color={C.bad} />
            <Card label="原価率" value={`${t.cost_rate}%`} color={C.bad} />
            <Card label="Amazon手数料" value={yen(t.amazon_fee)} />
            <Card label="FBA手数料" value={yen(t.fba_fee)} />
          </div>

          {/* 原価が入っていない商品があると利益が多めに出る。黙って出さない */}
          {q.data.no_cost_count > 0 && (
            <div style={{ marginBottom: 12, fontSize: 12, padding: '8px 10px',
              borderRadius: 6, background: '#fffbeb', border: '1px solid #fcd34d',
              color: '#92400e' }}>
              <b>原価が入っていない商品が {q.data.no_cost_count} 件あります。</b>
              そのぶん利益が多めに出ています：
              {(q.data.no_cost_skus || []).join('、')}
              {q.data.no_cost_count > 20 && ' ほか'}
            </div>
          )}

          <div className="card" style={{ padding: 0 }}>
            <div style={{ padding: 10, display: 'flex', gap: 10,
              alignItems: 'center', flexWrap: 'wrap' }}>
              <b style={{ fontSize: 13 }}>SKUごと（{rows.length}件）</b>
              <input value={search} onChange={e => setSearch(e.target.value)}
                placeholder="SKU・商品名で絞り込み"
                className="search-input-ja" style={{ width: 220 }} />
            </div>
            <div style={{ overflow: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr>
                    <th style={{ ...th, textAlign: 'left' }}>SKU</th>
                    <th style={{ ...th, textAlign: 'left' }}>商品名</th>
                    {['販売数', 'うちVine', '売上', '値引き', '原価', '原価率',
                      'Amazon手数料', 'FBA手数料', '利益', '利益率'].map(h => (
                        <th key={h} style={{ ...th, textAlign: 'right' }}>{h}</th>
                      ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map(i => (
                    <tr key={i.sku}>
                      <td style={{ ...td, fontFamily: 'monospace', fontSize: 11 }}>
                        {i.sku}
                      </td>
                      <td style={{ ...td, maxWidth: 260, overflow: 'hidden',
                        textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                        title={i.name}>
                        {i.name || (
                          <span style={{ color: C.warn }}>商品マスタにありません</span>
                        )}
                      </td>
                      <td style={num}>{i.units}</td>
                      <td style={{ ...num, color: i.vine_units ? C.warn : '#cbd5e1' }}>
                        {i.vine_units || '—'}
                      </td>
                      <td style={{ ...num, fontWeight: 600 }}>{yen(i.revenue)}</td>
                      <td style={{ ...num, color: i.promo ? C.warn : '#cbd5e1' }}>
                        {i.promo ? yen(i.promo) : '—'}
                      </td>
                      <td style={num}>{yen(i.cost)}</td>
                      <td style={{ ...num, color: C.bad }}>{i.cost_rate}%</td>
                      <td style={num}>{yen(i.amazon_fee)}</td>
                      <td style={num}>{yen(i.fba_fee)}</td>
                      <td style={{ ...num, fontWeight: 700,
                        color: i.profit >= 0 ? C.good : C.bad }}>
                        {yen(i.profit)}
                      </td>
                      <td style={{ ...num, fontWeight: 600,
                        color: i.profit_rate >= 20 ? C.good
                          : i.profit_rate >= 10 ? C.warn : C.bad }}>
                        {i.profit_rate}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div style={{ fontSize: 11, color: C.sub, marginTop: 10, lineHeight: 1.9 }}>
            日ごとに溜めている実績（販売数・売上・値引き）から組み立てています。
            原価は商品マスタの「仕入原価（円）」×販売数、Amazon手数料は売上×手数料率、
            FBA手数料はマスタの値×販売数です。<br />
            <b>広告費と返品・返金は入っていません。</b>
            そのぶん、実際の利益はここに出ている額より少なくなります。
          </div>
        </>
      )}
    </div>
  )
}

function Card({ label, value, color }) {
  return (
    <div className="card" style={{ margin: 0, padding: '12px 14px' }}>
      <div style={{ fontSize: 11, color: C.sub }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700, color: color || C.text }}>
        {value}
      </div>
    </div>
  )
}
