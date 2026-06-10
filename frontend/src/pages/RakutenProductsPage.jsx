import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'

const EMPTY = {
  sku: '', name: '', jan_code: '', buy_url: '', price: '',
  set_size: 1, stock: 0, inbound: 0,
  sales_30_recent: 0, sales_30_prev: 0, memo: '', is_active: true,
}

export default function RakutenProductsPage() {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(null)   // null | 'new' | product
  const [form, setForm] = useState(EMPTY)
  const [search, setSearch] = useState('')

  const { data: products = [], isLoading } = useQuery({
    queryKey: ['rakuten-products'],
    queryFn: () => api.get('/rakuten/products').then(r => r.data),
  })

  const saveMutation = useMutation({
    mutationFn: (d) => editing === 'new'
      ? api.post('/rakuten/products', d)
      : api.put(`/rakuten/products/${editing.id}`, d),
    onSuccess: () => { qc.invalidateQueries(['rakuten-products']); qc.invalidateQueries(['rakuten-recommendations']); setEditing(null) },
  })

  const deleteMutation = useMutation({
    mutationFn: (id) => api.delete(`/rakuten/products/${id}`),
    onSuccess: () => { qc.invalidateQueries(['rakuten-products']); qc.invalidateQueries(['rakuten-recommendations']) },
  })

  const openNew = () => { setForm(EMPTY); setEditing('new') }
  const openEdit = (p) => { setForm({ ...p }); setEditing(p) }

  const f = (k, type = 'text') => ({
    value: form[k] ?? '',
    onChange: e => setForm(prev => ({ ...prev, [k]: type === 'number' ? Number(e.target.value) : e.target.value }))
  })

  const filtered = products.filter(p =>
    !search ||
    (p.sku || '').toLowerCase().includes(search.toLowerCase()) ||
    (p.name || '').toLowerCase().includes(search.toLowerCase()) ||
    (p.jan_code || '').includes(search)
  )

  if (isLoading) return <div className="loading">読み込み中...</div>

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 24 }}>
        <h1>🛒 楽天 商品マスタ</h1>
        <button className="btn btn-primary" onClick={openNew}>+ 商品追加</button>
      </div>

      {/* 検索 */}
      <div className="card" style={{ padding: '12px 16px', marginBottom: 16 }}>
        <input
          type="text" placeholder="SKU・商品名・JANコードで絞り込み"
          value={search} onChange={e => setSearch(e.target.value)}
          style={{ width: '100%', maxWidth: 400 }}
        />
      </div>

      {/* 商品テーブル */}
      <div className="card" style={{ padding: 0, overflow: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: '#1e2433', borderBottom: '2px solid #2d3748' }}>
              {['SKU', '商品名', 'JAN', '実在庫', '輸送中', '直近30日', '前30日', '仕入値(元)', '操作'].map(h => (
                <th key={h} style={{ padding: '10px 12px', textAlign: 'center', color: '#94a3b8', whiteSpace: 'nowrap' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr><td colSpan={9} style={{ textAlign: 'center', padding: 32, color: '#64748b' }}>商品がありません</td></tr>
            )}
            {filtered.map(p => (
              <tr key={p.id} style={{ borderBottom: '1px solid #2d3748' }}>
                <td style={{ padding: '10px 12px', color: '#94a3b8', fontFamily: 'monospace' }}>{p.sku}</td>
                <td style={{ padding: '10px 12px', color: '#e2e8f0', maxWidth: 200 }}>
                  <div>{p.name || '—'}</div>
                  {p.buy_url && <a href={p.buy_url} target="_blank" rel="noreferrer" style={{ fontSize: 11, color: '#60a5fa' }}>仕入れURL</a>}
                </td>
                <td style={{ padding: '10px 12px', color: '#94a3b8', fontFamily: 'monospace' }}>{p.jan_code || '—'}</td>
                <td style={{ padding: '10px 12px', textAlign: 'center', fontWeight: 700, color: '#e2e8f0' }}>{p.stock}</td>
                <td style={{ padding: '10px 12px', textAlign: 'center', color: '#94a3b8' }}>{p.inbound}</td>
                <td style={{ padding: '10px 12px', textAlign: 'center', color: '#60a5fa', fontWeight: 600 }}>{p.sales_30_recent}</td>
                <td style={{ padding: '10px 12px', textAlign: 'center', color: '#94a3b8' }}>{p.sales_30_prev}</td>
                <td style={{ padding: '10px 12px', textAlign: 'center', color: '#94a3b8' }}>{p.price != null ? `¥${p.price}` : '—'}</td>
                <td style={{ padding: '10px 12px', whiteSpace: 'nowrap' }}>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <button className="btn" style={{ fontSize: 12, padding: '3px 10px' }} onClick={() => openEdit(p)}>編集</button>
                    <button
                      className="btn"
                      style={{ fontSize: 12, padding: '3px 10px', color: '#f87171' }}
                      onClick={() => { if (confirm(`${p.name || p.sku} を削除しますか？`)) deleteMutation.mutate(p.id) }}
                    >削除</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* 編集モーダル */}
      {editing && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000
        }}>
          <div style={{ background: '#1a2235', borderRadius: 12, padding: 32, width: 560, maxHeight: '90vh', overflowY: 'auto', border: '1px solid #2d3748' }}>
            <h2 style={{ marginBottom: 20 }}>{editing === 'new' ? '商品追加' : '商品編集'}</h2>

            <div className="form-grid" style={{ gridTemplateColumns: '1fr 1fr' }}>
              <div className="form-group" style={{ gridColumn: '1 / -1' }}>
                <label>商品管理番号（SKU）<span style={{ color: '#f87171' }}> *</span></label>
                <input {...f('sku')} placeholder="例: ITEM-001" />
              </div>
              <div className="form-group" style={{ gridColumn: '1 / -1' }}>
                <label>商品名</label>
                <input {...f('name')} placeholder="例: ○○ポーチ" />
              </div>
              <div className="form-group">
                <label>JANコード</label>
                <input {...f('jan_code')} placeholder="例: 4900000000000" />
              </div>
              <div className="form-group">
                <label>セット入数</label>
                <input type="number" min={1} {...f('set_size', 'number')} />
              </div>
              <div className="form-group" style={{ gridColumn: '1 / -1' }}>
                <label>仕入れURL</label>
                <input {...f('buy_url')} placeholder="https://..." />
              </div>
              <div className="form-group">
                <label>仕入れ値（元）</label>
                <input type="number" step="0.01" {...f('price', 'number')} />
              </div>
            </div>

            <div style={{ borderTop: '1px solid #2d3748', margin: '20px 0 16px', paddingTop: 16 }}>
              <h3 style={{ fontSize: 14, color: '#94a3b8', marginBottom: 12 }}>📦 在庫（手動入力）</h3>
              <div className="form-grid" style={{ gridTemplateColumns: '1fr 1fr' }}>
                <div className="form-group">
                  <label>実在庫（手持ち）</label>
                  <input type="number" min={0} {...f('stock', 'number')} />
                </div>
                <div className="form-group">
                  <label>輸送中</label>
                  <input type="number" min={0} {...f('inbound', 'number')} />
                </div>
              </div>
            </div>

            <div style={{ borderTop: '1px solid #2d3748', margin: '0 0 16px', paddingTop: 16 }}>
              <h3 style={{ fontSize: 14, color: '#94a3b8', marginBottom: 4 }}>📊 販売実績（楽天API or 手動入力）</h3>
              <p style={{ fontSize: 12, color: '#64748b', marginBottom: 12 }}>
                90日分の販売データを30日ずつ区切って入力します。在庫切れ期間は除外してください。
              </p>
              <div className="form-grid" style={{ gridTemplateColumns: '1fr 1fr' }}>
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

            <div className="form-group">
              <label>メモ</label>
              <textarea
                value={form.memo || ''}
                onChange={e => setForm(p => ({ ...p, memo: e.target.value }))}
                rows={2} style={{ resize: 'vertical' }}
              />
            </div>

            <div style={{ display: 'flex', gap: 12, marginTop: 24 }}>
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
