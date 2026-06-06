import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'

const POLL_INTERVAL = 3000 // 3秒ごとにポーリング

export default function OrderPage() {
  const qc = useQueryClient()
  const [tab, setTab] = useState('order')
  const [selected, setSelected] = useState(null)
  const [exporting, setExporting] = useState(false)
  const [error, setError] = useState('')
  const [qtyOverrides, setQtyOverrides] = useState({})

  // バックグラウンドジョブ管理
  const [jobId, setJobId] = useState(null)
  const [jobStatus, setJobStatus] = useState('idle') // idle | running | done | error
  const [jobElapsed, setJobElapsed] = useState(0)
  const [rawItems, setRawItems] = useState([])
  const pollRef = useRef(null)

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  const startFetch = async (force = false) => {
    setJobStatus('running')
    setError('')
    setRawItems([])
    setSelected(null)
    setQtyOverrides({})
    try {
      const res = await api.post(`/orders/preview/start?force=${force}`)
      const id = res.data.job_id
      setJobId(id)
      pollRef.current = setInterval(async () => {
        try {
          const status = await api.get(`/orders/preview/status/${id}`)
          setJobElapsed(status.data.elapsed)
          if (status.data.status === 'done') {
            stopPolling()
            setRawItems(status.data.result || [])
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

  // マウント時に自動取得開始
  useEffect(() => {
    startFetch()
    return () => stopPolling()
  }, [])

  useEffect(() => {
    if (rawItems.length > 0 && selected === null) {
      setSelected(new Set(rawItems.map((_, i) => i)))
    }
  }, [rawItems])

  const items = rawItems.map((item, i) => ({
    ...item,
    qty: qtyOverrides[item.product_id] ?? item.qty,
    _idx: i,
  }))

  const { data: history = [] } = useQuery({
    queryKey: ['orderHistory'],
    queryFn: () => api.get('/orders/history').then(r => r.data),
    enabled: tab === 'history',
  })

  const deleteHistory = useMutation({
    mutationFn: (id) => api.delete(`/orders/history/${id}`),
    onSuccess: () => qc.invalidateQueries(['orderHistory']),
  })

  const updateQty = (productId, val) => {
    setQtyOverrides(prev => ({ ...prev, [productId]: Number(val) }))
  }

  const currentSelected = selected ?? new Set(items.map((_, i) => i))

  const toggleSelect = (idx) => {
    setSelected(prev => {
      const base = prev ?? new Set(items.map((_, i) => i))
      const next = new Set(base)
      next.has(idx) ? next.delete(idx) : next.add(idx)
      return next
    })
  }

  const toggleAll = () => {
    if (currentSelected.size === items.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(items.map((_, i) => i)))
    }
  }

  const handleExport = async () => {
    const targets = items.filter((item, i) => currentSelected.has(i) && item.qty > 0)
    if (!targets.length) { setError('選択された商品がないか、発注数が0です'); return }
    setExporting(true)
    try {
      const res = await api.post('/orders/export', { items: targets }, { responseType: 'blob' })
      const url = window.URL.createObjectURL(new Blob([res.data]))
      const a = document.createElement('a')
      a.href = url
      a.download = `${new Date().toISOString().slice(0,10).replace(/-/g,'')}_order.xlsx`
      a.click()
      window.URL.revokeObjectURL(url)
      qc.invalidateQueries(['orderHistory'])
      setQtyOverrides({})
      setSelected(null)
    } catch {
      setError('Excelの出力に失敗しました')
    } finally {
      setExporting(false)
    }
  }

  const handleRefetch = () => {
    stopPolling()
    startFetch(true)  // 再計算ボタンはキャッシュを強制クリア
  }

  const daysBadge = (days) => {
    if (days < 30) return <span className="badge badge-danger">{days}日</span>
    if (days < 60) return <span className="badge badge-warn">{days}日</span>
    return <span className="badge badge-ok">{days}日</span>
  }

  const selectedItems = items.filter((item, i) => currentSelected.has(i) && item.qty > 0)
  const totalYuan = selectedItems.reduce((s, i) => s + i.qty * i.price, 0)
  const isLoading = jobStatus === 'running' || jobStatus === 'idle'

  return (
    <div>
      <h1>📦 発注管理</h1>

      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        <button
          className={`btn ${tab === 'order' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setTab('order')}
        >発注推奨リスト</button>
        <button
          className={`btn ${tab === 'history' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setTab('history')}
        >発注済みリスト</button>
      </div>

      {tab === 'order' && (
        <>
          <div className="card">
            <p style={{ marginBottom: 14, color: '#555', fontSize: 13 }}>
              Amazon SP-APIから在庫・売上データを取得し、推奨発注数を自動計算します。<br />
              チェックを入れた商品だけExcelに出力されます。出力すると発注済みリストに記録されます。
            </p>
            <div className="top-actions">
              <button className="btn btn-secondary" onClick={handleRefetch} disabled={isLoading}>
                {isLoading ? '取得中...' : '🔄 再計算'}
              </button>
              {items.length > 0 && (
                <button className="btn btn-success" onClick={handleExport} disabled={exporting}>
                  {exporting ? '生成中...' : `📥 Excelダウンロード（${selectedItems.length}件）`}
                </button>
              )}
            </div>
            {error && <p className="error-msg">{error}</p>}
          </div>

          {isLoading && (
            <div className="card" style={{ textAlign: 'center', color: '#555', padding: 40 }}>
              <div style={{ fontSize: 32, marginBottom: 12 }}>⏳</div>
              <p style={{ fontWeight: 600, marginBottom: 8 }}>SP-APIからデータを取得中...</p>
              <p style={{ fontSize: 13, color: '#888' }}>
                Amazon SP-APIから全商品の在庫・売上データを取得しています。<br />
                商品数によっては2〜3分かかる場合があります。
              </p>
              {jobElapsed > 0 && (
                <p style={{ fontSize: 13, color: '#aaa', marginTop: 8 }}>経過時間: {jobElapsed}秒</p>
              )}
            </div>
          )}

          {jobStatus === 'error' && !isLoading && (
            <div className="card" style={{ textAlign: 'center', color: '#c00', padding: 40 }}>
              <div style={{ fontSize: 32, marginBottom: 8 }}>⚠️</div>
              <p>データ取得に失敗しました。再計算ボタンで再試行してください。</p>
            </div>
          )}

          {!isLoading && jobStatus === 'done' && items.length > 0 && (
            <div className="card">
              <h2>発注推奨リスト（{items.length}件）</h2>
              <div style={{ overflowX: 'auto' }}>
                <table>
                  <thead>
                    <tr>
                      <th style={{ width: 36, cursor: 'pointer' }} onClick={toggleAll}>
                        <input type="checkbox"
                          checked={currentSelected.size === items.length}
                          onChange={toggleAll}
                          onClick={e => e.stopPropagation()}
                        />
                      </th>
                      <th>SKU</th>
                      <th>商品名</th>
                      <th>色/サイズ</th>
                      <th>残日数</th>
                      <th>在庫</th>
                      <th>発注済</th>
                      <th>日販</th>
                      <th>発注数</th>
                      <th>単価(元)</th>
                      <th>小計(元)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((item) => (
                      <tr key={item.product_id} style={{ opacity: currentSelected.has(item._idx) ? 1 : 0.4 }}>
                        <td
                          style={{ textAlign: 'center', cursor: 'pointer' }}
                          onClick={() => toggleSelect(item._idx)}
                        >
                          <input type="checkbox"
                            checked={currentSelected.has(item._idx)}
                            onChange={() => toggleSelect(item._idx)}
                            onClick={e => e.stopPropagation()}
                          />
                        </td>
                        <td style={{ fontFamily: 'monospace', fontSize: 12 }}>{item.sku}</td>
                        <td style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {item.name}
                        </td>
                        <td style={{ fontSize: 12, color: '#666' }}>{[item.color, item.size].filter(Boolean).join(' / ')}</td>
                        <td>{daysBadge(item.days_left)}</td>
                        <td style={{ textAlign: 'right' }}>{item.stock}</td>
                        <td style={{ textAlign: 'right', color: item.ordered > 0 ? '#e94560' : '#bbb', fontWeight: item.ordered > 0 ? 600 : 400 }}>
                          {item.ordered > 0 ? item.ordered : '-'}
                        </td>
                        <td style={{ textAlign: 'right' }}>{item.daily}</td>
                        <td>
                          <input
                            type="number"
                            className="qty-input"
                            min={0}
                            value={item.qty}
                            onChange={e => updateQty(item.product_id, e.target.value)}
                          />
                        </td>
                        <td style={{ textAlign: 'right' }}>{item.price}</td>
                        <td style={{ textAlign: 'right', fontWeight: 600 }}>
                          {currentSelected.has(item._idx) ? (item.qty * item.price).toFixed(0) : '-'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr>
                      <td colSpan={9} style={{ textAlign: 'right', fontWeight: 700, paddingTop: 12 }}>合計（選択分）</td>
                      <td style={{ textAlign: 'right', fontWeight: 700 }}>
                        {totalYuan.toFixed(0)} 元
                      </td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            </div>
          )}

          {!isLoading && jobStatus === 'done' && items.length === 0 && (
            <div className="card empty-state">
              <div style={{ fontSize: 40 }}>✅</div>
              <p>現在、発注が必要な商品はありません。</p>
            </div>
          )}
        </>
      )}

      {tab === 'history' && (
        <div className="card">
          <h2>発注済みリスト（{history.length}件）</h2>
          {history.length === 0 ? (
            <div className="empty-state">
              <div style={{ fontSize: 40 }}>📋</div>
              <p>発注履歴がありません。</p>
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table>
                <thead>
                  <tr>
                    <th>発注日時</th>
                    <th>SKU</th>
                    <th>商品名</th>
                    <th>色/サイズ</th>
                    <th>発注数</th>
                    <th>単価(元)</th>
                    <th>小計(元)</th>
                    <th>仕入URL</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {history.map(row => (
                    <tr key={row.id}>
                      <td style={{ fontSize: 12, whiteSpace: 'nowrap', color: '#666' }}>
                        {new Date(row.ordered_at).toLocaleString('ja-JP', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
                      </td>
                      <td style={{ fontFamily: 'monospace', fontSize: 12 }}>{row.sku}</td>
                      <td style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{row.name}</td>
                      <td style={{ fontSize: 12, color: '#666' }}>{[row.color, row.size].filter(Boolean).join(' / ')}</td>
                      <td style={{ textAlign: 'right', fontWeight: 600 }}>{row.qty}</td>
                      <td style={{ textAlign: 'right' }}>{row.price}</td>
                      <td style={{ textAlign: 'right', fontWeight: 600 }}>{(row.qty * row.price).toFixed(0)}</td>
                      <td>
                        {row.buy_url && (
                          <a href={row.buy_url} target="_blank" rel="noreferrer" style={{ color: '#e94560', fontSize: 12 }}>リンク</a>
                        )}
                      </td>
                      <td>
                        <button
                          className="btn btn-sm"
                          style={{ background: '#fee2e2', color: '#991b1b', whiteSpace: 'nowrap' }}
                          onClick={() => {
                            if (confirm(`${row.sku} の発注済みレコードを削除しますか？\n（FBA納品プラン作成済みの場合に押してください）`))
                              deleteHistory.mutate(row.id)
                          }}
                        >納品済</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <td colSpan={6} style={{ textAlign: 'right', fontWeight: 700, paddingTop: 12 }}>合計</td>
                    <td style={{ textAlign: 'right', fontWeight: 700 }}>
                      {history.reduce((s, r) => s + r.qty * r.price, 0).toFixed(0)} 元
                    </td>
                    <td></td>
                    <td></td>
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
