import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '../api/client'

const fmtDate = (value) => {
  if (!value) return '-'
  return new Date(value).toLocaleString('ja-JP', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

const sourceStyle = (source) => {
  if (source === 'manufacturer_receive') return { background: '#ecfdf5', color: '#047857', border: '#a7f3d0' }
  return { background: '#eff6ff', color: '#1d4ed8', border: '#bfdbfe' }
}

export default function InventoryReflectionLogsPage() {
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [sourceFilter, setSourceFilter] = useState('')

  const { data, dataUpdatedAt, isLoading } = useQuery({
    queryKey: ['inventory-reflection-logs'],
    queryFn: () => api.get('/rakuten/inventory-reflection-logs?limit=300').then(r => r.data),
    refetchInterval: autoRefresh ? 30000 : false,
  })

  const logs = data?.logs || []
  const filtered = sourceFilter ? logs.filter(l => l.source === sourceFilter) : logs

  const groups = useMemo(() => {
    const map = new Map()
    for (const log of filtered) {
      const key = log.event_id || `log-${log.id}`
      if (!map.has(key)) {
        map.set(key, {
          event_id: key,
          created_at: log.created_at,
          source: log.source,
          source_label: log.source_label,
          source_ref: log.source_ref,
          source_id: log.source_id,
          rms_push_items: log.rms_push_items || 0,
          note: log.note,
          rows: [],
        })
      }
      const g = map.get(key)
      g.rows.push(log)
      g.rms_push_items = Math.max(g.rms_push_items || 0, log.rms_push_items || 0)
    }
    return [...map.values()]
      .sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0))
      .map(g => ({
        ...g,
        total_qty: g.rows.reduce((sum, r) => sum + Number(r.received_qty || 0), 0),
      }))
  }, [filtered])

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 16, flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0 }}>在庫反映履歴</h2>
        <select value={sourceFilter} onChange={e => setSourceFilter(e.target.value)} style={{ width: 160 }}>
          <option value="">すべて</option>
          <option value="shipment_order">配送依頼</option>
          <option value="manufacturer_receive">メーカー入荷</option>
        </select>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
          <input type="checkbox" checked={autoRefresh} onChange={e => setAutoRefresh(e.target.checked)} />
          30秒自動更新
        </label>
        {dataUpdatedAt && (
          <span style={{ fontSize: 12, color: '#666' }}>
            最終更新: {new Date(dataUpdatedAt).toLocaleTimeString('ja-JP')}
          </span>
        )}
      </div>

      {isLoading ? (
        <div className="loading">読み込み中...</div>
      ) : groups.length === 0 ? (
        <div className="card" style={{ padding: 32, textAlign: 'center', color: '#666' }}>
          在庫反映履歴はまだありません。
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {groups.map(group => {
            const badge = sourceStyle(group.source)
            return (
              <div key={group.event_id} className="card" style={{ padding: 0, overflow: 'hidden' }}>
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 12,
                  padding: '12px 16px',
                  background: '#f8fafc',
                  borderBottom: '1px solid #e5e7eb',
                  flexWrap: 'wrap',
                }}>
                  <span style={{ fontSize: 12, color: '#64748b', minWidth: 92 }}>{fmtDate(group.created_at)}</span>
                  <span style={{
                    fontSize: 12,
                    fontWeight: 700,
                    border: `1px solid ${badge.border}`,
                    background: badge.background,
                    color: badge.color,
                    borderRadius: 999,
                    padding: '3px 10px',
                  }}>
                    {group.source_label || group.source}
                  </span>
                  <span style={{ fontSize: 13, fontWeight: 700, color: '#0f172a' }}>{group.source_ref || '-'}</span>
                  <span style={{ fontSize: 12, color: '#475569' }}>
                    {group.rows.length}SKU / 入荷合計 {group.total_qty.toLocaleString()}個
                  </span>
                  <span style={{ fontSize: 12, color: '#475569' }}>RMS反映 {group.rms_push_items}件</span>
                  {group.note && <span style={{ fontSize: 12, color: '#64748b' }}>{group.note}</span>}
                </div>

                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                    <thead>
                      <tr style={{ background: '#fff', borderBottom: '1px solid #e5e7eb' }}>
                        {['SKU', '商品名', '仕入先', '入荷数', '実在庫', '発注済1', '発注済2'].map(h => (
                          <th key={h} style={{ padding: '9px 10px', textAlign: h === '商品名' ? 'left' : 'center', whiteSpace: 'nowrap', color: '#334155' }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {group.rows.map(row => (
                        <tr key={row.id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                          <td style={{ padding: '8px 10px', fontFamily: 'monospace', whiteSpace: 'nowrap' }}>{row.sku}</td>
                          <td style={{ padding: '8px 10px', minWidth: 220 }}>{row.name || '-'}</td>
                          <td style={{ padding: '8px 10px', textAlign: 'center', color: '#64748b' }}>{row.supplier || '-'}</td>
                          <td style={{ padding: '8px 10px', textAlign: 'right', fontWeight: 700, color: '#16a34a' }}>
                            +{Number(row.received_qty || 0).toLocaleString()}
                          </td>
                          <td style={{ padding: '8px 10px', textAlign: 'center' }}>{row.stock_before} → <b>{row.stock_after}</b></td>
                          <td style={{ padding: '8px 10px', textAlign: 'center' }}>{row.inbound_before} → <b>{row.inbound_after}</b></td>
                          <td style={{ padding: '8px 10px', textAlign: 'center' }}>{row.standard_stock_before} → <b>{row.standard_stock_after}</b></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
