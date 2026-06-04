import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'

const EMPTY = {
  sku: '', fnsku: '', asin: '', name: '', buy_url: '', photo_url: '',
  color: '', size: '', price: '', repack: '', note: '', set_size: 1, extra_stock: 0,
}

export default function ProductsPage() {
  const qc = useQueryClient()
  const [modal, setModal] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState(EMPTY)
  const [error, setError] = useState('')

  const { data: products = [], isLoading } = useQuery({
    queryKey: ['products'],
    queryFn: () => api.get('/products/').then(r => r.data),
  })

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
      const { added, skipped } = res.data
      alert(`インポート完了！\n追加: ${added}件\nスキップ(既存): ${skipped}件`)
      qc.invalidateQueries(['products'])
    } catch (e) {
      alert('インポート失敗: ' + (e.response?.data?.detail || e.message))
    } finally {
      setImporting(false)
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
    const data = { ...form, price: Number(form.price) || 0, set_size: Number(form.set_size) || 1, extra_stock: Number(form.extra_stock) || 0 }
    save.mutate(data)
  }

  const f = (k) => ({ value: form[k], onChange: e => setForm(p => ({ ...p, [k]: e.target.value })) })

  if (isLoading) return <div className="loading">読み込み中...</div>

  return (
    <div>
      <h1>🏷️ 商品マスタ</h1>
      <div className="top-actions">
        <button className="btn btn-primary" onClick={openNew}>＋ 商品を追加</button>
        <button className="btn btn-secondary" onClick={importFromFba} disabled={importing}>
          {importing ? 'インポート中...' : '📦 FBAから自動インポート'}
        </button>
        <span style={{ color: '#888', fontSize: 13 }}>{products.length}件登録済み</span>
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
                  <th>FNSKU</th>
                  <th>ASIN</th>
                  <th>商品名</th>
                  <th>色</th>
                  <th>サイズ</th>
                  <th>単価(元)</th>
                  <th>セット数</th>
                  <th>仕入URL</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {products.map(p => (
                  <tr key={p.id}>
                    <td style={{ fontFamily: 'monospace', fontSize: 12, whiteSpace: 'nowrap', maxWidth: 100, overflow: 'hidden', textOverflow: 'ellipsis' }}>{p.sku}</td>
                    <td style={{ fontFamily: 'monospace', fontSize: 12, color: '#888' }}>{p.fnsku}</td>
                    <td style={{ fontFamily: 'monospace', fontSize: 12, color: '#888' }}>{p.asin}</td>
                    <td style={{ maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.name}</td>
                    <td>{p.color}</td>
                    <td>{p.size}</td>
                    <td style={{ textAlign: 'right' }}>{p.price}</td>
                    <td style={{ textAlign: 'center' }}>{p.set_size}</td>
                    <td>
                      {p.buy_url && (
                        <a href={p.buy_url} target="_blank" rel="noreferrer" style={{ color: '#e94560', fontSize: 12 }}>
                          リンク
                        </a>
                      )}
                    </td>
                    <td>
                      <div style={{ display: 'flex', gap: 6 }}>
                        <button className="btn btn-secondary btn-sm" onClick={() => openEdit(p)}>編集</button>
                        <button className="btn btn-sm" style={{ background: '#fee2e2', color: '#991b1b' }}
                          onClick={() => { if (confirm('削除しますか？')) del.mutate(p.id) }}>削除</button>
                      </div>
                    </td>
                  </tr>
                ))}
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
                <div className="form-group">
                  <label>別個数在庫</label>
                  <input type="number" min={0} {...f('extra_stock')} />
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
