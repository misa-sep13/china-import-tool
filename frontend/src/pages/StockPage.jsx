import { useState, useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import api from '../api/client'

const POLL_INTERVAL = 3000

export default function StockPage() {
  const qc = useQueryClient()
  const [jobId, setJobId] = useState(null)
  const [jobStatus, setJobStatus] = useState('idle')
  const [jobElapsed, setJobElapsed] = useState(0)
  const [rawItems, setRawItems] = useState([])
  const [selected, setSelected] = useState(null)
  const [qtyOverrides, setQtyOverrides] = useState({})
  const [exporting, setExporting] = useState(false)
  const [error, setError] = useState('')
  const [sortKey, setSortKey] = useState('days_left')
  const [sortAsc, setSortAsc] = useState(true)
  const [search, setSearch] = useState('')
  const [ordering, setOrdering] = useState(null)
  const [justOrdered, setJustOrdered] = useState(new Set())
  const [hiding, setHiding] = useState(null)
  const pollRef = useRef(null)

  const stopPolling = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }

  const startFetch = async (force = false) => {
    if (force) sessionStorage.removeItem('stock_items')
    setJobStatus('running')
    setError('')
    setRawItems([])
    setSelected(null)
    setQtyOverrides({})
    try {
      const res = await api.post(`/orders/stock/start?force=${force}`)
      const id = res.data.job_id
      setJobId(id)
      pollRef.current = setInterval(async () => {
        try {
          const status = await api.get(`/orders/preview/status/${id}`)
          setJobElapsed(status.data.elapsed)
          if (status.data.status === 'done') {
            stopPolling()
            const items = status.data.result || []
            setRawItems(items)
            sessionStorage.setItem('stock_items', JSON.stringify(items))
            setJobStatus('done')
          } else if (status.data.status === 'error') {
            stopPolling()
            setError(status.data.error || 'SP-APIデータ取得に失敗しました')
            setJobStatus('error')
          }
        } catch {
          stopPolling()
          setError('ステータス取得に失敗しました')
          setJobStatus('error')
        }
      }, POLL_INTERVAL)
    } catch {
      setJobStatus('error')
      setError('データ取得の開始に失敗しました')
    }
  }

  useEffect(() => {
    const cached = sessionStorage.getItem('stock_items')
    if (cached) {
      try {
        setRawItems(JSON.parse(cached))
        setJobStatus('done')
        return () => {}
      } catch {}
    }
    startFetch()
    return () => stopPolling()
  }, [])

  const items = rawItems.map((item, i) => ({
    ...item,
    qty: qtyOverrides[item.product_id] ?? item.qty,
    _idx: i,
  }))

  const q = search.trim().toLowerCase()
  const filtered = q
    ? items.filter(item =>
        (item.sku || '').toLowerCase().includes(q) ||
        (item.name || '').toLowerCase().includes(q) ||
        (item.color || '').toLowerCase().includes(q) ||
        (item.size || '').toLowerCase().includes(q)
      )
    : items

  const sorted = [...filtered].sort((a, b) => {
    let va = a[sortKey], vb = b[sortKey]
    if (typeof va === 'string') va = va.toLowerCase()
    if (typeof vb === 'string') vb = vb.toLowerCase()
    if (va < vb) return sortAsc ? -1 : 1
    if (va > vb) return sortAsc ? 1 : -1
    return 0
  })

  const currentSelected = selected ?? new Set()

  const toggleSelect = (idx) => {
    setSelected(prev => {
      const base = prev ?? new Set()
      const next = new Set(base)
      next.has(idx) ? next.delete(idx) : next.add(idx)
      return next
    })
  }

  const toggleAll = () => {
    const allIdx = sorted.map(item => item._idx)
    if (currentSelected.size === sorted.length && sorted.every(item => currentSelected.has(item._idx))) {
      setSelected(new Set())
    } else {
      setSelected(new Set(allIdx))
    }
  }

  const updateQty = (productId, val) => {
    setQtyOverrides(prev => ({ ...prev, [productId]: Number(val) }))
  }

  const handleSort = (key) => {
    if (sortKey === key) { setSortAsc(a => !a) } else { setSortKey(key); setSortAsc(true) }
  }

  const sortIcon = (key) => sortKey === key ? (sortAsc ? ' ▲' : ' ▼') : ''

  const hideProduct = async (item) => {
    if (!confirm(`${item.sku} を一覧から非表示にしますか？\n（商品マスタからも外れます。Amazonの出品には影響しません。後で復元可能）`)) return
    setHiding(item.product_id)
    setError('')
    try {
      await api.delete(`/products/${item.product_id}`)
      setRawItems(prev => {
        const next = prev.filter(it => it.product_id !== item.product_id)
        sessionStorage.setItem('stock_items', JSON.stringify(next))
        return next
      })
    } catch {
      setError('非表示に失敗しました')
    } finally {
      setHiding(null)
    }
  }

  const recordOrder = async (item) => {
    if (!item.qty || item.qty <= 0) { setError('発注数が0です'); return }
    setOrdering(item.product_id)
    setError('')
    try {
      await api.post('/orders/order', { items: [{
        sku: item.sku, name: item.name, color: item.color, size: item.size,
        qty: item.qty, price: item.price, buy_url: item.buy_url,
        photo_url: item.photo_url, asin: item.asin, fnsku: item.fnsku, note: item.note,
      }] })
      setJustOrdered(prev => new Set(prev).add(item.product_id))
      qc.invalidateQueries(['orderHistory'])
    } catch {
      setError('発注の記録に失敗しました')
    } finally {
      setOrdering(null)
    }
  }

  const handleExport = async () => {
    const targets = sorted.filter(item => currentSelected.has(item._idx) && item.qty > 0)
    if (!targets.length) { setError('選択された商品がないか、発注数が0です'); return }
    setExporting(true)
    try {
      const res = await api.post('/orders/export', { items: targets }, { responseType: 'blob' })
      const url = window.URL.createObjectURL(new Blob([res.data]))
      const a = document.createElement('a')
      a.href = url
      a.download = `${new Date().toISOString().slice(0, 10).replace(/-/g, '')}_order.xlsx`
      a.click()
      window.URL.revokeObjectURL(url)
      qc.invalidateQueries(['orderHistory'])
      setQtyOverrides({})
      setSelected(new Set())
    } catch {
      setError('Excelの出力に失敗しました')
    } finally {
      setExporting(false)
    }
  }

  const selectedItems = sorted.filter(item => currentSelected.has(item._idx) && item.qty > 0)
  const checkedCount = sorted.filter(item => currentSelected.has(item._idx)).length
  const isLoading = jobStatus === 'running' || jobStatus === 'idle'

  const daysBadge = (days) => {
    if (days >= 9999) return <span style={{ color: '#999', fontSize: 12 }}>-</span>
    if (days < 30) return <span className="badge badge-danger">{days}日</span>
    if (days < 60) return <span className="badge badge-warn">{days}日</span>
    return <span className="badge badge-ok">{days}日</span>
  }

  const recBadge = (pieces) => {
    if (pieces > 0) return <span style={{ color: '#e94560', fontWeight: 700 }}>+{pieces}</span>
    if (pieces < 0) return <span style={{ color: '#16a34a', fontWeight: 600 }}>{pieces}</span>
    return <span style={{ color: '#999' }}>0</span>
  }

  const thStyle = (key) => ({
    cursor: 'pointer',
    userSelect: 'none',
    whiteSpace: 'nowrap',
    background: sortKey === key ? '#f0f4ff' : undefined,
  })

  return (
    <div>
      <h1>📊 全在庫一覧</h1>

      <div className="card">
        <div className="top-actions">
          <button className="btn btn-secondary" onClick={() => { stopPolling(); startFetch(true) }} disabled={isLoading}>
            {isLoading ? '取得中...' : '🔄 再計算'}
          </button>
          <button className="btn btn-success" onClick={handleExport} disabled={exporting || checkedCount === 0}>
            {exporting ? '生成中...' : `📥 Excelダウンロード（${checkedCount}件）`}
          </button>
          <input
            type="text" placeholder="SKU・商品名・色/サイズで絞り込み"
            value={search} onChange={e => setSearch(e.target.value)}
            style={{ width: 260, flex: '0 0 260px' }}
          />
        </div>
        {error && <p className="error-msg">{error}</p>}
      </div>

      {isLoading && (
        <div className="card" style={{ textAlign: 'center', color: '#555', padding: 40 }}>
          <div style={{ fontSize: 32, marginBottom: 12 }}>⏳</div>
          <p style={{ fontWeight: 600, marginBottom: 8 }}>SP-APIからデータを取得中...</p>
          <p style={{ fontSize: 13, color: '#888' }}>在庫・売上データを取得しています。しばらくお待ちください。</p>
          {jobElapsed > 0 && <p style={{ fontSize: 13, color: '#aaa', marginTop: 8 }}>経過時間: {jobElapsed}秒</p>}
        </div>
      )}

      {jobStatus === 'error' && !isLoading && (
        <div className="card" style={{ textAlign: 'center', color: '#c00', padding: 40 }}>
          <div style={{ fontSize: 32, marginBottom: 8 }}>⚠️</div>
          <p>データ取得に失敗しました。再計算ボタンで再試行してください。</p>
        </div>
      )}

      {!isLoading && jobStatus === 'done' && (
        <div className="card">
          <h2>全在庫（{sorted.length}件）</h2>
          <div className="sticky-table-wrap">
            <table className="sticky-table">
              <thead>
                <tr>
                  <th style={{ width: 36, cursor: 'pointer' }} onClick={toggleAll}>
                    <input
                      type="checkbox"
                      checked={sorted.length > 0 && sorted.every(item => currentSelected.has(item._idx))}
                      onChange={toggleAll}
                      onClick={e => e.stopPropagation()}
                    />
                  </th>
                  <th style={thStyle('sku')} onClick={() => handleSort('sku')}>SKU{sortIcon('sku')}</th>
                  <th style={thStyle('name')} onClick={() => handleSort('name')}>商品名{sortIcon('name')}</th>
                  <th style={thStyle('category')} onClick={() => handleSort('category')}>区分{sortIcon('category')}</th>
                  <th style={thStyle('color')} onClick={() => handleSort('color')}>色/サイズ{sortIcon('color')}</th>
                  <th style={{ ...thStyle('available'), textAlign: 'right' }} onClick={() => handleSort('available')}>在庫{sortIcon('available')}</th>
                  <th style={{ ...thStyle('inbound'), textAlign: 'right' }} onClick={() => handleSort('inbound')}>納品中{sortIcon('inbound')}</th>
                  <th style={{ ...thStyle('ordered'), textAlign: 'right' }} onClick={() => handleSort('ordered')}>発注済{sortIcon('ordered')}</th>
                  <th style={{ ...thStyle('daily'), textAlign: 'right' }} onClick={() => handleSort('daily')}>日販{sortIcon('daily')}</th>
                  <th style={{ ...thStyle('days_left'), textAlign: 'right' }} onClick={() => handleSort('days_left')}>残日数{sortIcon('days_left')}</th>
                  <th style={{ ...thStyle('recommended_pieces'), textAlign: 'right' }} onClick={() => handleSort('recommended_pieces')}>推奨発注{sortIcon('recommended_pieces')}</th>
                  <th style={{ textAlign: 'right' }}>発注数</th>
                  <th style={{ ...thStyle('price'), textAlign: 'right' }} onClick={() => handleSort('price')}>単価(元){sortIcon('price')}</th>
                  <th style={{ textAlign: 'center' }}>発注</th>
                  <th style={{ textAlign: 'center' }}>非表示</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map(item => (
                  <tr
                    key={item.product_id}
                    style={{ background: item.recommended_pieces < 0 ? '#f0fdf4' : undefined }}
                  >
                    <td style={{ textAlign: 'center', cursor: 'pointer' }} onClick={() => toggleSelect(item._idx)}>
                      <input
                        type="checkbox"
                        checked={currentSelected.has(item._idx)}
                        onChange={() => toggleSelect(item._idx)}
                        onClick={e => e.stopPropagation()}
                      />
                    </td>
                    <td style={{ fontFamily: 'monospace', fontSize: 12, color: '#1a1a2e' }}>{item.sku}</td>
                    <td style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: '#1a1a2e' }}>{item.name}</td>
                    <td style={{ fontSize: 11, whiteSpace: 'nowrap' }}>
                      <span style={{
                        padding: '2px 6px', borderRadius: 4, fontWeight: 600,
                        background: item.category === 'ファッション' ? '#fce7f3' : item.category === '大型' ? '#fef9c3' : '#e0f2fe',
                        color: item.category === 'ファッション' ? '#9d174d' : item.category === '大型' ? '#854d0e' : '#0369a1',
                      }}>
                        {item.category || '標準'}
                      </span>
                    </td>
                    <td style={{ fontSize: 12, color: '#555' }}>{[item.color, item.size].filter(Boolean).join(' / ')}</td>
                    <td style={{ textAlign: 'right', fontWeight: 600 }}>{item.available}</td>
                    <td style={{ textAlign: 'right', color: item.inbound > 0 ? '#2563eb' : '#aaa' }}>{item.inbound || '-'}</td>
                    <td style={{ textAlign: 'right', color: item.ordered > 0 ? '#e94560' : '#aaa' }}>{item.ordered > 0 ? item.ordered : '-'}</td>
                    <td style={{ textAlign: 'right', color: '#555' }}>{item.daily}</td>
                    <td style={{ textAlign: 'right' }}>{daysBadge(item.days_left)}</td>
                    <td style={{ textAlign: 'right' }}>{recBadge(item.recommended_pieces)}</td>
                    <td>
                      <input
                        type="number"
                        className="qty-input"
                        min={0}
                        value={item.qty}
                        onChange={e => updateQty(item.product_id, e.target.value)}
                        style={{ width: 60 }}
                      />
                    </td>
                    <td style={{ textAlign: 'right', color: '#555' }}>{item.price}</td>
                    <td style={{ textAlign: 'center', whiteSpace: 'nowrap' }}>
                      {justOrdered.has(item.product_id) ? (
                        <span style={{ color: '#16a34a', fontWeight: 700, fontSize: 12 }}>✓ 発注済</span>
                      ) : (
                        <button
                          className="btn btn-primary"
                          style={{ padding: '4px 12px', fontSize: 12 }}
                          disabled={ordering === item.product_id || item.qty <= 0}
                          onClick={() => recordOrder(item)}
                        >
                          {ordering === item.product_id ? '...' : '発注'}
                        </button>
                      )}
                    </td>
                    <td style={{ textAlign: 'center', whiteSpace: 'nowrap' }}>
                      <button
                        className="btn btn-sm"
                        style={{ background: '#fee2e2', color: '#991b1b', fontSize: 12 }}
                        disabled={hiding === item.product_id}
                        onClick={() => hideProduct(item)}
                      >
                        {hiding === item.product_id ? '...' : '非表示'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
