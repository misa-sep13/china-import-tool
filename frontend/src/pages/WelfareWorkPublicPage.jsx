import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '../api/client'

const fmtDate = (v) => {
  if (!v) return ''
  try { return new Date(v).toLocaleDateString('ja-JP') } catch { return v }
}

const fmtWorkDate = (row) => {
  const sheet = String(row.source_sheet || '').trim()
  if (/^\d{2}$/.test(sheet)) return `${Number(sheet.slice(0, 1))}/${Number(sheet.slice(1))}`
  if (/^\d{3}$/.test(sheet)) return `${Number(sheet.slice(0, 1))}/${Number(sheet.slice(1))}`
  if (/^\d{4}$/.test(sheet)) return `${Number(sheet.slice(0, 2))}/${Number(sheet.slice(2))}`
  return sheet || fmtDate(row.order_date) || '-'
}

const workDateSortValue = (date) => {
  const s = String(date || '')
  const iso = s.match(/^\d{4}\/(\d{1,2})\/(\d{1,2})/)
  if (iso) return Number(iso[1]) * 100 + Number(iso[2])
  const slash = s.match(/^(\d{1,2})\/(\d{1,2})$/)
  if (slash) return Number(slash[1]) * 100 + Number(slash[2])
  return -1
}

const workRemainingUnits = (row) => (
  row.remaining_units ?? ((row.remaining_qty || 0) * (row.unit_per_set || 1))
)

export default function WelfareWorkPublicPage() {
  const [search, setSearch] = useState('')
  const [activeWorkDate, setActiveWorkDate] = useState('')

  const { data: rows = [], isLoading } = useQuery({
    queryKey: ['welfare-work-public', search],
    queryFn: () => api.get('/welfare/work-instructions', {
      params: search ? { q: search } : {},
    }).then(r => r.data),
    refetchInterval: 60000,
  })

  const visibleRows = useMemo(
    () => rows.filter(r => workRemainingUnits(r) > 0),
    [rows]
  )

  const workDateTabs = useMemo(() => {
    const counts = new Map()
    visibleRows.forEach(row => {
      const date = fmtWorkDate(row)
      counts.set(date, (counts.get(date) || 0) + 1)
    })
    return Array.from(counts, ([date, count]) => ({ date, count }))
      .sort((a, b) => workDateSortValue(b.date) - workDateSortValue(a.date) || String(b.date).localeCompare(String(a.date), 'ja'))
  }, [visibleRows])

  const selectedRows = useMemo(
    () => activeWorkDate ? visibleRows.filter(row => fmtWorkDate(row) === activeWorkDate) : visibleRows,
    [activeWorkDate, visibleRows]
  )

  useEffect(() => {
    if (workDateTabs.length === 0) {
      if (activeWorkDate) setActiveWorkDate('')
      return
    }
    if (!activeWorkDate || !workDateTabs.some(tab => tab.date === activeWorkDate)) {
      setActiveWorkDate(workDateTabs[0].date)
    }
  }, [activeWorkDate, workDateTabs])

  const totalQty = selectedRows.reduce((sum, r) => sum + (r.units || 0), 0)
  const totalRemaining = selectedRows.reduce((sum, r) => sum + workRemainingUnits(r), 0)

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
            <div style={{ fontSize: 24, fontWeight: 700 }}>{selectedRows.length}</div>
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
            <div>
              <div style={{ display: 'flex', gap: 8, overflowX: 'auto', paddingBottom: 10, marginBottom: 12 }}>
                {workDateTabs.map(tab => (
                  <button
                    key={tab.date}
                    className={`btn ${activeWorkDate === tab.date ? 'btn-primary' : 'btn-secondary'}`}
                    onClick={() => setActiveWorkDate(tab.date)}
                    style={{ whiteSpace: 'nowrap' }}
                  >
                    {tab.date} ({tab.count})
                  </button>
                ))}
              </div>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ minWidth: 1260, tableLayout: 'fixed' }}>
                  <thead>
                    <tr>
                      <th style={{ width: 90 }}>発注時間</th>
                      <th style={{ width: 100 }}>注文</th>
                      <th style={{ width: 250 }}>商品名</th>
                      <th style={{ width: 110 }}>色</th>
                      <th style={{ width: 90 }}>サイズ</th>
                      <th style={{ width: 80 }}>商品URL</th>
                      <th style={{ width: 70 }}>単価</th>
                      <th style={{ width: 70 }}>数量</th>
                      <th style={{ width: 180 }}>指示</th>
                      <th style={{ width: 70 }}>残</th>
                      <th style={{ width: 150 }}>備考</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selectedRows.map(row => (
                      <tr key={row.id}>
                        <td style={{ whiteSpace: 'nowrap' }}>{row.order_date || fmtWorkDate(row)}</td>
                        <td>{row.source_order_no || '-'}</td>
                        <td style={{ wordBreak: 'break-word', fontWeight: 600 }}>{row.source_product_name || row.name_jp || '未照合'}</td>
                        <td style={{ color: '#e11d48' }}>{row.color || row.supplier_spec || '-'}</td>
                        <td style={{ color: '#e11d48' }}>{row.size || '-'}</td>
                        <td>{row.buy_url ? <a href={row.buy_url} target="_blank" rel="noreferrer">URL</a> : '-'}</td>
                        <td>{row.unit_price || '-'}</td>
                        <td style={{ color: '#e11d48', fontWeight: 700 }}>{row.units}</td>
                        <td style={{ minWidth: 180 }}>{row.instruction || '-'}</td>
                        <td style={{ fontWeight: 700 }}>{workRemainingUnits(row)}</td>
                        <td style={{ minWidth: 180 }}>{row.note || '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
