import { useState, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'

const EMPTY = {
  sku: '', name: '', jan_code: '', spec: '', buy_url: '', price: '',
  set_size: 1, rakuten_item_url: '', rakuten_sku_id: '', supplier: '',
  standard_stock: 0, stock: 0, inbound: 0,
  sales_30_recent: 0, sales_30_prev: 0,
  customer_memo: '', notes: '', memo: '',
  set_components: '', is_component: false, is_active: true,
}

const BASE_URL = api.defaults.baseURL || ''

export default function RakutenProductsPage() {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState(EMPTY)
  const [search, setSearch] = useState('')
  const [showComponents, setShowComponents] = useState(false)
  const [importResult, setImportResult] = useState(null)
  const [importing, setImporting] = useState(false)
  const [syncingPrices, setSyncingPrices] = useState(false)
  const [syncPriceResult, setSyncPriceResult] = useState(null)
  const [compTab, setCompTab] = useState({})  // {id: bool} セット構成展開
  const fileRef = useRef(null)

  const { data: products = [], isLoading } = useQuery({
    queryKey: ['rakuten-products'],
    queryFn: () => api.get('/rakuten/products').then(r => r.data),
  })

  const { data: settings } = useQuery({
    queryKey: ['rakuten-settings'],
    queryFn: () => api.get('/rakuten/settings').then(r => r.data),
  })
  const commissionRate = settings?.commission_rate ?? 0.09

  const saveMutation = useMutation({
    mutationFn: (d) => editing === 'new'
      ? api.post('/rakuten/products', d)
      : api.put(`/rakuten/products/${editing.id}`, d),
    onSuccess: () => {
      qc.invalidateQueries(['rakuten-products'])
      qc.invalidateQueries(['rakuten-recommendations'])
      setEditing(null)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id) => api.delete(`/rakuten/products/${id}`),
    onSuccess: () => {
      qc.invalidateQueries(['rakuten-products'])
      qc.invalidateQueries(['rakuten-recommendations'])
    },
  })

  const openNew = () => { setForm(EMPTY); setEditing('new') }
  const openEdit = (p) => { setForm({ ...p }); setEditing(p) }

  const f = (k, type = 'text') => ({
    value: form[k] ?? '',
    onChange: e => setForm(prev => ({ ...prev, [k]: type === 'number' ? Number(e.target.value) : e.target.value }))
  })

  const handleSyncPrices = async () => {
    if (!window.confirm('RMS APIから売価を取得して更新します。よろしいですか？')) return
    setSyncingPrices(true)
    setSyncPriceResult(null)
    try {
      const res = await api.post('/rakuten/rms/sync-prices')
      // statusエンドポイントがある場合はポーリング、ない場合は即完了扱い
      if (res.data?.message?.includes('バックグラウンド')) {
        for (let i = 0; i < 60; i++) {
          await new Promise(r => setTimeout(r, 2000))
          try {
            const status = await api.get('/rakuten/rms/sync-prices/status')
            if (!status.data.running && status.data.result) {
              setSyncPriceResult(status.data.result)
              qc.invalidateQueries(['rakuten-products'])
              return
            }
          } catch { /* statusエンドポイントがない古いバージョンは無視 */ }
        }
        setSyncPriceResult({ error: 'タイムアウト' })
      } else {
        setSyncPriceResult(res.data)
        qc.invalidateQueries(['rakuten-products'])
      }
    } catch (err) {
      setSyncPriceResult({ error: err.response?.data?.detail || '売価同期エラーが発生しました' })
    } finally {
      setSyncingPrices(false)
    }
  }

  const handleImport = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setImporting(true)
    setImportResult(null)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await api.post('/rakuten/products/csv/import', fd, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      setImportResult(res.data)
      qc.invalidateQueries(['rakuten-products'])
      qc.invalidateQueries(['rakuten-recommendations'])
    } catch (err) {
      setImportResult({ error: err.response?.data?.detail || 'インポートエラーが発生しました' })
    } finally {
      setImporting(false)
      e.target.value = ''
    }
  }

  // セット構成をパース
  const parseComponents = (json) => {
    try { return JSON.parse(json || '[]') } catch { return [] }
  }

  // 単品（親）・セット（子）・スタンドアロン に分類
  const singles    = products.filter(p => p.is_component)
  const sets       = products.filter(p => !p.is_component && p.set_components && p.set_components !== '[]')
  const standalone = products.filter(p => !p.is_component && (!p.set_components || p.set_components === '[]'))

  // 単品SKUに紐づくセット一覧を返す
  const getSetsForSingle = (sku) =>
    sets.filter(s => {
      try { return JSON.parse(s.set_components || '[]').some(c => c.sku === sku) }
      catch { return false }
    })

  const toHalf = (s) => s.replace(/[Ａ-Ｚａ-ｚ０-９]/g, c => String.fromCharCode(c.charCodeAt(0) - 0xFEE0))
  const normalize = (s) => toHalf(s || '').toLowerCase()

  const searchMatch = (p) => {
    if (!search) return true
    const q = normalize(search)
    return (
      normalize(p.sku).includes(q) ||
      normalize(p.name).includes(q) ||
      (p.jan_code || '').includes(search) ||
      normalize(p.rakuten_sku_id).includes(q)
    )
  }

  const filteredSingles    = singles.filter(searchMatch)
  const filteredStandalone = standalone.filter(searchMatch)
  const filtered = [] // 旧変数との互換用（使わない）

  if (isLoading) return <div className="loading">読み込み中...</div>

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24, flexWrap: 'wrap' }}>
        <h1>🛒 楽天 商品マスタ</h1>
        <button className="btn btn-primary" onClick={openNew}>+ 商品追加</button>
        <a href={`${BASE_URL}/rakuten/products/csv/template`} download className="btn" style={{ fontSize: 13, textDecoration: 'none' }}>
          📥 CSVテンプレート
        </a>
        <button className="btn" style={{ fontSize: 13 }} onClick={() => fileRef.current?.click()} disabled={importing}>
          {importing ? '取り込み中...' : '📤 CSVインポート'}
        </button>
        <input ref={fileRef} type="file" accept=".csv" style={{ display: 'none' }} onChange={handleImport} />
        <a href={`${BASE_URL}/rakuten/products/csv/export`} download className="btn" style={{ fontSize: 13, textDecoration: 'none' }}>
          📊 CSV書き出し
        </a>
        <button className="btn" style={{ fontSize: 13 }} onClick={handleSyncPrices} disabled={syncingPrices}>
          {syncingPrices ? '取得中...' : '💰 売価同期(RMS)'}
        </button>
        {syncPriceResult && (
          <span style={{ fontSize: 12, color: syncPriceResult.error ? '#e53e3e' : '#38a169' }}>
            {syncPriceResult.error || `${syncPriceResult.updated_products}件更新`}
          </span>
        )}
      </div>

      {importResult && (
        <div style={{
          background: importResult.error ? '#2d1b1b' : '#1b2d1b',
          border: `1px solid ${importResult.error ? '#f87171' : '#4ade80'}`,
          borderRadius: 8, padding: '12px 16px', marginBottom: 16, fontSize: 13,
        }}>
          {importResult.error ? (
            <span style={{ color: '#f87171' }}>❌ {importResult.error}</span>
          ) : (
            <div>
              <span style={{ color: '#4ade80', fontWeight: 700 }}>
                ✅ 新規追加: {importResult.created}件　更新: {importResult.updated}件　スキップ: {importResult.skipped}件
              </span>
              {importResult.errors?.length > 0 && (
                <ul style={{ color: '#fcd34d', margin: '8px 0 0', paddingLeft: 16 }}>
                  {importResult.errors.map((e, i) => <li key={i}>{e}</li>)}
                </ul>
              )}
            </div>
          )}
        </div>
      )}

      {/* 検索 */}
      <div className="card" style={{ padding: '12px 16px', marginBottom: 16, display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <input
          type="text" placeholder="SKU・商品名・JANコード・楽天SKUで絞り込み"
          value={search} onChange={e => setSearch(e.target.value)}
          style={{ width: '100%', maxWidth: 420 }}
        />
        <span style={{ fontSize: 12, color: '#6b7280' }}>
          単品 {filteredSingles.length}件 / その他 {filteredStandalone.length}件
          {sets.length > 0 && ` / バリエーション ${sets.length}件（単品から展開）`}
        </span>
      </div>

      {/* 商品テーブル */}
      <div className="card" style={{ padding: 0, overflow: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: '#f0f2f8', borderBottom: '2px solid #e2e8f0' }}>
              {[
                ['SKU管理番号', null], ['商品名 / 仕様', null], ['お客様専用メモ', 90],
                ['仕入原価(円)', null], ['販売価格(円)', null], ['手数料率', null],
                ['利益額', null], ['利益率', null], ['備考', 90], ['操作', null]
              ].map(([h, w]) => (
                <th key={h} style={{ padding: '10px 12px', textAlign: 'center', color: '#333', whiteSpace: 'nowrap', fontWeight: 700, ...(w ? { width: w, maxWidth: w } : {}) }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filteredSingles.length === 0 && filteredStandalone.length === 0 && (
              <tr><td colSpan={10} style={{ textAlign: 'center', padding: 32, color: '#999' }}>商品がありません</td></tr>
            )}

            {/* ① 単品（親） → クリックでバリエーション展開 */}
            {filteredSingles.map(p => {
              const expanded = !!compTab[p.id]
              const children = getSetsForSingle(p.sku)
              return (
                <ProductRow
                  key={p.id}
                  p={p}
                  commissionRate={commissionRate}
                  expanded={expanded}
                  childCount={children.length}
                  onToggle={() => setCompTab(prev => ({ ...prev, [p.id]: !prev[p.id] }))}
                  onEdit={openEdit}
                  onDelete={(p) => { if (confirm(`${p.name || p.sku} を削除しますか？`)) deleteMutation.mutate(p.id) }}
                  isSingle={true}
                >
                  {/* バリエーション子行 */}
                  {expanded && children.map(child => (
                    <ProductRow
                      key={child.id}
                      p={child}
                      commissionRate={commissionRate}
                      onEdit={openEdit}
                      onDelete={(p) => { if (confirm(`${p.name || p.sku} を削除しますか？`)) deleteMutation.mutate(p.id) }}
                      isChild={true}
                    />
                  ))}
                </ProductRow>
              )
            })}

            {/* ② スタンドアロン商品（セット構成なし・単品フラグなし） */}
            {filteredStandalone.map(p => (
              <ProductRow
                key={p.id}
                p={p}
                commissionRate={commissionRate}
                onEdit={openEdit}
                onDelete={(p) => { if (confirm(`${p.name || p.sku} を削除しますか？`)) deleteMutation.mutate(p.id) }}
              />
            ))}
          </tbody>
        </table>
      </div>

      {/* 編集モーダル */}
      {editing && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
          <div style={{ background: '#fff', color: '#1a1a2e', borderRadius: 12, padding: 32, width: 620, maxHeight: '90vh', overflowY: 'auto', boxShadow: '0 8px 40px rgba(0,0,0,0.25)' }}>
            <h2 style={{ marginBottom: 20 }}>{editing === 'new' ? '商品追加' : '商品編集'}</h2>

            {/* 基本情報 */}
            <h3 style={{ fontSize: 13, color: '#64748b', marginBottom: 10 }}>基本情報</h3>
            <div className="form-grid" style={{ gridTemplateColumns: '1fr 1fr' }}>
              <div className="form-group" style={{ gridColumn: '1 / -1' }}>
                <label>SKU管理番号<span style={{ color: '#f87171' }}> *</span></label>
                <input {...f('sku')} placeholder="例: y76_b-b" />
              </div>
              <div className="form-group" style={{ gridColumn: '1 / -1' }}>
                <label>商品名</label>
                <input {...f('name')} placeholder="例: ○○ポーチ" />
              </div>
              <div className="form-group">
                <label>システム連携用SKU番号（全角48文字）</label>
                <input {...f('spec')} placeholder="例: 厚手4足セット　ブラック" />
              </div>
              <div className="form-group">
                <label>JANコード</label>
                <input {...f('jan_code')} placeholder="例: 4900000000000" />
              </div>
              <div className="form-group">
                <label>セット入数</label>
                <input type="number" min={1} {...f('set_size', 'number')} />
              </div>
              <div className="form-group">
                <label>仕入先</label>
                <input {...f('supplier')} placeholder="例: タオタロウ" />
              </div>
              <div className="form-group" style={{ gridColumn: '1 / -1' }}>
                <label>仕入れURL（複数ある場合は1行に1URL）</label>
                <textarea {...f('buy_url')} placeholder="https://..." rows={3} style={{ fontFamily: 'monospace', fontSize: 12 }} />
              </div>
              <div className="form-group">
                <label>仕入れ値（元）</label>
                <input type="number" step="0.01" {...f('price', 'number')} />
              </div>
              <div className="form-group">
                <label>販売価格（円）</label>
                <input type="number" step="1" {...f('selling_price', 'number')} />
              </div>
              <div className="form-group">
                <label>お客様専用メモ（タオタロウG列）</label>
                <textarea value={form.customer_memo || ''} onChange={e => setForm(p => ({ ...p, customer_memo: e.target.value }))} rows={2} />
              </div>
              <div className="form-group">
                <label>備考（タオタロウH列）</label>
                <textarea value={form.notes || ''} onChange={e => setForm(p => ({ ...p, notes: e.target.value }))} rows={2} />
              </div>
            </div>

            {/* 楽天管理情報 */}
            <div style={{ borderTop: '1px solid #e2e8f0', margin: '16px 0', paddingTop: 14 }}>
              <h3 style={{ fontSize: 13, color: '#64748b', marginBottom: 10 }}>🛒 楽天管理情報</h3>
              <div className="form-grid" style={{ gridTemplateColumns: '1fr 1fr' }}>
                <div className="form-group">
                  <label>規定在庫数</label>
                  <input type="number" min={0} {...f('standard_stock', 'number')} />
                </div>
              </div>
            </div>

            {/* 在庫・販売実績 */}
            <div style={{ borderTop: '1px solid #e2e8f0', margin: '0 0 16px', paddingTop: 14 }}>
              <h3 style={{ fontSize: 13, color: '#64748b', marginBottom: 10 }}>📦 在庫 / 販売実績</h3>
              <div className="form-grid" style={{ gridTemplateColumns: '1fr 1fr' }}>
                <div className="form-group">
                  <label>実在庫（手持ち）</label>
                  <input type="number" min={0} {...f('stock', 'number')} />
                </div>
                <div className="form-group">
                  <label>輸送中</label>
                  <input type="number" min={0} {...f('inbound', 'number')} />
                </div>
                <div className="form-group">
                  <label>直近30日の販売数</label>
                  <input type="number" min={0} {...f('sales_30_recent', 'number')} />
                </div>
                <div className="form-group">
                  <label>60日前〜31日前の販売数</label>
                  <input type="number" min={0} {...f('sales_30_prev', 'number')} />
                </div>
              </div>
            </div>

            {/* 内部メモ */}
            <div style={{ borderTop: '1px solid #e2e8f0', margin: '0 0 16px', paddingTop: 14 }}>
              <div className="form-group">
                <label>内部メモ</label>
                <textarea value={form.memo || ''} onChange={e => setForm(p => ({ ...p, memo: e.target.value }))} rows={2} />
              </div>
              <div style={{ marginTop: 12 }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13 }}>
                  <input
                    type="checkbox"
                    checked={!!form.is_component}
                    onChange={e => setForm(p => ({ ...p, is_component: e.target.checked }))}
                    style={{ width: 'auto', accentColor: '#f59e0b' }}
                  />
                  <span>🔩 単品フラグ（セット構成用の内部管理商品 — 一覧では非表示）</span>
                </label>
              </div>
            </div>

            {/* セット構成（単品管理） */}
            <div style={{ borderTop: '1px solid #e2e8f0', margin: '0 0 16px', paddingTop: 14 }}>
              <h3 style={{ fontSize: 13, color: '#64748b', marginBottom: 4 }}>🔗 セット構成（単品管理）</h3>
              <p style={{ fontSize: 12, color: '#475569', marginBottom: 10 }}>
                セット商品の場合、構成する単品SKUと数量をJSON形式で入力します。
              </p>
              <SetComponentsEditor
                value={form.set_components || ''}
                onChange={v => setForm(p => ({ ...p, set_components: v }))}
                allProducts={products}
              />
            </div>

            <div style={{ display: 'flex', gap: 12, marginTop: 8 }}>
              <button
                className="btn btn-primary"
                disabled={!form.sku || saveMutation.isPending}
                onClick={() => saveMutation.mutate(form)}
              >
                {saveMutation.isPending ? '保存中...' : '💾 保存'}
              </button>
              <button className="btn" onClick={() => setEditing(null)}>キャンセル</button>
            </div>
            {saveMutation.isError && (
              <div style={{ color: '#f87171', fontSize: 13, marginTop: 8 }}>
                {saveMutation.error?.response?.data?.detail || 'エラーが発生しました'}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// 仕入れURL複数対応：改行区切りで複数URLを保持。nameをクリッカブルにする
function BuyUrlLinks({ buyUrl, name }) {
  const urls = (buyUrl || '').split('\n').map(u => u.trim()).filter(Boolean)

  if (urls.length === 0) {
    return <span style={{ color: '#1a1a2e', fontWeight: 500 }}>{name}</span>
  }

  const openAll = () => urls.forEach(url => window.open(url, '_blank'))

  if (urls.length === 1) {
    return (
      <a href={urls[0]} target="_blank" rel="noreferrer"
        style={{ color: '#1a1a2e', fontWeight: 500, textDecoration: 'none', borderBottom: '1px dashed #94a3b8' }}>
        {name}
      </a>
    )
  }

  return (
    <span
      onClick={openAll}
      style={{ color: '#1a1a2e', fontWeight: 500, cursor: 'pointer', borderBottom: '1px dashed #94a3b8' }}>
      {name}
    </span>
  )
}

// 商品行コンポーネント
function ProductRow({ p, commissionRate = 0.09, expanded, childCount, onToggle, onEdit, onDelete, isSingle, isChild, children }) {
  const rowBg = isChild ? '#f8faff' : '#ffffff'
  const indent = isChild ? 32 : 0

  const shippingFee = p.shipping_fee ?? 180
  const commission = p.selling_price ? p.selling_price * commissionRate : null
  const profit = (p.selling_price != null && p.cost_jpy != null) ? p.selling_price - p.cost_jpy - (p.selling_price * commissionRate) - shippingFee : null
  const profitRate = (profit != null && p.selling_price) ? profit / p.selling_price : null

  return (
    <>
      <tr style={{ borderBottom: '1px solid #e5e7eb', background: rowBg }}>
        <td style={{ padding: `10px 12px 10px ${12 + indent}px`, fontFamily: 'monospace', whiteSpace: 'nowrap', fontSize: 12, color: '#666' }}>
          {isChild && <span style={{ color: '#ccc', marginRight: 6 }}>└</span>}
          {p.sku}
          {isSingle && (
            <span style={{ display: 'block', fontSize: 10, background: '#fef3c7', color: '#92400e', borderRadius: 4, padding: '1px 5px', marginTop: 2, width: 'fit-content', border: '1px solid #fbbf24' }}>単品</span>
          )}
        </td>
        <td style={{ padding: '10px 12px', minWidth: 140 }}>
          <BuyUrlLinks buyUrl={p.buy_url} name={p.name || '—'} />
          {p.spec && <div style={{ color: '#888', fontSize: 11 }}>{p.spec}</div>}
        </td>
        <td style={{ padding: '10px 12px', width: 90, maxWidth: 90, overflow: 'hidden', fontSize: 12, color: '#475569' }}>
          {p.customer_memo
            ? <span title={p.customer_memo} style={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', cursor: 'default' }}>{p.customer_memo}</span>
            : '—'}
        </td>
        <td style={{ padding: '10px 12px', textAlign: 'right', color: '#1a1a2e' }}>
          {p.cost_jpy != null ? `¥${p.cost_jpy.toLocaleString()}` : '—'}
        </td>
        <td style={{ padding: '10px 12px', textAlign: 'right', color: '#1a1a2e', fontWeight: 600 }}>
          {p.selling_price ? `¥${p.selling_price.toLocaleString()}` : '—'}
        </td>
        <td style={{ padding: '10px 12px', textAlign: 'center', color: '#666' }}>
          {(commissionRate * 100).toFixed(0)}%
        </td>
        <td style={{ padding: '10px 12px', textAlign: 'right', color: profit != null ? (profit >= 0 ? '#16a34a' : '#dc2626') : '#999', fontWeight: 600 }}>
          {profit != null ? `¥${Math.round(profit).toLocaleString()}` : '—'}
        </td>
        <td style={{ padding: '10px 12px', textAlign: 'right', color: profitRate != null ? (profitRate >= 0.15 ? '#16a34a' : profitRate >= 0 ? '#ca8a04' : '#dc2626') : '#999' }}>
          {profitRate != null ? `${(profitRate * 100).toFixed(1)}%` : '—'}
        </td>
        <td style={{ padding: '10px 12px', width: 90, maxWidth: 90, overflow: 'hidden', fontSize: 12, color: '#475569' }}>
          {p.notes
            ? <span title={p.notes} style={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', cursor: 'default' }}>{p.notes}</span>
            : '—'}
        </td>
        <td style={{ padding: '10px 12px', whiteSpace: 'nowrap' }}>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            {isSingle && childCount > 0 && (
              <button
                className="btn"
                style={{ fontSize: 11, padding: '3px 8px', background: expanded ? '#dbeafe' : '#f1f5f9', color: '#1e40af', border: `1px solid ${expanded ? '#93c5fd' : '#e2e8f0'}`, whiteSpace: 'nowrap' }}
                onClick={onToggle}
              >
                {expanded ? '▲' : '▼'} {childCount}件
              </button>
            )}
            <button className="btn" style={{ fontSize: 12, padding: '3px 10px' }} onClick={() => onEdit(p)}>編集</button>
            <button
              className="btn" style={{ fontSize: 12, padding: '3px 10px', color: '#dc2626' }}
              onClick={() => onDelete(p)}
            >削除</button>
          </div>
        </td>
      </tr>
      {children}
    </>
  )
}

// セット構成エディタコンポーネント
function SetComponentsEditor({ value, onChange, allProducts }) {
  const parse = (v) => { try { return JSON.parse(v || '[]') } catch { return [] } }
  const items = parse(value)

  const update = (newItems) => onChange(JSON.stringify(newItems))

  const addRow = () => update([...items, { sku: '', qty: 1 }])
  const removeRow = (i) => update(items.filter((_, idx) => idx !== i))
  const updateRow = (i, field, val) => {
    const next = items.map((item, idx) => idx === i ? { ...item, [field]: val } : item)
    update(next)
  }

  return (
    <div>
      {items.map((item, i) => (
        <div key={i} style={{ display: 'flex', gap: 8, marginBottom: 6, alignItems: 'center' }}>
          <select
            value={item.sku}
            onChange={e => updateRow(i, 'sku', e.target.value)}
            style={{ flex: 2, padding: '6px 8px', fontSize: 13, background: '#0f172a', color: '#e2e8f0', border: '1px solid #374151', borderRadius: 6 }}
          >
            <option value="">— 商品を選択 —</option>
            {allProducts.map(p => (
              <option key={p.id} value={p.sku}>
                {p.sku}{p.spec ? ` [${p.spec}]` : ''}{p.name ? ` - ${p.name}` : ''}
              </option>
            ))}
          </select>
          <input
            type="number" min={1} value={item.qty}
            onChange={e => updateRow(i, 'qty', Number(e.target.value))}
            style={{ width: 60, textAlign: 'center' }}
            placeholder="数量"
          />
          <span style={{ color: '#64748b', fontSize: 12 }}>個</span>
          <button className="btn" style={{ fontSize: 12, padding: '3px 8px', color: '#f87171' }} onClick={() => removeRow(i)}>✕</button>
        </div>
      ))}
      <button className="btn" style={{ fontSize: 12, marginTop: 4 }} onClick={addRow}>+ 単品を追加</button>
    </div>
  )
}
