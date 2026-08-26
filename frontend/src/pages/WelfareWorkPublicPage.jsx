import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '../api/client'
import WelfarePackingOrders from '../components/WelfarePackingOrders'

const fmtDate = (v) => {
  if (!v) return ''
  try { return new Date(v).toLocaleDateString('ja-JP') } catch { return v }
}

const fmtWorkDate = (row) => {
  const sheet = String(row.source_sheet || '').trim()
  if (/^\d{2}$/.test(sheet)) return `${Number(sheet.slice(0, 1))}/${Number(sheet.slice(1))}`
  if (/^\d{3}$/.test(sheet)) return `${Number(sheet.slice(0, 1))}/${Number(sheet.slice(1))}`
  if (/^\d{4}$/.test(sheet)) return `${Number(sheet.slice(0, 2))}/${Number(sheet.slice(2))}`
  const mixed = sheet.match(/^(\d{1,2})[/-](\d{1,2})(.*)$/)
  if (mixed) return `${Number(mixed[1])}/${Number(mixed[2])}${mixed[3] || ''}`
  const dotted = sheet.match(/^(\d{1,2})・(\d{1,2})(.*)$/)
  if (dotted) return sheet
  const compact = sheet.match(/^(\d{3,4})(.+)$/)
  if (compact) {
    const d = compact[1]
    const month = d.length === 3 ? Number(d.slice(0, 1)) : Number(d.slice(0, 2))
    const day = d.length === 3 ? Number(d.slice(1)) : Number(d.slice(2))
    return `${month}/${day}${compact[2]}`
  }
  return sheet || fmtDate(row.order_date) || '-'
}

const workDateSortValue = (date) => {
  const s = String(date || '')
  const today = new Date()
  const currentYear = today.getFullYear()
  const currentMonthDay = (today.getMonth() + 1) * 100 + today.getDate()
  const withDate = s.match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})/)
  if (withDate) return Number(withDate[1]) * 10000 + Number(withDate[2]) * 100 + Number(withDate[3])
  const monthDay = s.match(/^(\d{1,2})[\/・](\d{1,2})/)
  if (monthDay) {
    const value = Number(monthDay[1]) * 100 + Number(monthDay[2])
    const year = value > currentMonthDay ? currentYear - 1 : currentYear
    return year * 10000 + value
  }
  return -1
}

const workRemainingQty = (row) => row.remaining_qty ?? 0

const instructionCellStyle = (value) => {
  const v = String(value || '')
  if (v.includes('作業保管')) return { background: '#dbeafe' }
  if (v.includes('戻し')) return { background: '#fef3c7' }
  return { background: '#fff' }
}

const imageThumb = (src) => (
  src ? <img src={src} alt="" style={{ width: 42, height: 42, objectFit: 'cover', borderRadius: 4, display: 'block' }} /> : '-'
)

export default function WelfareWorkPublicPage() {
  const [search, setSearch] = useState('')
  const [activeWorkDate, setActiveWorkDate] = useState('')
  // 荷受けの作業指示と、再梱包の作業依頼を切り替える
  const [view, setView] = useState('work')

  const { data: rows = [], isLoading } = useQuery({
    queryKey: ['welfare-work-public', search],
    queryFn: () => api.get('/welfare/work-instructions', {
      params: search ? { q: search } : {},
    }).then(r => r.data),
    refetchInterval: 60000,
  })

  const visibleRows = useMemo(
    () => rows.filter(r => workRemainingQty(r) > 0),
    [rows]
  )

  const workDateTabs = useMemo(() => {
    const groups = new Map()
    visibleRows.forEach(row => {
      const date = fmtWorkDate(row)
      if (!groups.has(date)) groups.set(date, { count: 0, maxCreatedAt: '' })
      const g = groups.get(date)
      g.count++
      const ts = row.created_at || ''
      if (ts > g.maxCreatedAt) g.maxCreatedAt = ts
    })
    return Array.from(groups, ([date, { count, maxCreatedAt }]) => ({ date, count, maxCreatedAt }))
      .sort((a, b) => {
        if (a.maxCreatedAt && b.maxCreatedAt) return b.maxCreatedAt.localeCompare(a.maxCreatedAt)
        return workDateSortValue(b.date) - workDateSortValue(a.date)
      })
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
  const totalRemaining = selectedRows.reduce((sum, r) => sum + workRemainingQty(r), 0)

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

        {/* 荷受けの指示と、再梱包の作業依頼は見る場面が違うのでタブで分ける */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 16 }} className="no-print">
          {[
            { key: 'work', label: '荷受けの作業指示' },
            { key: 'packing', label: '再梱包の作業依頼' },
          ].map(t => (
            <button
              key={t.key}
              onClick={() => setView(t.key)}
              className={view === t.key ? 'btn btn-primary' : 'btn btn-secondary'}
              style={{ minWidth: 160 }}
            >
              {t.label}
            </button>
          ))}
        </div>

        {view === 'packing' ? <WelfarePackingOrders /> : (
        <>
        <div className="top-actions">
          <input
            className="search-input-ja"
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
            <div style={{ fontSize: 12, color: '#64748b' }}>単品数合計</div>
            <div style={{ fontSize: 24, fontWeight: 700 }}>{totalQty}</div>
          </div>
          <div className="card" style={{ margin: 0 }}>
            <div style={{ fontSize: 12, color: '#64748b' }}>残合計</div>
            <div style={{ fontSize: 24, fontWeight: 700 }}>{totalRemaining}</div>
          </div>
        </div>

        <div className="card" style={{ padding: 12 }}>
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
                <table className="welfare-work-table" style={{ width: 1140, minWidth: 1140 }}>
                  <thead>
                    <tr>
                      <th style={{ width: 58 }}>写真</th>
                      <th style={{ width: 240 }}>商品名</th>
                      <th style={{ width: 110 }}>色</th>
                      <th style={{ width: 80 }}>サイズ</th>
                      <th style={{ width: 52 }}>URL</th>
                      <th style={{ width: 64 }}>単品数</th>
                      <th style={{ width: 64 }}>換算</th>
                      <th style={{ width: 74 }}>残</th>
                      <th style={{ width: 126 }}>指示</th>
                      <th style={{ width: 180 }}>備考</th>
                      <th style={{ width: 90 }}>発注時間</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selectedRows.map(row => (
                      <tr key={row.id}>
                        <td>{imageThumb(row.image_data_url)}</td>
                        <td style={{ wordBreak: 'break-word', fontWeight: 600 }}>{row.name_jp || row.source_product_name || '未照合'}</td>
                        <td style={{ color: '#e11d48' }}>{row.color || row.supplier_spec || '-'}</td>
                        <td style={{ color: '#e11d48' }}>{row.size || '-'}</td>
                        <td>{row.buy_url ? <a href={row.buy_url} target="_blank" rel="noreferrer">URL</a> : '-'}</td>
                        <td style={{ color: '#e11d48', fontWeight: 700 }}>{row.units}</td>
                        <td>{row.unit_per_set || 1}個で1</td>
                        <td style={{ fontWeight: 700 }}>{workRemainingQty(row)}</td>
                        <td style={{ ...instructionCellStyle(row.instruction), fontWeight: 600 }}>{row.instruction || '-'}</td>
                        <td>{row.note || '-'}</td>
                        <td style={{ whiteSpace: 'nowrap' }}>{row.order_date || fmtWorkDate(row)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
        </>
        )}
      </div>
    </div>
  )
}
