import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '../api/client'

const fmtDate = (v) => {
  if (!v) return ''
  try { return new Date(v).toLocaleDateString('ja-JP') } catch { return v }
}

export default function WelfareWorkPublicPage() {
  const [search, setSearch] = useState('')

  const { data: rows = [], isLoading } = useQuery({
    queryKey: ['welfare-work-public', search],
    queryFn: () => api.get('/welfare/work-instructions', {
      params: search ? { q: search } : {},
    }).then(r => r.data),
    refetchInterval: 60000,
  })

  const visibleRows = useMemo(
    () => rows.filter(r => (r.remaining_qty ?? 0) > 0),
    [rows]
  )

  const totalQty = visibleRows.reduce((sum, r) => sum + (r.qty || 0), 0)
  const totalRemaining = visibleRows.reduce((sum, r) => sum + (r.remaining_qty || 0), 0)

  return (
    <div style={{ minHeight: '100vh', background: '#f5f6fa', padding: '28px 36px' }}>
      <div style={{ maxWidth: 1480, margin: '0 auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: 16, marginBottom: 18 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 24 }}>作業指示</h1>
            <div style={{ color: '#64748b', fontSize: 13, marginTop: 6 }}>就労支援さん用</div>
          </div>
          <button className="btn btn-secondary" onClick={() => window.print()}>印刷</button>
        </div>

        <div className="top-actions">
          <input
            style={{ maxWidth: 360 }}
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="SKU・商品名・仕様・注文番号で検索"
          />
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12, marginBottom: 16 }}>
          <div className="card" style={{ margin: 0 }}>
            <div style={{ fontSize: 12, color: '#64748b' }}>作業行</div>
            <div style={{ fontSize: 24, fontWeight: 700 }}>{visibleRows.length}</div>
          </div>
          <div className="card" style={{ margin: 0 }}>
            <div style={{ fontSize: 12, color: '#64748b' }}>数量合計</div>
            <div style={{ fontSize: 24, fontWeight: 700 }}>{totalQty}</div>
          </div>
          <div className="card" style={{ margin: 0 }}>
            <div style={{ fontSize: 12, color: '#64748b' }}>残合計</div>
            <div style={{ fontSize: 24, fontWeight: 700 }}>{totalRemaining}</div>
          </div>
        </div>

        <div className="card">
          {isLoading ? (
            <div className="loading">読み込み中...</div>
          ) : visibleRows.length === 0 ? (
            <div className="empty-state">
              <p>作業指示はありません。</p>
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table>
                <thead>
                  <tr>
                    <th>日付</th>
                    <th>注文</th>
                    <th>商品名</th>
                    <th>仕様</th>
                    <th>URL</th>
                    <th>単品数</th>
                    <th>換算</th>
                    <th>数量</th>
                    <th>指示</th>
                    <th>残</th>
                    <th>備考</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleRows.map(row => (
                    <tr key={row.id}>
                      <td style={{ whiteSpace: 'nowrap' }}>{fmtDate(row.order_date)}</td>
                      <td>{row.source_order_no || '-'}</td>
                      <td style={{ minWidth: 240, fontWeight: 600 }}>{row.name_jp || '未照合'}</td>
                      <td style={{ minWidth: 180 }}>{row.supplier_spec || '-'}</td>
                      <td>{row.buy_url ? <a href={row.buy_url} target="_blank" rel="noreferrer">URL</a> : '-'}</td>
                      <td>{row.units}</td>
                      <td>{row.unit_per_set}個で1</td>
                      <td style={{ fontWeight: 700 }}>{row.qty}</td>
                      <td style={{ minWidth: 180 }}>{row.instruction || '-'}</td>
                      <td style={{ fontWeight: 700 }}>{row.remaining_qty}</td>
                      <td style={{ minWidth: 180 }}>{row.note || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
