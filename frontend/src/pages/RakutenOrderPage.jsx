import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'

async function downloadExcel(items) {
  const res = await api.post('/rakuten/orders/excel', { items }, { responseType: 'blob' })
  const url = URL.createObjectURL(new Blob([res.data]))
  const a = document.createElement('a')
  a.href = url
  a.download = `${new Date().toISOString().slice(0,10).replace(/-/g,'')}_rakuten_order.xlsx`
  a.click()
  URL.revokeObjectURL(url)
}

export default function RakutenOrderPage() {
  const qc = useQueryClient()
  const [tab, setTab] = useState('order')
  const [orderInputs, setOrderInputs] = useState({})
  const [ordering, setOrdering] = useState(null)
  const [downloading, setDownloading] = useState(false)

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['rakuten-recommendations'],
    queryFn: () => api.get('/rakuten/orders/recommendations').then(r => r.data),
  })

  const { data: history = [] } = useQuery({
    queryKey: ['rakuten-order-history'],
    queryFn: () => api.get('/rakuten/orders/history').then(r => r.data),
    enabled: tab === 'history',
  })

  const createOrder = useMutation({
    mutationFn: (body) => api.post('/rakuten/orders/history', body),
    onSuccess: () => {
      qc.invalidateQueries(['rakuten-recommendations'])
      qc.invalidateQueries(['rakuten-order-history'])
    },
  })

  const deleteOrder = useMutation({
    mutationFn: (id) => api.delete(`/rakuten/orders/history/${id}`),
    onSuccess: () => qc.invalidateQueries(['rakuten-order-history']),
  })

  const items = data?.items || []
  const settings = data?.settings || {}

  const handleOrder = async (item) => {
    const qty = orderInputs[item.sku] ?? item.order_qty
    if (!qty || qty <= 0) return
    setOrdering(item.sku)
    try {
      await createOrder.mutateAsync({ sku: item.sku, name: item.name, qty: Number(qty) })
    } finally {
      setOrdering(null)
    }
  }

  const handleExcelDownload = async () => {
    const targets = items
      .map(item => ({ sku: item.sku, qty: Number(orderInputs[item.sku] ?? item.order_qty) }))
      .filter(i => i.qty > 0)
    if (targets.length === 0) { alert('発注数が1以上の商品がありません'); return }
    setDownloading(true)
    try { await downloadExcel(targets) } finally { setDownloading(false) }
  }

  if (isLoading) return <div className="loading">読み込み中...</div>

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20, flexWrap: 'wrap' }}>
        <h1>🛒 楽天 発注管理</h1>
        <button className="btn" onClick={() => refetch()} style={{ fontSize: 13 }}>🔄 更新</button>
        <button
          className="btn"
          style={{ fontSize: 13, background: '#22c55e', color: '#fff', border: 'none' }}
          disabled={downloading}
          onClick={handleExcelDownload}
        >
          {downloading ? '生成中...' : '📥 発注Excel（タオタロウ）'}
        </button>
      </div>

      {/* タブ */}
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

      {/* ===== 発注推奨リスト ===== */}
      {tab === 'order' && (
        <>
          {/* 設定サマリー */}
          <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
            {[
              ['目標販売日数', `${settings.target_days ?? 30}日`,   '#dbeafe', '#1e40af'],
              ['リードタイム', `${settings.lead_days ?? 20}日`,     '#dcfce7', '#166534'],
              ['安全在庫率',  `${((settings.safety_stock_rate ?? 0.10) * 100).toFixed(0)}%`, '#fef9c3', '#854d0e'],
              ['発注閾値',    `在庫${settings.threshold_days ?? 60}日分以下`, '#fce7f3', '#9d174d'],
            ].map(([label, val, bg, color]) => (
              <div key={label} style={{ background: bg, borderRadius: 8, padding: '8px 16px', fontSize: 13 }}>
                <span style={{ color }}>{label}: </span>
                <span style={{ color, fontWeight: 800 }}>{val}</span>
              </div>
            ))}
          </div>

          <div className="card" style={{ padding: 0, overflow: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ background: '#f0f2f8', borderBottom: '2px solid #e2e8f0' }}>
                  {['商品名 / SKU', '実在庫', '輸送中', '発注済', '全在庫', '日販', '在庫日数', '成長率', '提案発注数', '発注'].map(h => (
                    <th key={h} style={{ padding: '10px 12px', textAlign: 'center', whiteSpace: 'nowrap' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {items.length === 0 && (
                  <tr><td colSpan={10} style={{ textAlign: 'center', padding: 32, color: '#999' }}>商品マスタに商品を登録してください</td></tr>
                )}
                {items.map(item => {
                  const needsOrder = item.needs_order
                  const rowBg = needsOrder ? '#fff7ed' : 'transparent'
                  const inputVal = orderInputs[item.sku] ?? item.order_qty

                  return (
                    <tr key={item.sku} style={{ borderBottom: '1px solid #f0f2f8', background: rowBg }}>
                      <td style={{ padding: '10px 12px', minWidth: 160 }}>
                        <div style={{ fontWeight: 400, color: '#1a1a2e' }}>{item.name || '—'}</div>
                        <div style={{ color: '#999', fontSize: 11 }}>{item.sku}</div>
                        {item.buy_url && (
                          <a href={item.buy_url} target="_blank" rel="noreferrer" style={{ fontSize: 11, color: '#e94560' }}>仕入れURL</a>
                        )}
                      </td>
                      <td style={{ padding: '10px 12px', textAlign: 'center', fontWeight: 600 }}>{item.stock}</td>
                      <td style={{ padding: '10px 12px', textAlign: 'center', color: '#666' }}>{item.inbound}</td>
                      <td style={{ padding: '10px 12px', textAlign: 'center', color: '#666' }}>{item.ordered}</td>
                      <td style={{ padding: '10px 12px', textAlign: 'center', fontWeight: 600 }}>{item.total_stock}</td>
                      <td style={{ padding: '10px 12px', textAlign: 'center', color: '#666' }}>
                        {item.daily_avg > 0 ? item.daily_avg.toFixed(1) : '—'}
                      </td>
                      <td style={{ padding: '10px 12px', textAlign: 'center' }}>
                        <span className={`badge ${
                          item.days_left < (settings.threshold_days ?? 60) ? 'badge-danger'
                          : item.days_left < 90 ? 'badge-warn' : 'badge-ok'
                        }`}>
                          {item.days_left >= 9999 ? '∞' : `${item.days_left}日`}
                        </span>
                      </td>
                      <td style={{ padding: '10px 12px', textAlign: 'center' }}>
                        <span style={{ color: item.growth_rate > 0 ? '#16a34a' : item.growth_rate < 0 ? '#dc2626' : '#666', fontWeight: 600 }}>
                          {item.growth_rate > 0 ? '+' : ''}{item.growth_rate}%
                        </span>
                      </td>
                      <td style={{ padding: '10px 12px', textAlign: 'center' }}>
                        {needsOrder ? (
                          <span className="badge badge-danger" style={{ fontSize: 14, padding: '4px 12px' }}>{item.order_qty}</span>
                        ) : (
                          <span style={{ color: item.order_qty > 0 ? '#16a34a' : '#999', fontWeight: 600 }}>
                            {item.order_qty > 0 ? item.order_qty : '—'}
                          </span>
                        )}
                      </td>
                      <td style={{ padding: '10px 12px', textAlign: 'center', whiteSpace: 'nowrap' }}>
                        <div style={{ display: 'flex', gap: 4, alignItems: 'center', justifyContent: 'center' }}>
                          <input
                            type="number" min={0}
                            value={inputVal}
                            onChange={e => setOrderInputs(p => ({ ...p, [item.sku]: e.target.value }))}
                            style={{ width: 60, textAlign: 'center', padding: '4px 6px', fontSize: 13 }}
                          />
                          <button
                            className="btn btn-primary"
                            style={{ padding: '4px 10px', fontSize: 12 }}
                            disabled={ordering === item.sku || !inputVal || Number(inputVal) <= 0}
                            onClick={() => handleOrder(item)}
                          >
                            発注
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <div style={{ fontSize: 12, color: '#999', marginTop: 8 }}>
            ※ <span style={{ color: '#ea580c', fontWeight: 700 }}>オレンジ行</span> = 全在庫が閾値（{settings.threshold_days ?? 60}日分）以下 → 発注タイミング
          </div>
        </>
      )}

      {/* ===== 発注済みリスト ===== */}
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
                    <th>発注日</th>
                    <th>SKU</th>
                    <th>商品名</th>
                    <th>発注数</th>
                    <th>メモ</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {history.map(row => (
                    <tr key={row.id}>
                      <td style={{ fontSize: 12, whiteSpace: 'nowrap', color: '#666' }}>
                        {row.ordered_at || '—'}
                      </td>
                      <td style={{ fontFamily: 'monospace', fontSize: 12 }}>{row.sku}</td>
                      <td style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{row.name || '—'}</td>
                      <td style={{ textAlign: 'right', fontWeight: 600 }}>{row.qty}</td>
                      <td style={{ fontSize: 12, color: '#666' }}>{row.memo || '—'}</td>
                      <td>
                        <button
                          className="btn btn-sm"
                          style={{ background: '#fee2e2', color: '#991b1b', whiteSpace: 'nowrap' }}
                          onClick={() => {
                            if (confirm(`${row.sku} を発注済みリストから削除しますか？\n（納品済みの場合に押してください）`))
                              deleteOrder.mutate(row.id)
                          }}
                        >納品済</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <td colSpan={3} style={{ textAlign: 'right', fontWeight: 700, paddingTop: 12 }}>合計</td>
                    <td style={{ textAlign: 'right', fontWeight: 700 }}>
                      {history.reduce((s, r) => s + r.qty, 0)} 個
                    </td>
                    <td colSpan={2}></td>
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
