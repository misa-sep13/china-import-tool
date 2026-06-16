import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'

export default function RakutenStockPage() {
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [supplierFilter, setSupplierFilter] = useState('')
  const [editingId, setEditingId] = useState(null)
  const [editVals, setEditVals] = useState({})
  const [importingStock, setImportingStock] = useState(false)
  const [importStockResult, setImportStockResult] = useState(null)

  const handleImportStock = async () => {
    if (!window.confirm('RMSから現在の在庫数を取得してDBに保存します。よろしいですか？')) return
    setImportingStock(true)
    setImportStockResult(null)
    try {
      const res = await api.post('/rakuten/rms/import-stock')
      setImportStockResult(res.data)
      qc.invalidateQueries(['rakuten-stock'])
    } catch (err) {
      setImportStockResult({ error: err.response?.data?.detail || '在庫取得エラーが発生しました' })
    } finally {
      setImportingStock(false)
    }
  }

  const { data: items = [], isLoading } = useQuery({
    queryKey: ['rakuten-stock'],
    queryFn: () => api.get('/rakuten/stock').then(r => r.data),
  })

  const { data: settings } = useQuery({
    queryKey: ['rakuten-settings'],
    queryFn: () => api.get('/rakuten/settings').then(r => r.data),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }) => api.patch(`/rakuten/products/${id}/stock`, data),
    onSuccess: () => {
      qc.invalidateQueries(['rakuten-stock'])
      setEditingId(null)
    },
  })

  const updatePriceMutation = useMutation({
    mutationFn: ({ id, selling_price, stock, inbound, standard_stock }) =>
      api.put(`/rakuten/products/${id}`, { selling_price, stock, inbound, standard_stock }),
    onSuccess: () => {
      qc.invalidateQueries(['rakuten-stock'])
      setEditingId(null)
    },
  })

  const suppliers = [...new Set(items.map(p => p.supplier).filter(Boolean))].sort()

  const filtered = items.filter(p => {
    if (supplierFilter && (p.supplier || '') !== supplierFilter) return false
    if (!search) return true
    const q = search.toLowerCase()
    return (p.sku || '').toLowerCase().includes(q) ||
           (p.name || '').toLowerCase().includes(q) ||
           (p.spec || '').toLowerCase().includes(q)
  })

  const commissionRate = settings?.commission_rate ?? 0.09

  const startEdit = (p) => {
    setEditingId(p.id)
    setEditVals({
      selling_price: p.selling_price ?? '',
      shipping_fee: p.shipping_fee ?? 180,
      stock: p.stock ?? 0,
      inbound: p.inbound ?? 0,
      standard_stock: p.standard_stock ?? 0,
    })
  }

  const saveEdit = (p) => {
    const sp = editVals.selling_price !== '' ? Number(editVals.selling_price) : null
    const commission = sp ? sp * commissionRate : null
    const cost = p.cost_jpy || 0
    api.put(`/rakuten/products/${p.id}`, {
      ...p,
      selling_price: sp,
      shipping_fee: Number(editVals.shipping_fee),
      stock: Number(editVals.stock),
      inbound: Number(editVals.inbound),
      standard_stock: Number(editVals.standard_stock),
    }).then(() => {
      qc.invalidateQueries(['rakuten-stock'])
      setEditingId(null)
    })
  }

  if (isLoading) return <div className="loading">読み込み中...</div>

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24, flexWrap: 'wrap' }}>
        <h1>📦 楽天 在庫・損益一覧</h1>
        <span style={{ fontSize: 12, color: '#64748b' }}>手数料率: {(commissionRate * 100).toFixed(0)}%</span>
        <button className="btn" style={{ fontSize: 13 }} onClick={handleImportStock} disabled={importingStock}>
          {importingStock ? '取得中...' : '📦 在庫取得(RMS)'}
        </button>
        {importStockResult && (
          <span style={{ fontSize: 12, color: importStockResult.error ? '#e53e3e' : '#38a169' }}>
            {importStockResult.error || `${importStockResult.updated}件更新・${importStockResult.not_found}件未登録`}
          </span>
        )}
      </div>

      <div className="card" style={{ padding: '12px 16px', marginBottom: 16, display: 'flex', gap: 12, alignItems: 'center' }}>
        <input
          type="text" placeholder="SKU・商品名・仕様で絞り込み"
          value={search} onChange={e => setSearch(e.target.value)}
          style={{ flex: '1 1 380px', minWidth: 0 }}
        />
        <select value={supplierFilter} onChange={e => setSupplierFilter(e.target.value)} style={{ width: 160, flex: '0 0 160px' }}>
          <option value="">仕入れ先: すべて</option>
          {suppliers.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <span style={{ fontSize: 12, color: '#6b7280' }}>{filtered.length}件</span>
      </div>

      <div className="card" style={{ padding: 0, overflow: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: '#f0f2f8', borderBottom: '2px solid #e2e8f0' }}>
              {['SKU', '商品名', '仕様', 'お客様専用メモ', '仕入原価(元)', '販売価格(円)', '送料', '手数料', '利益額', '利益率', '実在庫', '輸送中', '規定在庫', '直近30日', '前30日', '備考', ''].map(h => (
                <th key={h} style={{ padding: '10px 10px', textAlign: 'center', color: '#333', whiteSpace: 'nowrap', fontWeight: 700, fontSize: 12 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr><td colSpan={17} style={{ textAlign: 'center', padding: 32, color: '#999' }}>商品がありません</td></tr>
            )}
            {filtered.map(p => {
              const isEditing = editingId === p.id
              const sp = isEditing ? (editVals.selling_price !== '' ? Number(editVals.selling_price) : null) : p.selling_price
              const shippingFee = isEditing ? Number(editVals.shipping_fee ?? 180) : (p.shipping_fee ?? 180)
              const commission = sp ? Math.round(sp * commissionRate) : null
              const cost = p.cost_jpy || 0
              const profit = (sp && commission !== null) ? Math.round(sp - cost - commission - shippingFee) : null
              const profitRate = (sp && profit !== null) ? (profit / sp * 100).toFixed(1) : null

              return (
                <tr key={p.id} style={{ borderBottom: '1px solid #e5e7eb', background: isEditing ? '#f0f9ff' : '#fff' }}>
                  <td style={{ padding: '8px 10px', fontFamily: 'monospace', fontSize: 12, color: '#666', whiteSpace: 'nowrap' }}>{p.sku}</td>
                  <td style={{ padding: '8px 10px', minWidth: 140, color: '#1a1a2e' }}>{p.name || '—'}</td>
                  <td style={{ padding: '8px 10px', color: '#666', fontSize: 12 }}>{p.spec || '—'}</td>
                  <td style={{ padding: '8px 10px', color: '#666', fontSize: 12, maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.customer_memo || '—'}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', color: '#666' }}>{cost ? `¥${cost}` : '—'}</td>

                  {/* 販売価格 */}
                  <td style={{ padding: '8px 10px', textAlign: 'right' }}>
                    {isEditing ? (
                      <input type="number" value={editVals.selling_price} onChange={e => setEditVals(v => ({ ...v, selling_price: e.target.value }))}
                        style={{ width: 80, textAlign: 'right' }} />
                    ) : (
                      <span style={{ fontWeight: 600 }}>{sp ? `¥${sp.toLocaleString()}` : '—'}</span>
                    )}
                  </td>

                  {/* 送料 */}
                  <td style={{ padding: '8px 10px', textAlign: 'right', color: '#666' }}>
                    {isEditing ? (
                      <input type="number" value={editVals.shipping_fee} onChange={e => setEditVals(v => ({ ...v, shipping_fee: e.target.value }))}
                        style={{ width: 70, textAlign: 'right' }} />
                    ) : (
                      `¥${shippingFee}`
                    )}
                  </td>

                  <td style={{ padding: '8px 10px', textAlign: 'right', color: '#666' }}>{commission !== null ? `¥${commission.toLocaleString()}` : '—'}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', fontWeight: 600, color: profit > 0 ? '#16a34a' : profit < 0 ? '#dc2626' : '#666' }}>
                    {profit !== null ? `¥${profit.toLocaleString()}` : '—'}
                  </td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', fontWeight: 600, color: profitRate > 30 ? '#16a34a' : profitRate > 0 ? '#d97706' : '#dc2626' }}>
                    {profitRate !== null ? `${profitRate}%` : '—'}
                  </td>

                  {/* 実在庫 */}
                  <td style={{ padding: '8px 10px', textAlign: 'center' }}>
                    {isEditing ? (
                      <input type="number" value={editVals.stock} onChange={e => setEditVals(v => ({ ...v, stock: e.target.value }))}
                        style={{ width: 60, textAlign: 'center' }} />
                    ) : (
                      <span style={{ fontWeight: 600 }}>{p.stock}</span>
                    )}
                  </td>
                  {/* 輸送中 */}
                  <td style={{ padding: '8px 10px', textAlign: 'center', color: '#666' }}>
                    {isEditing ? (
                      <input type="number" value={editVals.inbound} onChange={e => setEditVals(v => ({ ...v, inbound: e.target.value }))}
                        style={{ width: 60, textAlign: 'center' }} />
                    ) : p.inbound}
                  </td>
                  {/* 規定在庫 */}
                  <td style={{ padding: '8px 10px', textAlign: 'center', color: '#666' }}>
                    {isEditing ? (
                      <input type="number" value={editVals.standard_stock} onChange={e => setEditVals(v => ({ ...v, standard_stock: e.target.value }))}
                        style={{ width: 60, textAlign: 'center' }} />
                    ) : p.standard_stock}
                  </td>

                  <td style={{ padding: '8px 10px', textAlign: 'center', color: '#2563eb', fontWeight: 600 }}>{p.sales_30_recent}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'center', color: '#666' }}>{p.sales_30_prev}</td>
                  <td style={{ padding: '8px 10px', color: '#666', fontSize: 12, maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.notes || '—'}</td>

                  <td style={{ padding: '8px 10px', whiteSpace: 'nowrap' }}>
                    {isEditing ? (
                      <div style={{ display: 'flex', gap: 4 }}>
                        <button className="btn btn-primary" style={{ fontSize: 11, padding: '3px 8px' }} onClick={() => saveEdit(p)}>保存</button>
                        <button className="btn" style={{ fontSize: 11, padding: '3px 8px' }} onClick={() => setEditingId(null)}>取消</button>
                      </div>
                    ) : (
                      <button className="btn" style={{ fontSize: 11, padding: '3px 8px' }} onClick={() => startEdit(p)}>編集</button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
