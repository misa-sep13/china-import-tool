import { useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'

const fmtDate = (v) => {
  if (!v) return '-'
  try { return new Date(v).toLocaleString('ja-JP') } catch { return '-' }
}

export default function WelfareInventoryPage() {
  const qc = useQueryClient()
  const fileRef = useRef(null)
  const [search, setSearch] = useState('')
  const [importResult, setImportResult] = useState(null)
  const [editing, setEditing] = useState(null)
  const [withdrawing, setWithdrawing] = useState(null)
  const [withdrawQty, setWithdrawQty] = useState(1)
  const [withdrawNote, setWithdrawNote] = useState('')
  const [remainingDrafts, setRemainingDrafts] = useState({})

  const { data: items = [], isLoading } = useQuery({
    queryKey: ['welfare-inventory', search],
    queryFn: () => api.get('/welfare/inventory', { params: search ? { q: search } : {} }).then(r => r.data),
  })

  const { data: movements = [] } = useQuery({
    queryKey: ['welfare-movements'],
    queryFn: () => api.get('/welfare/movements').then(r => r.data),
  })

  const totals = useMemo(() => ({
    count: items.length,
    remaining: items.reduce((sum, it) => sum + (it.remaining_qty || 0), 0),
    units: items.reduce((sum, it) => sum + (it.total_received_units || 0), 0),
  }), [items])

  const importMutation = useMutation({
    mutationFn: async (file) => {
      const fd = new FormData()
      fd.append('file', file)
      return api.post('/welfare/import-excel', fd, { headers: { 'Content-Type': 'multipart/form-data' } }).then(r => r.data)
    },
    onSuccess: (data) => {
      setImportResult(data)
      qc.invalidateQueries(['welfare-inventory'])
      qc.invalidateQueries(['welfare-movements'])
    },
  })

  const saveMutation = useMutation({
    mutationFn: ({ id, payload }) => api.patch(`/welfare/inventory/${id}`, payload).then(r => r.data),
    onSuccess: () => {
      setEditing(null)
      qc.invalidateQueries(['welfare-inventory'])
    },
  })

  const withdrawMutation = useMutation({
    mutationFn: ({ id, qty, note }) => api.post(`/welfare/inventory/${id}/withdraw`, { qty, note }).then(r => r.data),
    onSuccess: () => {
      setWithdrawing(null)
      setWithdrawQty(1)
      setWithdrawNote('')
      qc.invalidateQueries(['welfare-inventory'])
      qc.invalidateQueries(['welfare-movements'])
    },
  })

  const adjustMutation = useMutation({
    mutationFn: ({ id, remaining_qty }) => api.post(`/welfare/inventory/${id}/adjust`, {
      remaining_qty,
      note: '画面から残量直接修正',
    }).then(r => r.data),
    onSuccess: (_data, vars) => {
      setRemainingDrafts(prev => {
        const next = { ...prev }
        delete next[vars.id]
        return next
      })
      qc.invalidateQueries(['welfare-inventory'])
      qc.invalidateQueries(['welfare-movements'])
    },
  })

  const handleFile = (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setImportResult(null)
    importMutation.mutate(file)
    e.target.value = ''
  }

  const openEdit = (item) => {
    setEditing({ ...item, instruction: item.instruction || '', note: item.note || '' })
  }

  return (
    <div>
      <h1>就労支援在庫</h1>

      <div className="top-actions">
        <input
          style={{ maxWidth: 320 }}
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="SKU・商品名・中国名で検索"
        />
        <button className="btn btn-primary" onClick={() => fileRef.current?.click()} disabled={importMutation.isPending}>
          Excel取込
        </button>
        <input ref={fileRef} type="file" accept=".xlsx,.xls" style={{ display: 'none' }} onChange={handleFile} />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12, marginBottom: 16 }}>
        <div className="card" style={{ margin: 0 }}>
          <div style={{ fontSize: 12, color: '#64748b' }}>登録商品</div>
          <div style={{ fontSize: 24, fontWeight: 700 }}>{totals.count}</div>
        </div>
        <div className="card" style={{ margin: 0 }}>
          <div style={{ fontSize: 12, color: '#64748b' }}>残量合計</div>
          <div style={{ fontSize: 24, fontWeight: 700 }}>{totals.remaining}</div>
        </div>
        <div className="card" style={{ margin: 0 }}>
          <div style={{ fontSize: 12, color: '#64748b' }}>取込単品数</div>
          <div style={{ fontSize: 24, fontWeight: 700 }}>{totals.units}</div>
        </div>
      </div>

      {importResult && (
        <div className="card" style={{ borderLeft: importResult.unmatched ? '4px solid #d97706' : '4px solid #16a34a' }}>
          取込完了: {importResult.imported}行 / 未照合 {importResult.unmatched}行
        </div>
      )}

      <div className="card">
        {isLoading ? (
          <div className="loading">読み込み中...</div>
        ) : items.length === 0 ? (
          <div className="empty-state">
            <p>就労支援在庫がありません。</p>
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th>SKU</th>
                  <th>日本語名</th>
                  <th>中国名 / 仕様</th>
                  <th>URL</th>
                  <th>単品数</th>
                  <th>換算</th>
                  <th>入荷数</th>
                  <th>残量</th>
                  <th>指示</th>
                  <th>備考</th>
                  <th>更新</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {items.map(item => (
                  <tr key={item.id}>
                    <td style={{ fontWeight: 700 }}>{item.sku || '-'}</td>
                    <td style={{ minWidth: 220 }}>{item.name_jp || '-'}</td>
                    <td style={{ minWidth: 240 }}>
                      <div>{item.name_cn}</div>
                      <div style={{ color: '#64748b', fontSize: 12 }}>{item.supplier_spec}</div>
                    </td>
                    <td>
                      {item.buy_url ? <a href={item.buy_url} target="_blank" rel="noreferrer">開く</a> : '-'}
                    </td>
                    <td>{item.total_received_units}</td>
                    <td>{item.unit_per_set}個で1</td>
                    <td>{item.total_received_qty}</td>
                    <td style={{ minWidth: 120 }}>
                      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                        <input
                          type="number"
                          min="0"
                          value={remainingDrafts[item.id] ?? item.remaining_qty}
                          onChange={e => setRemainingDrafts(prev => ({ ...prev, [item.id]: Number(e.target.value) }))}
                          style={{ width: 72, fontSize: 16, fontWeight: 700, textAlign: 'right' }}
                        />
                        {(remainingDrafts[item.id] ?? item.remaining_qty) !== item.remaining_qty && (
                          <button
                            className="btn btn-primary btn-sm"
                            onClick={() => adjustMutation.mutate({ id: item.id, remaining_qty: remainingDrafts[item.id] })}
                            disabled={adjustMutation.isPending}
                          >
                            保存
                          </button>
                        )}
                      </div>
                    </td>
                    <td style={{ minWidth: 160 }}>{item.instruction || '-'}</td>
                    <td style={{ minWidth: 160 }}>{item.note || '-'}</td>
                    <td style={{ whiteSpace: 'nowrap', color: '#64748b', fontSize: 12 }}>{fmtDate(item.last_received_at)}</td>
                    <td style={{ whiteSpace: 'nowrap' }}>
                      <button className="btn btn-secondary btn-sm" onClick={() => openEdit(item)}>編集</button>
                      <button className="btn btn-primary btn-sm" style={{ marginLeft: 6 }} onClick={() => setWithdrawing(item)} disabled={!item.remaining_qty}>
                        減算
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card">
        <h2>最近の入出庫</h2>
        {movements.length === 0 ? (
          <div style={{ color: '#64748b' }}>履歴はまだありません。</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>日時</th>
                <th>種別</th>
                <th>SKU</th>
                <th>数量</th>
                <th>単品数</th>
                <th>メモ</th>
              </tr>
            </thead>
            <tbody>
              {movements.slice(0, 20).map(m => (
                <tr key={m.id}>
                  <td>{fmtDate(m.created_at)}</td>
                  <td>{m.movement_type === 'withdraw' ? '減算' : m.movement_type === 'adjust' ? '修正' : '取込'}</td>
                  <td>{m.sku || '-'}</td>
                  <td>{m.qty}</td>
                  <td>{m.units}</td>
                  <td>{m.note || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {editing && (
        <div className="modal-overlay">
          <div className="modal">
            <div className="modal-header">
              <h2>指示・備考</h2>
              <button className="modal-close" onClick={() => setEditing(null)}>×</button>
            </div>
            <div className="form-grid">
              <div className="form-group">
                <label>指示</label>
                <textarea rows={4} value={editing.instruction} onChange={e => setEditing(prev => ({ ...prev, instruction: e.target.value }))} />
              </div>
              <div className="form-group">
                <label>備考</label>
                <textarea rows={4} value={editing.note} onChange={e => setEditing(prev => ({ ...prev, note: e.target.value }))} />
              </div>
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button className="btn btn-secondary" onClick={() => setEditing(null)}>キャンセル</button>
              <button className="btn btn-primary" onClick={() => saveMutation.mutate({ id: editing.id, payload: { instruction: editing.instruction, note: editing.note } })}>
                保存
              </button>
            </div>
          </div>
        </div>
      )}

      {withdrawing && (
        <div className="modal-overlay">
          <div className="modal">
            <div className="modal-header">
              <h2>在庫を引き上げ</h2>
              <button className="modal-close" onClick={() => setWithdrawing(null)}>×</button>
            </div>
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontWeight: 700 }}>{withdrawing.sku} / {withdrawing.name_jp}</div>
              <div style={{ color: '#64748b', fontSize: 13 }}>現在の残量: {withdrawing.remaining_qty}</div>
            </div>
            <div className="form-grid">
              <div className="form-group">
                <label>減算数</label>
                <input type="number" min="1" max={withdrawing.remaining_qty} value={withdrawQty} onChange={e => setWithdrawQty(Number(e.target.value))} />
              </div>
              <div className="form-group">
                <label>メモ</label>
                <input value={withdrawNote} onChange={e => setWithdrawNote(e.target.value)} placeholder="こちらに引き上げ 等" />
              </div>
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button className="btn btn-secondary" onClick={() => setWithdrawing(null)}>キャンセル</button>
              <button className="btn btn-primary" onClick={() => withdrawMutation.mutate({ id: withdrawing.id, qty: withdrawQty, note: withdrawNote })}>
                減算する
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
