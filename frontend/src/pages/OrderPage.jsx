import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '../api/client'

export default function OrderPage() {
  const [items, setItems] = useState(null)
  const [loading, setLoading] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [error, setError] = useState('')

  const fetchPreview = async () => {
    setLoading(true)
    setError('')
    try {
      const res = await api.get('/orders/preview')
      setItems(res.data)
      if (res.data.length === 0) setError('発注対象の商品がありません（全商品の在庫が十分です）')
    } catch (e) {
      setError(e.response?.data?.detail || 'データの取得に失敗しました')
    } finally {
      setLoading(false)
    }
  }

  const updateQty = (idx, val) => {
    setItems(prev => prev.map((item, i) => i === idx ? { ...item, qty: Number(val) } : item))
  }

  const handleExport = async () => {
    const targets = items.filter(i => i.qty > 0)
    if (!targets.length) { setError('発注数が0の商品しかありません'); return }
    setExporting(true)
    try {
      const res = await api.post('/orders/export', { items: targets }, { responseType: 'blob' })
      const url = window.URL.createObjectURL(new Blob([res.data]))
      const a = document.createElement('a')
      a.href = url
      a.download = `taotaro_order_${new Date().toISOString().slice(0,10)}.xlsx`
      a.click()
      window.URL.revokeObjectURL(url)
    } catch (e) {
      setError('Excelの出力に失敗しました')
    } finally {
      setExporting(false)
    }
  }

  const daysBadge = (days) => {
    if (days < 30) return <span className="badge badge-danger">{days}日</span>
    if (days < 60) return <span className="badge badge-warn">{days}日</span>
    return <span className="badge badge-ok">{days}日</span>
  }

  return (
    <div>
      <h1>📦 発注管理</h1>

      <div className="card">
        <p style={{ marginBottom: 14, color: '#555', fontSize: 13 }}>
          Amazon SP-APIから在庫・売上データを取得し、推奨発注数を自動計算します。<br />
          数量を確認・調整して「Excelダウンロード」でTAO太郎用の発注書を出力できます。
        </p>
        <div className="top-actions">
          <button className="btn btn-primary" onClick={fetchPreview} disabled={loading}>
            {loading ? '取得中...' : '🔄 発注数を計算する'}
          </button>
          {items && items.length > 0 && (
            <button className="btn btn-success" onClick={handleExport} disabled={exporting}>
              {exporting ? '生成中...' : '📥 Excelダウンロード'}
            </button>
          )}
        </div>
        {error && <p className="error-msg">{error}</p>}
      </div>

      {items && items.length > 0 && (
        <div className="card">
          <h2>発注推奨リスト（{items.length}件）</h2>
          <div style={{ overflowX: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th>SKU</th>
                  <th>商品名</th>
                  <th>色/サイズ</th>
                  <th>残日数</th>
                  <th>在庫</th>
                  <th>日販</th>
                  <th>発注数</th>
                  <th>単価(元)</th>
                  <th>小計(元)</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item, idx) => (
                  <tr key={item.product_id}>
                    <td style={{ fontFamily: 'monospace', fontSize: 12 }}>{item.sku}</td>
                    <td style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {item.name}
                    </td>
                    <td style={{ fontSize: 12, color: '#666' }}>{[item.color, item.size].filter(Boolean).join(' / ')}</td>
                    <td>{daysBadge(item.days_left)}</td>
                    <td style={{ textAlign: 'right' }}>{item.stock}</td>
                    <td style={{ textAlign: 'right' }}>{item.daily}</td>
                    <td>
                      <input
                        type="number"
                        className="qty-input"
                        min={0}
                        value={item.qty}
                        onChange={e => updateQty(idx, e.target.value)}
                      />
                    </td>
                    <td style={{ textAlign: 'right' }}>{item.price}</td>
                    <td style={{ textAlign: 'right', fontWeight: 600 }}>
                      {(item.qty * item.price).toFixed(0)}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <td colSpan={8} style={{ textAlign: 'right', fontWeight: 700, paddingTop: 12 }}>合計</td>
                  <td style={{ textAlign: 'right', fontWeight: 700 }}>
                    {items.reduce((s, i) => s + i.qty * i.price, 0).toFixed(0)} 元
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        </div>
      )}

      {items && items.length === 0 && !error && (
        <div className="card empty-state">
          <div style={{ fontSize: 40 }}>✅</div>
          <p>現在、発注が必要な商品はありません。</p>
        </div>
      )}
    </div>
  )
}
