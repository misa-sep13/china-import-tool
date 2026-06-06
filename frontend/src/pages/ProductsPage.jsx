import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'

const EMPTY = {
  sku: '', fnsku: '', asin: '', name: '', buy_url: '', photo_url: '',
  color: '', size: '', price: '', repack: '', note: '', set_size: 1, extra_stock: 0,
  amazon_fee_rate: 0.1,
}

function calcProfit(p, exchangeRate) {
  if (!p.selling_price || !p.price) return null
  const costJpy = p.price * exchangeRate
  const amazonFee = p.selling_price * (p.amazon_fee_rate ?? 0.1)
  const fbaFee = p.fba_fee ?? 0
  const profit = p.selling_price - costJpy - amazonFee - fbaFee
  const rate = profit / p.selling_price
  return { profit: Math.round(profit), rate: (rate * 100).toFixed(1) }
}

export default function ProductsPage() {
  const qc = useQueryClient()
  const [modal, setModal] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState(EMPTY)
  const [error, setError] = useState('')
  const [inlineEdit, setInlineEdit] = useState(null)
  const [refreshing, setRefreshing] = useState(false)

  const { data: products = [], isLoading } = useQuery({
    queryKey: ['products'],
    queryFn: () => api.get('/products/').then(r => r.data),
  })

  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: () => api.get('/settings/').then(r => r.data),
  })

  const exchangeRate = settings?.exchange_rate ?? 21

  const save = useMutation({
    mutationFn: (d) => editing
      ? api.put(`/products/${editing.id}`, d)
      : api.post('/products/', d),
    onSuccess: () => { qc.invalidateQueries(['products']); closeModal() },
    onError: (e) => setError(e.response?.data?.detail || '保存に失敗しました'),
  })

  const del = useMutation({
    mutationFn: (id) => api.delete(`/products/${id}`),
    onSuccess: () => qc.invalidateQueries(['products']),
  })

  const [importing, setImporting] = useState(false)

  const importFromFba = async () => {
    if (!confirm('SP-APIのFBA在庫から商品を自動インポートします。よろしいですか？')) return
    setImporting(true)
    try {
      const res = await api.post('/fba/import')
      const { added, skipped, fixed = 0 } = res.data
      alert(`インポート完了！\n追加: ${added}件\nFNSKU修正: ${fixed}件\nスキップ(既存): ${skipped}件`)
      qc.invalidateQueries(['products'])
    } catch (e) {
      alert('インポート失敗: ' + (e.response?.data?.detail || e.message))
    } finally {
      setImporting(false)
    }
  }

  const handleRefreshFees = async () => {
    if (!confirm('SP-APIから全商品の販売価格・FBA手数料を取得します。\n商品数によっては数分かかります。よろしいですか？')) return
    setRefreshing(true)
    try {
      const res = await api.post('/products/refresh-fees')
      alert(`更新完了！${res.data.updated}件の価格・手数料を更新しました。`)
      qc.invalidateQueries(['products'])
    } catch (e) {
      alert('更新失敗: ' + (e.response?.data?.detail || e.message))
    } finally {
      setRefreshing(false)
    }
  }

  const openNew = () => { setEditing(null); setForm(EMPTY); setError(''); setModal(true) }
  const openEdit = (p) => {
    setEditing(p)
    setForm({ ...EMPTY, ...p })
    setError('')
    setModal(true)
  }
  const closeModal = () => setModal(false)

  const handleSubmit = (e) => {
    e.preventDefault()
    const data = {
      ...form,
      price: Number(form.price) || 0,
      set_size: Number(form.set_size) || 1,
      extra_stock: Number(form.extra_stock) || 0,
      amazon_fee_rate: Number(form.amazon_fee_rate) || 0.1,
    }
    save.mutate(data)
  }

  const f = (k) => ({ value: form[k] ?? '', onChange: e => setForm(p => ({ ...p, [k]: e.target.value })) })

  const saveInlineName = useMutation({
    mutationFn: ({ id, name }) => api.put(`/products/${id}`, { name }),
    onSuccess: () => { qc.invalidateQueries(['products']); setInlineEdit(null) },
    onError: () => alert('商品名の保存に失敗しました'),
  })

  const handleInlineKeyDown = (e, id) => {
    if (e.key === 'Enter') saveInlineName.mutate({ id, name: inlineEdit.value })
    if (e.key === 'Escape') setInlineEdit(null)
  }

  // 最終更新日時（全商品で最新のもの）
  const lastUpdated = products
    .map(p => p.fees_updated_at)
    .filter(Boolean)
    .sort()
    .at(-1)

  if (isLoading) return <div className="loading">読み込み中...</div>

  return (
    <div>
      <h1>🏷️ 商品マスタ</h1>
      <div className="top-actions">
        <button className="btn btn-primary" onClick={openNew}>＋ 商品を追加</button>
        <button className="btn btn-secondary" onClick={importFromFba} disabled={importing}>
          {importing ? 'インポート中...' : '📦 FBAから自動インポート'}
        </button>
        <button className="btn btn-secondary" onClick={handleRefreshFees} disabled={refreshing}>
          {refreshing ? '取得中...' : '💰 価格・手数料を更新'}
        </button>
        <span style={{ color: '#888', fontSize: 13 }}>
          {products.length}件登録済み
          {lastUpdated && (
            <span style={{ marginLeft: 8 }}>
              （最終取得: {new Date(lastUpdated).toLocaleDateString('ja-JP')}）
            </span>
          )}
        </span>
      </div>

      {products.length === 0 ? (
        <div className="card empty-state">
          <div style={{ fontSize: 40 }}>🏷️</div>
          <p>商品が登録されていません。「＋ 商品を追加」から登録してください。</p>
        </div>
      ) : (
        <div className="card">
          <div style={{ overflowX: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th>SKU</th>
                  <th>商品名</th>
                  <th>色/サイズ</th>
                  <th style={{ textAlign: 'right' }}>仕入(元)</th>
                  <th style={{ textAlign: 'right' }}>販売価格(円)</th>
                  <th style={{ textAlign: 'right' }}>FBA手数料</th>
                  <th style={{ textAlign: 'right' }}>Amazon手数料率</th>
                  <th style={{ textAlign: 'right' }}>利益額</th>
                  <th style={{ textAlign: 'right' }}>利益率</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {products.map(p => {
                  const profit = calcProfit(p, exchangeRate)
                  return (
                    <tr key={p.id}>
                      <td style={{ fontFamily: 'monospace', fontSize: 12, whiteSpace: 'nowrap' }}>{p.sku}</td>
                      <td style={{ maxWidth: 180 }}>
                        {inlineEdit?.id === p.id ? (
                          <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                            <input
                              autoFocus
                              value={inlineEdit.value}
                              onChange={e => setInlineEdit(v => ({ ...v, value: e.target.value }))}
                              onKeyDown={e => handleInlineKeyDown(e, p.id)}
                              style={{ fontSize: 13, padding: '2px 6px', border: '1px solid #3b82f6', borderRadius: 4, width: 140 }}
                            />
                            <button className="btn btn-primary btn-sm"
                              onClick={() => saveInlineName.mutate({ id: p.id, name: inlineEdit.value })}
                              disabled={saveInlineName.isPending}>✓</button>
                            <button className="btn btn-secondary btn-sm"
                              onClick={() => setInlineEdit(null)}>✕</button>
                          </div>
                        ) : (
                          <span
                            onClick={() => setInlineEdit({ id: p.id, value: p.name || '' })}
                            title="クリックして商品名を編集"
                            style={{
                              display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                              cursor: 'pointer', padding: '2px 4px', borderRadius: 4,
                              color: p.name ? 'inherit' : '#aaa',
                              background: p.name ? 'transparent' : '#fef9c3',
                            }}
                          >
                            {p.name || '(未入力)'}
                          </span>
                        )}
                      </td>
                      <td style={{ fontSize: 12, color: '#666', whiteSpace: 'nowrap' }}>
                        {[p.color, p.size].filter(Boolean).join(' / ')}
                      </td>
                      <td style={{ textAlign: 'right' }}>{p.price ? `¥${(p.price * exchangeRate).toFixed(0)}` : '-'}</td>
                      <td style={{ textAlign: 'right' }}>
                        {p.selling_price ? `¥${p.selling_price.toLocaleString()}` : <span style={{ color: '#bbb' }}>未取得</span>}
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        {p.fba_fee ? `¥${p.fba_fee.toLocaleString()}` : <span style={{ color: '#bbb' }}>-</span>}
                      </td>
                      <td style={{ textAlign: 'right', fontSize: 12 }}>
                        {((p.amazon_fee_rate ?? 0.1) * 100).toFixed(0)}%
                      </td>
                      <td style={{ textAlign: 'right', fontWeight: 600, color: profit ? (profit.profit >= 0 ? '#16a34a' : '#dc2626') : '#bbb' }}>
                        {profit ? `¥${profit.profit.toLocaleString()}` : '-'}
                      </td>
                      <td style={{ textAlign: 'right', fontWeight: 600, color: profit ? (parseFloat(profit.rate) >= 20 ? '#16a34a' : parseFloat(profit.rate) >= 10 ? '#ca8a04' : '#dc2626') : '#bbb' }}>
                        {profit ? `${profit.rate}%` : '-'}
                      </td>
                      <td>
                        <div style={{ display: 'flex', gap: 6 }}>
                          <button className="btn btn-secondary btn-sm" onClick={() => openEdit(p)}>編集</button>
                          <button className="btn btn-sm" style={{ background: '#fee2e2', color: '#991b1b' }}
                            onClick={() => { if (confirm('削除しますか？')) del.mutate(p.id) }}>削除</button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {modal && (
        <div className="modal-overlay" onClick={e => e.target === e.currentTarget && closeModal()}>
          <div className="modal">
            <div className="modal-header">
              <h2>{editing ? '商品を編集' : '商品を追加'}</h2>
              <button className="modal-close" onClick={closeModal}>✕</button>
            </div>
            <form onSubmit={handleSubmit}>
              <div className="form-grid">
                <div className="form-group">
                  <label>SKU *</label>
                  <input {...f('sku')} required />
                </div>
                <div className="form-group">
                  <label>FNSKU</label>
                  <input {...f('fnsku')} />
                </div>
                <div className="form-group">
                  <label>ASIN</label>
                  <input {...f('asin')} />
                </div>
                <div className="form-group" style={{ gridColumn: 'span 2' }}>
                  <label>商品名</label>
                  <input {...f('name')} />
                </div>
                <div className="form-group">
                  <label>色</label>
                  <input {...f('color')} />
                </div>
                <div className="form-group">
                  <label>サイズ/規格</label>
                  <input {...f('size')} />
                </div>
                <div className="form-group">
                  <label>仕入単価(元)</label>
                  <input type="number" step="0.01" {...f('price')} />
                </div>
                <div className="form-group">
                  <label>セット数</label>
                  <input type="number" min={1} {...f('set_size')} />
                </div>
                <div className="form-group">
                  <label>Amazon手数料率</label>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <input type="number" step="0.01" min={0} max={1} {...f('amazon_fee_rate')} style={{ width: 80 }} />
                    <span style={{ color: '#888', fontSize: 13 }}>
                      ({((Number(form.amazon_fee_rate) || 0) * 100).toFixed(0)}%)
                    </span>
                  </div>
                </div>
                <div className="form-group">
                  <label>別個数在庫</label>
                  <input type="number" min={0} {...f('extra_stock')} />
                </div>
                <div className="form-group" style={{ gridColumn: 'span 2' }}>
                  <label>仕入URL（1688/TAOBao）</label>
                  <input {...f('buy_url')} placeholder="https://detail.1688.com/..." />
                </div>
                <div className="form-group" style={{ gridColumn: 'span 2' }}>
                  <label>画像URL</label>
                  <input {...f('photo_url')} />
                </div>
                <div className="form-group">
                  <label>リパック</label>
                  <input {...f('repack')} />
                </div>
                <div className="form-group" style={{ gridColumn: 'span 2' }}>
                  <label>備考</label>
                  <textarea {...f('note')} rows={2} style={{ resize: 'vertical' }} />
                </div>
              </div>
              {error && <p className="error-msg">{error}</p>}
              <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 8 }}>
                <button type="button" className="btn btn-secondary" onClick={closeModal}>キャンセル</button>
                <button type="submit" className="btn btn-primary" disabled={save.isPending}>
                  {save.isPending ? '保存中...' : '保存'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
