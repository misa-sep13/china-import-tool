import { useState, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'

export default function RakutenStockPage() {
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [supplierFilter, setSupplierFilter] = useState('')
  const [importingStock, setImportingStock] = useState(false)
  const [importStockResult, setImportStockResult] = useState(null)
  const [ssSyncing, setSsSyncing] = useState(false)
  const [ssSyncResult, setSsSyncResult] = useState(null)
  // { [id]: { stock, inbound, standard_stock, selling_price, shipping_fee } }
  const [edits, setEdits] = useState({})
  const [saving, setSaving] = useState(false)

  const handleImportStock = async () => {
    if (!window.confirm('RMSから現在の在庫数を取得してDBに保存します。よろしいですか？')) return
    setImportingStock(true)
    setImportStockResult(null)
    try {
      const res = await api.post('/rakuten/rms/import-stock')
      setImportStockResult(res.data)
      qc.invalidateQueries(['rakuten-stock'])
      setEdits({})
    } catch (err) {
      setImportStockResult({ error: err.response?.data?.detail || '在庫取得エラーが発生しました' })
    } finally {
      setImportingStock(false)
    }
  }

  const handleSsSync = async () => {
    if (!window.confirm('直近のスーパーセール期間(3/6/9/12月 4日20時〜11日2時)の販売数をRMSから集計して保存します。よろしいですか？')) return
    setSsSyncing(true)
    setSsSyncResult(null)
    try {
      const start = await api.post('/rakuten/rms/ss-sync/start')
      const jobId = start.data.job_id
      // 完了までポーリング（最大3分）
      for (let i = 0; i < 90; i++) {
        await new Promise(r => setTimeout(r, 2000))
        const st = await api.get(`/rakuten/rms/sync/status/${jobId}`)
        if (st.data.status === 'done') {
          setSsSyncResult(st.data.result)
          qc.invalidateQueries(['rakuten-ss-sales'])
          break
        }
        if (st.data.status === 'error') {
          setSsSyncResult({ error: st.data.error || 'SS集計でエラーが発生しました' })
          break
        }
      }
    } catch (err) {
      setSsSyncResult({ error: err.response?.data?.detail || 'SS集計エラーが発生しました' })
    } finally {
      setSsSyncing(false)
    }
  }

  const { data: items = [], isLoading } = useQuery({
    queryKey: ['rakuten-stock'],
    queryFn: () => api.get('/rakuten/stock').then(r => r.data),
  })

  const { data: allProducts = [] } = useQuery({
    queryKey: ['rakuten-products'],
    queryFn: () => api.get('/rakuten/products').then(r => r.data),
  })

  const { data: settings } = useQuery({
    queryKey: ['rakuten-settings'],
    queryFn: () => api.get('/rakuten/settings').then(r => r.data),
  })

  const { data: ssSales } = useQuery({
    queryKey: ['rakuten-ss-sales'],
    queryFn: () => api.get('/rakuten/ss-sales').then(r => r.data),
  })
  const ssPeriod = ssSales?.period
  const ssMap = ssSales?.sales ?? {}

  const commissionRate = settings?.commission_rate ?? 0.09

  const internalSkus = new Set(allProducts.filter(p => p.is_component).map(p => p.sku))
  const parseComps = (p) => { try { return JSON.parse(p.set_components || '[]') } catch { return [] } }
  const compSkus = (p) => parseComps(p).map(c => c.sku).filter(Boolean)
  const isVariantChild = (p) => !p.is_component && compSkus(p).some(s => !internalSkus.has(s))

  const variantParentSkus = new Set(
    allProducts.filter(isVariantChild).flatMap(p => compSkus(p).filter(s => !internalSkus.has(s)))
  )
  const stockCompSkus = (p) => {
    try { return JSON.parse(p.set_components || '[]').map(c => c.sku).filter(Boolean) } catch { return [] }
  }
  const getVariantChildren = (sku) => items.filter(p => stockCompSkus(p).includes(sku))

  const suppliers = [...new Set(items.map(p => p.supplier).filter(Boolean))].sort()

  const searchMatch = (p) => {
    if (supplierFilter && (p.supplier || '') !== supplierFilter) return false
    if (!search) return true
    const normalize = (s) => (s || '').replace(/[Ａ-Ｚａ-ｚ０-９]/g, c => String.fromCharCode(c.charCodeAt(0) - 0xFEE0)).replace(/[\s　]/g, '').toLowerCase()
    const q = normalize(search)
    return normalize(p.sku).includes(q) || normalize(p.name).includes(q) || normalize(p.spec).includes(q) || normalize(p.rakuten_item_url || '').includes(q)
  }

  const childSkus = new Set(items.filter(p => stockCompSkus(p).some(s => !internalSkus.has(s))).map(p => p.sku))
  const parents = items.filter(p => variantParentSkus.has(p.sku) && searchMatch(p))
  const others  = items.filter(p => !variantParentSkus.has(p.sku) && !childSkus.has(p.sku) && searchMatch(p))
  const displayCount = parents.length + others.length

  const setEdit = useCallback((id, field, value) => {
    setEdits(prev => ({ ...prev, [id]: { ...prev[id], [field]: value } }))
  }, [])

  const dirtyCount = Object.keys(edits).length

  const handleSaveAll = async () => {
    if (dirtyCount === 0) return
    setSaving(true)
    try {
      const updates = Object.entries(edits).map(([id, vals]) => ({
        id: Number(id),
        ...(vals.stock !== undefined ? { stock: Number(vals.stock) } : {}),
        ...(vals.inbound !== undefined ? { inbound: Number(vals.inbound) } : {}),
        ...(vals.standard_stock !== undefined ? { standard_stock: Number(vals.standard_stock) } : {}),
      }))
      await api.post('/rakuten/products/bulk-update-stock', { updates })
      qc.invalidateQueries(['rakuten-stock'])
      setEdits({})
    } finally {
      setSaving(false)
    }
  }

  if (isLoading) return <div className="loading">読み込み中...</div>

  const rowProps = { commissionRate, edits, setEdit, ssMap }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
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
        <button className="btn" style={{ fontSize: 13 }} onClick={handleSsSync} disabled={ssSyncing}>
          {ssSyncing ? 'SS集計中...' : '🛒 SS販売数取得'}
        </button>
        {ssSyncResult && (
          <span style={{ fontSize: 12, color: ssSyncResult.error ? '#e53e3e' : '#9333ea' }}>
            {ssSyncResult.error || `SS(${ssSyncResult.period}) ${ssSyncResult.saved_products}件保存`}
          </span>
        )}
        <button
          className="btn btn-primary"
          style={{ fontSize: 13, marginLeft: 'auto', opacity: dirtyCount === 0 ? 0.4 : 1 }}
          onClick={handleSaveAll}
          disabled={dirtyCount === 0 || saving}
        >
          {saving ? '保存中...' : `💾 一括保存${dirtyCount > 0 ? `（${dirtyCount}件）` : ''}`}
        </button>
      </div>

      <div className="card" style={{ padding: '12px 16px', marginBottom: 16, display: 'flex', gap: 12, alignItems: 'center' }}>
        <input
          type="text" placeholder="SKU・商品名・仕様で絞り込み"
          value={search} onChange={e => setSearch(e.target.value)}
          style={{ width: 220, flex: '0 0 220px' }}
        />
        <select value={supplierFilter} onChange={e => setSupplierFilter(e.target.value)} style={{ width: 160, flex: '0 0 160px' }}>
          <option value="">仕入れ先: すべて</option>
          {suppliers.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <span style={{ fontSize: 12, color: '#6b7280' }}>{displayCount}件</span>
      </div>

      <div className="card" style={{ padding: 0, overflow: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: '#f0f2f8', borderBottom: '2px solid #e2e8f0' }}>
              {['SKU', '商品名', '仕様', 'お客様専用メモ', '仕入原価(元)', '販売価格(円)', '送料', '手数料', '利益額', '利益率', '実在庫', '輸送中', '規定在庫', '直近30日', '前30日', ssPeriod ? `SS(${ssPeriod})` : 'SS', '備考'].map(h => (
                <th key={h} style={{ padding: '10px 10px', textAlign: 'center', color: '#333', whiteSpace: 'nowrap', fontWeight: 700, fontSize: 12 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {displayCount === 0 && (
              <tr><td colSpan={17} style={{ textAlign: 'center', padding: 32, color: '#999' }}>商品がありません</td></tr>
            )}
            {parents.map(p => {
              const childList = getVariantChildren(p.sku).filter(searchMatch)
              return [
                <StockRow key={p.id} p={p} {...rowProps} />,
                ...childList.map(c => <StockRow key={c.id} p={c} isChild {...rowProps} />)
              ]
            })}
            {others.map(p => <StockRow key={p.id} p={p} {...rowProps} />)}
          </tbody>
        </table>
      </div>

      {/* フローティング保存ボタン（常時表示） */}
      <button
        onClick={handleSaveAll}
        disabled={dirtyCount === 0 || saving}
        style={{
          position: 'fixed', bottom: 32, right: 32,
          background: dirtyCount > 0 ? '#2563eb' : '#94a3b8', color: '#fff',
          border: 'none', borderRadius: 32,
          padding: '14px 28px', fontSize: 15, fontWeight: 700,
          boxShadow: '0 4px 16px rgba(0,0,0,0.2)',
          cursor: (dirtyCount === 0 || saving) ? 'not-allowed' : 'pointer',
          zIndex: 1000,
          transition: 'background 0.2s',
        }}
      >
        {saving ? '保存中...' : dirtyCount > 0 ? `💾 保存（${dirtyCount}件）` : '💾 保存'}
      </button>
    </div>
  )
}

function StockRow({ p, commissionRate, edits, setEdit, isChild, ssMap }) {
  const e = edits[p.id] || {}
  const sp = e.selling_price !== undefined ? (e.selling_price !== '' ? Number(e.selling_price) : null) : p.selling_price
  const shippingFee = e.shipping_fee !== undefined ? Number(e.shipping_fee) : (p.shipping_fee ?? 180)
  const stock = e.stock !== undefined ? e.stock : (p.stock ?? 0)
  const inbound = e.inbound !== undefined ? e.inbound : (p.inbound ?? 0)
  const standardStock = e.standard_stock !== undefined ? e.standard_stock : (p.standard_stock ?? 0)
  const isDirty = !!edits[p.id]

  const commission = sp ? Math.round(sp * commissionRate) : null
  const cost = p.cost_jpy || 0
  const profit = (sp && commission !== null) ? Math.round(sp - cost - commission - shippingFee) : null
  const profitRate = (sp && profit !== null) ? (profit / sp * 100).toFixed(1) : null
  const rowBg = isDirty ? '#fffbeb' : isChild ? '#f8faff' : '#fff'

  // 数値入力欄にフォーカスしたとき、中身が0なら全選択して上書き入力できるようにする
  // （0が残って「030」のように入力されるのを防ぐ）
  const selectIfZero = (ev) => {
    if (Number(ev.target.value) === 0) ev.target.select()
  }

  return (
    <tr style={{ borderBottom: '1px solid #e5e7eb', background: rowBg }}>
      <td style={{ padding: '8px 10px', paddingLeft: isChild ? 26 : 10, fontFamily: 'monospace', fontSize: 12, color: '#666', whiteSpace: 'nowrap' }}>
        {isChild && <span style={{ color: '#cbd5e1', marginRight: 4 }}>└</span>}
        {p.sku}
        {isDirty && <span style={{ color: '#d97706', marginLeft: 4, fontSize: 10 }}>●</span>}
      </td>
      <td style={{ padding: '8px 10px', minWidth: 140, color: isChild ? '#555' : '#1a1a2e' }}>{p.name || '—'}</td>
      <td style={{ padding: '8px 10px', color: '#666', fontSize: 12 }}>{p.spec || '—'}</td>
      <td style={{ padding: '8px 10px', color: '#666', fontSize: 12, maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.customer_memo || '—'}</td>
      <td style={{ padding: '8px 10px', textAlign: 'right', color: '#666' }}>{cost ? `¥${cost}` : '—'}</td>
      <td style={{ padding: '8px 10px', textAlign: 'right' }}>
        <span style={{ fontWeight: 600 }}>{sp ? `¥${sp.toLocaleString()}` : '—'}</span>
      </td>
      <td style={{ padding: '8px 10px', textAlign: 'right', color: '#666' }}>{`¥${shippingFee}`}</td>
      <td style={{ padding: '8px 10px', textAlign: 'right', color: '#666' }}>{commission !== null ? `¥${commission.toLocaleString()}` : '—'}</td>
      <td style={{ padding: '8px 10px', textAlign: 'right', fontWeight: 600, color: profit > 0 ? '#16a34a' : profit < 0 ? '#dc2626' : '#666' }}>
        {profit !== null ? `¥${profit.toLocaleString()}` : '—'}
      </td>
      <td style={{ padding: '8px 10px', textAlign: 'right', fontWeight: 600, color: profitRate > 30 ? '#16a34a' : profitRate > 0 ? '#d97706' : '#dc2626' }}>
        {profitRate !== null ? `${profitRate}%` : '—'}
      </td>
      <td style={{ padding: '4px 6px', textAlign: 'center' }}>
        <input
          type="number"
          value={stock}
          onFocus={selectIfZero}
          onChange={e => setEdit(p.id, 'stock', e.target.value)}
          style={{ width: 60, textAlign: 'center', border: isDirty ? '1px solid #d97706' : '1px solid #e2e8f0', borderRadius: 4, padding: '3px 4px', fontWeight: 600 }}
        />
      </td>
      <td style={{ padding: '4px 6px', textAlign: 'center' }}>
        <input
          type="number"
          value={inbound}
          onFocus={selectIfZero}
          onChange={e => setEdit(p.id, 'inbound', e.target.value)}
          style={{ width: 60, textAlign: 'center', border: '1px solid #e2e8f0', borderRadius: 4, padding: '3px 4px' }}
        />
      </td>
      <td style={{ padding: '4px 6px', textAlign: 'center' }}>
        <input
          type="number"
          value={standardStock}
          onFocus={selectIfZero}
          onChange={e => setEdit(p.id, 'standard_stock', e.target.value)}
          style={{ width: 60, textAlign: 'center', border: '1px solid #e2e8f0', borderRadius: 4, padding: '3px 4px' }}
        />
      </td>
      <td style={{ padding: '8px 10px', textAlign: 'center', color: '#2563eb', fontWeight: 600 }}>{p.sales_30_recent}</td>
      <td style={{ padding: '8px 10px', textAlign: 'center', color: '#666' }}>{p.sales_30_prev}</td>
      <td style={{ padding: '8px 10px', textAlign: 'center', color: '#9333ea', fontWeight: 600 }}>
        {ssMap && ssMap[p.sku] != null ? ssMap[p.sku] : '—'}
      </td>
      <td style={{ padding: '8px 10px', color: '#666', fontSize: 12, maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.notes || '—'}</td>
    </tr>
  )
}
