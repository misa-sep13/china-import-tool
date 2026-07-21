import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '../api/client'

export default function RakutenDailySalesPage() {
  const [days, setDays] = useState(7)

  const q = useQuery({
    queryKey: ['daily-sales', days],
    queryFn: () => api.get('/rakuten/daily-sales', { params: { days } }).then(r => r.data),
  })
  const data = q.data?.data || []

  const dates = useMemo(() => {
    const set = new Set()
    for (const item of data) {
      for (const d of Object.keys(item.daily || {})) set.add(d)
    }
    return [...set].sort().reverse()
  }, [data])

  const maxQty = useMemo(() => {
    let m = 0
    for (const item of data) {
      for (const v of Object.values(item.daily || {})) {
        if (v > m) m = v
      }
    }
    return m
  }, [data])

  const cellBg = (qty) => {
    if (!qty || qty === 0) return undefined
    const intensity = Math.min(qty / Math.max(maxQty, 1), 1)
    const r = Math.round(59 + (220 - 59) * (1 - intensity))
    const g = Math.round(130 + (240 - 130) * (1 - intensity))
    const b = Math.round(246 + (255 - 246) * (1 - intensity))
    return `rgb(${r},${g},${b})`
  }

  const fmtDate = (d) => {
    const parts = d.split('-')
    return `${parseInt(parts[1])}/${parseInt(parts[2])}`
  }

  const dayOfWeek = (d) => {
    const dt = new Date(d + 'T00:00:00')
    return ['日','月','火','水','木','金','土'][dt.getDay()]
  }

  const isWeekend = (d) => {
    const dt = new Date(d + 'T00:00:00')
    const dow = dt.getDay()
    return dow === 0 || dow === 6
  }

  return (
    <div>
      <h1 style={{ marginBottom: 16 }}>📊 日別販売数</h1>

      <div className="card" style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 12 }}>
        <label style={{ fontSize: 13, fontWeight: 600 }}>期間</label>
        <select value={days} onChange={e => setDays(Number(e.target.value))} style={{ width: 130 }}>
          <option value={7}>7日間</option>
          <option value={14}>14日間</option>
          <option value={30}>30日間</option>
          <option value={60}>60日間</option>
        </select>
        {q.isLoading && <span style={{ fontSize: 12, color: '#999' }}>読み込み中...</span>}
        {q.error && <span className="error-msg">{q.error.response?.data?.detail || q.error.message}</span>}
        {!q.isLoading && data.length > 0 && (
          <span style={{ fontSize: 12, color: '#64748b' }}>{data.length}商品</span>
        )}
      </div>

      {data.length > 0 && (
        <div className="card" style={{ padding: 0 }}>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ borderCollapse: 'collapse', fontSize: 12, whiteSpace: 'nowrap' }}>
              <thead>
                <tr>
                  <th style={{ padding: '8px 10px', textAlign: 'left', position: 'sticky', left: 0, background: '#f8fafc', zIndex: 2, minWidth: 160, borderRight: '2px solid #e2e8f0' }}>
                    商品
                  </th>
                  <th style={{ padding: '8px 6px', textAlign: 'center', fontWeight: 700, minWidth: 44, background: '#f0f9ff', borderRight: '2px solid #e2e8f0' }}>
                    合計
                  </th>
                  {dates.map(d => (
                    <th key={d} style={{
                      padding: '4px 6px',
                      textAlign: 'center',
                      fontWeight: isWeekend(d) ? 700 : 400,
                      color: isWeekend(d) ? '#dc2626' : '#334155',
                      minWidth: 38,
                      background: '#f8fafc',
                    }}>
                      <div>{fmtDate(d)}</div>
                      <div style={{ fontSize: 10 }}>({dayOfWeek(d)})</div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.map(item => (
                  <tr key={item.sku} style={{ borderTop: '1px solid #e2e8f0' }}>
                    <td style={{
                      padding: '6px 10px',
                      position: 'sticky',
                      left: 0,
                      background: '#fff',
                      zIndex: 1,
                      borderRight: '2px solid #e2e8f0',
                      maxWidth: 200,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                    }}>
                      <div style={{ fontWeight: 600, fontSize: 12 }}>{item.name || item.sku}</div>
                      <div style={{ fontSize: 10, color: '#94a3b8' }}>{item.sku}</div>
                    </td>
                    <td style={{
                      padding: '6px',
                      textAlign: 'center',
                      fontWeight: 700,
                      fontSize: 13,
                      background: '#f0f9ff',
                      borderRight: '2px solid #e2e8f0',
                    }}>
                      {item.total}
                    </td>
                    {dates.map(d => {
                      const qty = (item.daily || {})[d] || 0
                      return (
                        <td key={d} style={{
                          padding: '6px',
                          textAlign: 'center',
                          background: cellBg(qty),
                          fontWeight: qty > 0 ? 600 : 300,
                          color: qty > 0 ? '#1e293b' : '#cbd5e1',
                        }}>
                          {qty}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {!q.isLoading && data.length === 0 && (
        <div className="card" style={{ textAlign: 'center', color: '#999', padding: 32 }}>
          データがありません。GitHub Actionsの日次同期を実行してください。
        </div>
      )}
    </div>
  )
}
