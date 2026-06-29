import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'

const EMPTY = {
  sku: '', fnsku: '', asin: '', name: '', buy_url: '', photo_url: '',
  color: '', size: '', spec: '', customer_memo: '', price: '', repack: '', note: '',
  set_size: 1, extra_stock: 0, amazon_fee_rate: 0.1,
}
const EDITABLE_FIELDS = Object.keys(EMPTY)

const toNumber = (value, fallback) => {
  if (value === '' || value == null) return fallback
  const n = Number(value)
  return Number.isFinite(n) ? n : fallback
}

const buildFormData = (source) => {
  const data = {}
  EDITABLE_FIELDS.forEach(key => {
    data[key] = source[key] ?? ''
  })
  data.price = toNumber(source.price, 0)
  data.set_size = Math.max(1, Math.trunc(toNumber(source.set_size, 1)))
  data.extra_stock = Math.max(0, Math.trunc(toNumber(source.extra_stock, 0)))
  data.amazon_fee_rate = toNumber(source.amazon_fee_rate, 0.1)
  return data
}

const formatApiError = (e) => {
  const detail = e.response?.data?.detail
  if (Array.isArray(detail)) {
    return detail.map(item => {
      const loc = Array.isArray(item.loc) ? item.loc.join('.') : ''
      return [loc, item.msg].filter(Boolean).join(': ')
    }).join(' / ') || '保存に失敗しました'
  }
  if (typeof detail === 'string') return detail
  if (detail) return JSON.stringify(detail)
  return e.message || '保存に失敗しました'
}

const SORT_OPTIONS = { numeric: true, sensitivity: 'base' }

const compareProducts = (a, b) => {
  const sku = String(a.sku || '').localeCompare(String(b.sku || ''), 'ja', SORT_OPTIONS)
  if (sku) return sku
  const name = String(a.name || '').localeCompare(String(b.name || ''), 'ja', SORT_OPTIONS)
  if (name) return name
  return (a.id || 0) - (b.id || 0)
}

function calcProfit(p) {
  if (!p.selling_price || !p.price) return null
  const amazonFee = p.selling_price * (p.amazon_fee_rate ?? 0.1)
  const fbaFee = p.fba_fee ?? 0
  const profit = p.selling_price - p.price - amazonFee - fbaFee
  const rate = profit / p.selling_price
  return { profit: Math.round(profit), rate: (rate * 100).toFixed(1) }
}

export default function ProductsPage() {
  const qc = useQueryClient()
  const [modal, setModal] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState(EMPTY)
  const [initialForm, setInitialForm] = useState(EMPTY)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [supplierFilter, setSupplierFilter] = useState('')
  const [inlineEdit, setInlineEdit] = useState(null)
  const [refreshing, setRefreshing] = useState(false)
  const [hoveredImg, setHoveredImg] = useState(null) // { url, x, y }

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
    onError: (e) => setError(formatApiError(e)),
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
      const d = res.data
      alert(`更新完了！${d.updated}件を確認しました。\n価格取得: ${d.price_updated ?? '-'}件 / FBA手数料取得: ${d.fee_updated ?? '-'}件\n未取得: 価格${d.price_missing ?? 0}件・FBA${d.fee_missing ?? 0}件`)
      qc.invalidateQueries(['products'])
    } catch (e) {
      alert('更新失敗: ' + (e.response?.data?.detail || e.message))
    } finally {
      setRefreshing(false)
    }
  }

  const openNew = () => {
    const next = { ...EMPTY }
    setEditing(null)
    setForm(next)
    setInitialForm(next)
    setError('')
    setModal(true)
  }
  const openEdit = (p) => {
    const next = { ...EMPTY, ...p }
    setEditing(p)
    setForm(next)
    setInitialForm(next)
    setError('')
    setModal(true)
  }
  const closeModal = () => {
    setModal(false)
    setError('')
  }
  const hasUnsavedChanges = () => (
    JSON.stringify(buildFormData(form)) !== JSON.stringify(buildFormData(initialForm))
  )
  const handleModalClose = () => {
    if (save.isPending) return
    if (hasUnsavedChanges() && !confirm('保存されていない変更があります。閉じますか？')) return
    closeModal()
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    save.mutate(buildFormData(form))
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

  const toHalf = (s) => (s || '').replace(/[Ａ-Ｚａ-ｚ０-９]/g, c => String.fromCharCode(c.charCodeAt(0) - 0xFEE0))
  const normalize = (s) => toHalf(s).toLowerCase()
  const suppliers = [...new Set(products.map(p => p.supplier).filter(Boolean))].sort()
  const filteredProducts = products.filter(p => {
    if (supplierFilter && (p.supplier || '') !== supplierFilter) return false
    if (!search) return true
    const q = normalize(search)
    return normalize(p.sku).includes(q) || normalize(p.name).includes(q) ||
      (p.asin || '').toLowerCase().includes(q) || normalize(p.fnsku).includes(q)
  }).sort(compareProducts)

  // 最終更新日時（全商品で最新のもの）
  const lastUpdated = products
    .map(p => p.fees_updated_at)
    .filter(Boolean)
    .sort()
    .at(-1)

  if (isLoading) return <div className="loading">読み込み中...</div>

  return (
    <div>
      {hoveredImg && (
        <div style={{
          position: 'fixed',
          left: hoveredImg.x + 16,
          top: hoveredImg.y + 16,
          zIndex: 9999,
          pointerEvents: 'none',
          background: '#fff',
          border: '1px solid #ddd',
          borderRadius: 8,
          boxShadow: '0 4px 16px rgba(0,0,0,0.18)',
          padding: 6,
        }}>
          <img src={hoveredImg.url} alt="" referrerPolicy="no-referrer" style={{ width: 180, height: 180, objectFit: 'contain', display: 'block' }} />
        </div>
      )}
      <h1>🏷️ 商品マスタ</h1>
      <div className="top-actions">
        <button className="btn btn-primary" onClick={openNew}>＋ 商品を追加</button>
        <button className="btn btn-secondary" onClick={importFromFba} disabled={importing}>
          {importing ? 'インポート中...' : '📦 FBAから自動インポート'}
        </button>
        <button className="btn btn-secondary" onClick={handleRefreshFees} disabled={refreshing}>
          {refreshing ? '取得中...' : '💰 価格・手数料を更新'}
        </button>
        <a
          href={`${api.defaults.baseURL}/products/export/t4s-cost`}
          download="t4s_cost.xlsx"
          className="btn btn-secondary"
        >📥 T4S原価テンプレート</a>
        <span style={{ color: '#888', fontSize: 13 }}>
          {products.length}件登録済み
          {lastUpdated && (
            <span style={{ marginLeft: 8 }}>
              （最終取得: {new Date(lastUpdated).toLocaleDateString('ja-JP')}）
            </span>
          )}
        </span>
      </div>

      <div style={{ margin: '12px 0', display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <input
          type="text"
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="SKU・商品名・ASIN・FNSKUで絞り込み"
          style={{ padding: '8px 12px', width: 260, border: '1px solid #d1d5db', borderRadius: 6, fontSize: 14 }}
        />
        <select value={supplierFilter} onChange={e => setSupplierFilter(e.target.value)}
          style={{ padding: '8px 12px', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 14, width: 160 }}>
          <option value="">仕入れ先: すべて</option>
          {suppliers.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        {(search || supplierFilter) && <span style={{ color: '#888', fontSize: 13 }}>{filteredProducts.length}件</span>}
      </div>

      {filteredProducts.length === 0 ? (
        <div className="card empty-state">
          <div style={{ fontSize: 40 }}>🏷️</div>
          <p>商品が登録されていません。「＋ 商品を追加」から登録してください。</p>
        </div>
      ) : (
        <div className="card">
          <div className="sticky-table-wrap">
            <table className="sticky-table">
              <thead>
                <tr>
                  <th>SKU</th>
                  <th>商品名</th>
                  <th>仕様</th>
                  <th>お客様専用メモ</th>
                  <th style={{ textAlign: 'right' }}>仕入原価(円)</th>
                  <th style={{ textAlign: 'right' }}>販売価格(円)</th>
                  <th style={{ textAlign: 'right' }}>FBA手数料</th>
                  <th style={{ textAlign: 'right' }}>Amazon手数料率</th>
                  <th style={{ textAlign: 'right' }}>利益額</th>
                  <th style={{ textAlign: 'right' }}>利益率</th>
                  <th>備考</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {filteredProducts.map(p => {
                  const profit = calcProfit(p)
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
                            onMouseEnter={p.photo_url ? (e) => setHoveredImg({ url: p.photo_url, x: e.clientX, y: e.clientY }) : undefined}
                            onMouseMove={p.photo_url ? (e) => setHoveredImg(v => v ? { ...v, x: e.clientX, y: e.clientY } : null) : undefined}
                            onMouseLeave={p.photo_url ? () => setHoveredImg(null) : undefined}
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
                      <td style={{ maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 12 }} title={p.spec}>
                        {p.spec || <span style={{ color: '#bbb' }}>-</span>}
                      </td>
                      <td style={{ maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 12, color: '#666' }} title={p.customer_memo}>
                        {p.customer_memo || <span style={{ color: '#bbb' }}>-</span>}
                      </td>
                      <td style={{ textAlign: 'right' }}>{p.price ? `¥${Math.round(p.price).toLocaleString()}` : '-'}</td>
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
                      <td style={{ maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 12, color: '#666' }}
                          title={p.note}>
                        {p.note || ''}
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
        <div className="modal-overlay" onClick={e => e.target === e.currentTarget && handleModalClose()}>
          <div className="modal">
            <div className="modal-header">
              <h2>{editing ? '商品を編集' : '商品を追加'}</h2>
              <button className="modal-close" onClick={handleModalClose}>✕</button>
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
                  <label>仕入原価(円)※インボイスから自動計算</label>
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
                  <label>仕様（Excel出力用・色/サイズをまとめた表記）</label>
                  <input {...f('spec')} placeholder="例: 燕麦色、S 建议75-95斤" />
                </div>
                <div className="form-group" style={{ gridColumn: 'span 2' }}>
                  <label>お客様専用メモ（Excel出力用）</label>
                  <textarea {...f('customer_memo')} rows={2} style={{ resize: 'vertical' }} />
                </div>
                <div className="form-group" style={{ gridColumn: 'span 2' }}>
                  <label>備考</label>
                  <textarea {...f('note')} rows={2} style={{ resize: 'vertical' }} />
                </div>
              </div>
              {error && <p className="error-msg">{error}</p>}
              <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 8 }}>
                <button type="button" className="btn btn-secondary" onClick={handleModalClose}>キャンセル</button>
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
