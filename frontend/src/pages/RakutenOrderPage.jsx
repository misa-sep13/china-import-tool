import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'

async function downloadExcel(items) {
  const res = await api.post('/rakuten/orders/excel', { items }, { responseType: 'blob' })
  const url = URL.createObjectURL(new Blob([res.data]))
  const a = document.createElement('a')
  a.href = url
  a.download = 'rakuten_order.xlsx'
  a.click()
  URL.revokeObjectURL(url)
}

export default function RakutenOrderPage() {
  const qc = useQueryClient()
  const [orderInputs, setOrderInputs] = useState({})   // { sku: qty }
  const [ordering, setOrdering] = useState(null)
  const [downloading, setDownloading] = useState(false)

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['rakuten-recommendations'],
    queryFn: () => api.get('/rakuten/orders/recommendations').then(r => r.data),
  })

  const { data: historyData } = useQuery({
    queryKey: ['rakuten-order-history'],
    queryFn: () => api.get('/rakuten/orders/history').then(r => r.data),
  })

  const createOrder = useMutation({
    mutationFn: (body) => api.post('/rakuten/orders/history', body),
    onSuccess: () => { qc.invalidateQueries(['rakuten-recommendations']); qc.invalidateQueries(['rakuten-order-history']) },
  })

  const deliverOrder = useMutation({
    mutationFn: (id) => api.patch(`/rakuten/orders/history/${id}/deliver`),
    onSuccess: () => { qc.invalidateQueries(['rakuten-recommendations']); qc.invalidateQueries(['rakuten-order-history']) },
  })

  const deleteOrder = useMutation({
    mutationFn: (id) => api.delete(`/rakuten/orders/history/${id}`),
    onSuccess: () => qc.invalidateQueries(['rakuten-order-history']),
  })

  const items = data?.items || []
  const settings = data?.settings || {}
  const history = (historyData || []).filter(o => !o.is_delivered)

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

  if (isLoading) return <div className="loading">読み込み中...</div>

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24, flexWrap: 'wrap' }}>
        <h1>🛒 楽天 発注管理</h1>
        <button className="btn" onClick={() => refetch()} style={{ fontSize: 13 }}>🔄 更新</button>
        <button
          className="btn"
          style={{ fontSize: 13, background: '#22c55e', color: '#fff', border: 'none' }}
          disabled={downloading}
          onClick={async () => {
            const targets = items
              .map(item => ({ sku: item.sku, qty: Number(orderInputs[item.sku] ?? item.order_qty) }))
              .filter(i => i.qty > 0)
            if (targets.length === 0) { alert('発注数が1以上の商品がありません'); return }
            setDownloading(true)
            try { await downloadExcel(targets) } finally { setDownloading(false) }
          }}
        >
          {downloading ? '生成中...' : '📥 発注Excel（タオタロウ）'}
        </button>
      </div>

      {/* 設定サマリー */}
      <div style={{ display: 'flex', gap: 16, marginBottom: 20, flexWrap: 'wrap' }}>
        {[
          ['目標販売日数', `${settings.target_days ?? 30}日`,    '#dbeafe', '#1e40af'],
          ['リードタイム', `${settings.lead_days ?? 20}日`,      '#dcfce7', '#166534'],
          ['安全在庫率',  `${((settings.safety_stock_rate ?? 0.10) * 100).toFixed(0)}%`, '#fef9c3', '#854d0e'],
          ['発注閾値',    `在庫${settings.threshold_days ?? 60}日分以下`, '#fce7f3', '#9d174d'],
        ].map(([label, val, bg, color]) => (
          <div key={label} style={{ background: bg, borderRadius: 8, padding: '8px 16px', fontSize: 13 }}>
            <span style={{ color }}>{label}: </span>
            <span style={{ color, fontWeight: 800 }}>{val}</span>
          </div>
        ))}
      </div>

      {/* 発注推奨テーブル */}
      <div className="card" style={{ padding: 0, overflow: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: '#1e2433', borderBottom: '2px solid #2d3748' }}>
              {['商品名 / SKU', '実在庫', '輸送中', '発注済', '全在庫', '日販', '在庫日数', '成長率', '提案発注数', '発注'].map(h => (
                <th key={h} style={{ padding: '10px 12px', textAlign: 'center', color: '#94a3b8', fontWeight: 600, whiteSpace: 'nowrap' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && (
              <tr><td colSpan={10} style={{ textAlign: 'center', padding: 32, color: '#64748b' }}>商品マスタに商品を登録してください</td></tr>
            )}
            {items.map(item => {
              const needsOrder = item.needs_order
              const rowBg = needsOrder ? 'rgba(251,146,60,0.08)' : 'transparent'
              const inputVal = orderInputs[item.sku] ?? item.order_qty

              return (
                <tr key={item.sku} style={{ borderBottom: '1px solid #2d3748', background: rowBg }}>
                  <td style={{ padding: '10px 12px', minWidth: 160 }}>
                    <div style={{ fontWeight: 600, color: '#e2e8f0' }}>{item.name || '—'}</div>
                    <div style={{ color: '#64748b', fontSize: 11 }}>{item.sku}</div>
                    {item.buy_url && (
                      <a href={item.buy_url} target="_blank" rel="noreferrer" style={{ fontSize: 11, color: '#60a5fa' }}>仕入れURL</a>
                    )}
                  </td>
                  {/* 実在庫 */}
                  <td style={{ padding: '10px 12px', textAlign: 'center', fontWeight: 700, color: '#e2e8f0' }}>{item.stock}</td>
                  {/* 輸送中 */}
                  <td style={{ padding: '10px 12px', textAlign: 'center', color: '#94a3b8' }}>{item.inbound}</td>
                  {/* 発注済 */}
                  <td style={{ padding: '10px 12px', textAlign: 'center', color: '#94a3b8' }}>{item.ordered}</td>
                  {/* 全在庫 */}
                  <td style={{ padding: '10px 12px', textAlign: 'center', color: '#e2e8f0', fontWeight: 600 }}>{item.total_stock}</td>
                  {/* 日販 */}
                  <td style={{ padding: '10px 12px', textAlign: 'center', color: '#94a3b8' }}>
                    {item.daily_avg > 0 ? item.daily_avg.toFixed(1) : '—'}
                  </td>
                  {/* 在庫日数 */}
                  <td style={{ padding: '10px 12px', textAlign: 'center' }}>
                    <span style={{
                      fontWeight: 700,
                      color: item.days_left < (settings.threshold_days ?? 30) ? '#fb923c'
                           : item.days_left < 45 ? '#fcd34d' : '#4ade80',
                    }}>
                      {item.days_left >= 9999 ? '∞' : `${item.days_left}日`}
                    </span>
                  </td>
                  {/* 成長率 */}
                  <td style={{ padding: '10px 12px', textAlign: 'center' }}>
                    <span style={{ color: item.growth_rate > 0 ? '#4ade80' : item.growth_rate < 0 ? '#f87171' : '#94a3b8', fontWeight: 600 }}>
                      {item.growth_rate > 0 ? '+' : ''}{item.growth_rate}%
                    </span>
                  </td>
                  {/* 提案発注数 */}
                  <td style={{ padding: '10px 12px', textAlign: 'center' }}>
                    {needsOrder ? (
                      <span style={{ background: '#fb923c', color: '#fff', fontWeight: 800, borderRadius: 6, padding: '3px 10px', fontSize: 14 }}>
                        {item.order_qty}
                      </span>
                    ) : (
                      <span style={{ color: '#4ade80', fontWeight: 700 }}>{item.order_qty > 0 ? item.order_qty : '—'}</span>
                    )}
                  </td>
                  {/* 発注 */}
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

      {/* 内訳ポップアップ用の凡例 */}
      <div style={{ fontSize: 12, color: '#64748b', marginTop: 8 }}>
        ※ <span style={{ color: '#fb923c', fontWeight: 700 }}>オレンジ</span> = 全在庫が閾値（{settings.threshold_days ?? 30}日分）以下 → 発注タイミング
      </div>

      {/* 発注済みリスト */}
      {history.length > 0 && (
        <div className="card" style={{ marginTop: 32 }}>
          <h2>📋 発注済みリスト（未納品）</h2>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: '2px solid #2d3748' }}>
                {['SKU', '商品名', '数量', '発注日', '操作'].map(h => (
                  <th key={h} style={{ padding: '8px 12px', textAlign: 'left', color: '#94a3b8' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {history.map(o => (
                <tr key={o.id} style={{ borderBottom: '1px solid #2d3748' }}>
                  <td style={{ padding: '8px 12px', color: '#94a3b8' }}>{o.sku}</td>
                  <td style={{ padding: '8px 12px', color: '#e2e8f0' }}>{o.name || '—'}</td>
                  <td style={{ padding: '8px 12px', fontWeight: 700, color: '#e2e8f0' }}>{o.qty}</td>
                  <td style={{ padding: '8px 12px', color: '#94a3b8' }}>{o.ordered_at || '—'}</td>
                  <td style={{ padding: '8px 12px' }}>
                    <div style={{ display: 'flex', gap: 8 }}>
                      <button
                        className="btn btn-primary"
                        style={{ fontSize: 12, padding: '3px 10px' }}
                        onClick={() => deliverOrder.mutate(o.id)}
                      >
                        ✅ 納品済み
                      </button>
                      <button
                        className="btn"
                        style={{ fontSize: 12, padding: '3px 10px', color: '#f87171' }}
                        onClick={() => { if (confirm('削除しますか？')) deleteOrder.mutate(o.id) }}
                      >
                        削除
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
