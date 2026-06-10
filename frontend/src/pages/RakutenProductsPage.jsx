import { useState, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'

const EMPTY = {
  sku: '', name: '', jan_code: '', spec: '', buy_url: '', price: '',
  set_size: 1, rakuten_item_url: '', rakuten_sku_id: '', supplier: '',
  standard_stock: 0, stock: 0, inbound: 0,
  sales_30_recent: 0, sales_30_prev: 0,
  customer_memo: '', notes: '', memo: '',
  set_components: '', is_active: true,
}

const BASE_URL = api.defaults.baseURL || ''

export default function RakutenProductsPage() {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState(EMPTY)
  const [search, setSearch] = useState('')
  const [importResult, setImportResult] = useState(null)
  const [importing, setImporting] = useState(false)
  const [compTab, setCompTab] = useState({})  // {id: bool} セット構成展開
  const fileRef = useRef(null)

  const { data: products = [], isLoading } = useQuery({
    queryKey: ['rakuten-products'],
    queryFn: () => api.get('/rakuten/products').then(r => r.data),
  })

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

  const filtered = products.filter(p =>
    !search ||
    (p.sku || '').toLowerCase().includes(search.toLowerCase()) ||
    (p.name || '').toLowerCase().includes(search.toLowerCase()) ||
    (p.jan_code || '').includes(search) ||
    (p.rakuten_sku_id || '').includes(search)
  )

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
      <div className="card" style={{ padding: '12px 16px', marginBottom: 16 }}>
        <input
          type="text" placeholder="SKU・商品名・JANコード・楽天SKUで絞り込み"
          value={search} onChange={e => setSearch(e.target.value)}
          style={{ width: '100%', maxWidth: 420 }}
        />
      </div>

      {/* 商品テーブル */}
      <div className="card" style={{ padding: 0, overflow: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: '#1e2433', borderBottom: '2px solid #2d3748' }}>
              {['管理番号（URL）', '商品名 / システム連携SKU', '楽天SKU', '仕入先', '実在庫', '輸送中', '規定在庫', '直近30日', '前30日', '操作'].map(h => (
                <th key={h} style={{ padding: '10px 12px', textAlign: 'center', color: '#94a3b8', whiteSpace: 'nowrap' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr><td colSpan={10} style={{ textAlign: 'center', padding: 32, color: '#64748b' }}>商品がありません</td></tr>
            )}
            {filtered.map(p => {
              const comps = parseComponents(p.set_components)
              return (
                <>
                  <tr key={p.id} style={{ borderBottom: comps.length > 0 ? 'none' : '1px solid #2d3748' }}>
                    <td style={{ padding: '10px 12px', color: '#94a3b8', fontFamily: 'monospace', whiteSpace: 'nowrap', fontSize: 11 }}>{p.sku}</td>
                    <td style={{ padding: '10px 12px', minWidth: 160 }}>
                      <div style={{ color: '#e2e8f0', fontWeight: 600 }}>{p.name || '—'}</div>
                      {p.spec && <div style={{ color: '#64748b', fontSize: 11 }}>🔗 {p.spec}</div>}
                      {p.buy_url && <a href={p.buy_url} target="_blank" rel="noreferrer" style={{ fontSize: 11, color: '#60a5fa' }}>仕入れURL</a>}
                    </td>
                    <td style={{ padding: '10px 12px', textAlign: 'center', color: '#94a3b8', fontFamily: 'monospace', fontSize: 12 }}>{p.rakuten_sku_id || '—'}</td>
                    <td style={{ padding: '10px 12px', textAlign: 'center', color: '#94a3b8' }}>{p.supplier || '—'}</td>
                    <td style={{ padding: '10px 12px', textAlign: 'center', fontWeight: 700, color: '#e2e8f0' }}>{p.stock}</td>
                    <td style={{ padding: '10px 12px', textAlign: 'center', color: '#94a3b8' }}>{p.inbound}</td>
                    <td style={{ padding: '10px 12px', textAlign: 'center', color: '#94a3b8' }}>{p.standard_stock}</td>
                    <td style={{ padding: '10px 12px', textAlign: 'center', color: '#60a5fa', fontWeight: 600 }}>{p.sales_30_recent}</td>
                    <td style={{ padding: '10px 12px', textAlign: 'center', color: '#94a3b8' }}>{p.sales_30_prev}</td>
                    <td style={{ padding: '10px 12px', whiteSpace: 'nowrap' }}>
                      <div style={{ display: 'flex', gap: 6 }}>
                        <button className="btn" style={{ fontSize: 12, padding: '3px 10px' }} onClick={() => openEdit(p)}>編集</button>
                        <button
                          className="btn" style={{ fontSize: 12, padding: '3px 10px', color: '#f87171' }}
                          onClick={() => { if (confirm(`${p.name || p.sku} を削除しますか？`)) deleteMutation.mutate(p.id) }}
                        >削除</button>
                      </div>
                    </td>
                  </tr>
                  {/* セット構成（単品）展開表示 */}
                  {comps.length > 0 && (
                    <tr key={`${p.id}-comp`} style={{ borderBottom: '1px solid #2d3748', background: '#0f172a' }}>
                      <td colSpan={10} style={{ padding: '6px 24px 10px' }}>
                        <span style={{ fontSize: 11, color: '#475569', marginRight: 8 }}>📦 セット構成:</span>
                        {comps.map((c, i) => (
                          <span key={i} style={{ fontSize: 11, background: '#1e2433', borderRadius: 4, padding: '2px 8px', marginRight: 6, color: '#94a3b8' }}>
                            {c.sku} × {c.qty}
                          </span>
                        ))}
                      </td>
                    </tr>
                  )}
                </>
              )
            })}
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
                <label>商品管理番号（URL）<span style={{ color: '#f87171' }}> *</span></label>
                <input {...f('sku')} placeholder="例: ITEM-001（楽天商品URLの一部になる番号）" />
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
                <label>仕入れURL（タオタロウ発注URL）</label>
                <input {...f('buy_url')} placeholder="https://..." />
              </div>
              <div className="form-group">
                <label>仕入れ値（元）</label>
                <input type="number" step="0.01" {...f('price', 'number')} />
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
                <div className="form-group" style={{ gridColumn: '1 / -1' }}>
                  <label>在庫管理番号</label>
                  <input {...f('rakuten_item_url')} placeholder="例: ITEM-001（社内在庫管理用番号）" />
                </div>
                <div className="form-group">
                  <label>楽天SKU管理番号（半角32文字）</label>
                  <input {...f('rakuten_sku_id')} placeholder="例: y60_4_black" />
                </div>
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
