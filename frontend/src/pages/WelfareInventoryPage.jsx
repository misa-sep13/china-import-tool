import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'

const fmtDate = (v) => {
  if (!v) return '-'
  try { return new Date(v).toLocaleString('ja-JP') } catch { return '-' }
}

const fmtWorkDate = (row) => {
  const sheet = String(row.source_sheet || '').trim()
  if (/^\d{2}$/.test(sheet)) return `${Number(sheet.slice(0, 1))}/${Number(sheet.slice(1))}`
  if (/^\d{3}$/.test(sheet)) return `${Number(sheet.slice(0, 1))}/${Number(sheet.slice(1))}`
  if (/^\d{4}$/.test(sheet)) return `${Number(sheet.slice(0, 2))}/${Number(sheet.slice(2))}`
  const mixed = sheet.match(/^(\d{1,2})[/-](\d{1,2})(.*)$/)
  if (mixed) return `${Number(mixed[1])}/${Number(mixed[2])}${mixed[3] || ''}`
  const dotted = sheet.match(/^(\d{1,2})・(\d{1,2})(.*)$/)
  if (dotted) return sheet
  const compact = sheet.match(/^(\d{3,4})(.+)$/)
  if (compact) {
    const d = compact[1]
    const month = d.length === 3 ? Number(d.slice(0, 1)) : Number(d.slice(0, 2))
    const day = d.length === 3 ? Number(d.slice(1)) : Number(d.slice(2))
    return `${month}/${day}${compact[2]}`
  }
  return sheet || row.order_date || '-'
}

const workDateSortValue = (date) => {
  const s = String(date || '')
  const today = new Date()
  const currentYear = today.getFullYear()
  const currentMonthDay = (today.getMonth() + 1) * 100 + today.getDate()
  const withDate = s.match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})/)
  if (withDate) return Number(withDate[1]) * 10000 + Number(withDate[2]) * 100 + Number(withDate[3])
  const monthDay = s.match(/^(\d{1,2})[\/・](\d{1,2})/)
  if (monthDay) {
    const value = Number(monthDay[1]) * 100 + Number(monthDay[2])
    const year = value > currentMonthDay ? currentYear - 1 : currentYear
    return year * 10000 + value
  }
  return -1
}

const workRemainingQty = (row) => row.remaining_qty ?? 0

const WORK_INSTRUCTION_OPTIONS = ['作業保管', '保管', '戻し']

const instructionCellStyle = (value) => {
  const v = String(value || '')
  if (v.includes('作業保管')) return { background: '#dbeafe' }
  if (v.includes('戻し')) return { background: '#fef3c7' }
  return { background: '#fff' }
}

const imageThumb = (src) => (
  src ? <img src={src} alt="" style={{ width: 42, height: 42, objectFit: 'cover', borderRadius: 4, display: 'block' }} /> : '-'
)

export default function WelfareInventoryPage() {
  const qc = useQueryClient()
  const fileRef = useRef(null)
  const [search, setSearch] = useState('')
  const [activeTab, setActiveTab] = useState('inventory')
  const [importResult, setImportResult] = useState(null)
  const [editing, setEditing] = useState(null)
  const [withdrawing, setWithdrawing] = useState(null)
  const [withdrawQty, setWithdrawQty] = useState(1)
  const [withdrawNote, setWithdrawNote] = useState('')
  const [remainingDrafts, setRemainingDrafts] = useState({})
  const [workDrafts, setWorkDrafts] = useState({})
  const [activeWorkDate, setActiveWorkDate] = useState('')

  const { data: items = [], isLoading } = useQuery({
    queryKey: ['welfare-inventory', search],
    queryFn: () => api.get('/welfare/inventory', { params: search ? { q: search } : {} }).then(r => r.data),
  })

  const { data: movements = [] } = useQuery({
    queryKey: ['welfare-movements'],
    queryFn: () => api.get('/welfare/movements').then(r => r.data),
  })

  const { data: workInstructions = [], isLoading: workLoading } = useQuery({
    queryKey: ['welfare-work-instructions', search],
    queryFn: () => api.get('/welfare/work-instructions', { params: search ? { q: search } : {} }).then(r => r.data),
  })

  const workDateTabs = useMemo(() => {
    const counts = new Map()
    workInstructions.forEach(row => {
      const date = fmtWorkDate(row)
      counts.set(date, (counts.get(date) || 0) + 1)
    })
    return Array.from(counts, ([date, count]) => ({ date, count }))
      .sort((a, b) => workDateSortValue(b.date) - workDateSortValue(a.date) || String(b.date).localeCompare(String(a.date), 'ja'))
  }, [workInstructions])

  const visibleWorkInstructions = useMemo(
    () => activeWorkDate ? workInstructions.filter(row => fmtWorkDate(row) === activeWorkDate) : workInstructions,
    [activeWorkDate, workInstructions]
  )

  useEffect(() => {
    if (activeTab !== 'work') return
    if (workDateTabs.length === 0) {
      if (activeWorkDate) setActiveWorkDate('')
      return
    }
    if (!activeWorkDate || !workDateTabs.some(tab => tab.date === activeWorkDate)) {
      setActiveWorkDate(workDateTabs[0].date)
    }
  }, [activeTab, activeWorkDate, workDateTabs])

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
      qc.invalidateQueries(['welfare-work-instructions'])
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

  const workSaveMutation = useMutation({
    mutationFn: ({ id, payload }) => api.patch(`/welfare/work-instructions/${id}`, payload).then(r => r.data),
    onSuccess: (_data, vars) => {
      setWorkDrafts(prev => {
        const next = { ...prev }
        delete next[vars.id]
        return next
      })
      qc.invalidateQueries(['welfare-work-instructions'])
    },
  })

  const workDeleteMutation = useMutation({
    mutationFn: (id) => api.delete(`/welfare/work-instructions/${id}`).then(r => r.data),
    onSuccess: (_data, id) => {
      setWorkDrafts(prev => {
        const next = { ...prev }
        delete next[id]
        return next
      })
      qc.invalidateQueries(['welfare-work-instructions'])
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
          placeholder="SKU・商品名・仕様で検索"
        />
        <button className="btn btn-primary" onClick={() => fileRef.current?.click()} disabled={importMutation.isPending}>
          Excel取込
        </button>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 12px', borderRadius: 8, background: '#fff', border: '1px solid #e2e8f0', fontSize: 13 }}>
          <span style={{ color: '#64748b' }}>登録商品</span>
          <strong style={{ fontSize: 18 }}>{items.length}</strong>
        </div>
        <input ref={fileRef} type="file" accept=".xlsx,.xls" style={{ display: 'none' }} onChange={handleFile} />
      </div>

      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        <button
          className={`btn ${activeTab === 'inventory' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setActiveTab('inventory')}
        >
          就労支援在庫
        </button>
        <button
          className={`btn ${activeTab === 'work' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setActiveTab('work')}
        >
          作業指示
        </button>
      </div>

      {importResult && (
        <div className="card" style={{ borderLeft: importResult.unmatched ? '4px solid #d97706' : '4px solid #16a34a' }}>
          取込完了: 在庫 {importResult.imported}行 / 作業指示 {importResult.work_imported ?? importResult.imported}行 / 未照合 {importResult.unmatched}行
        </div>
      )}

      {activeTab === 'inventory' && <div className="card">
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
                  <th>写真</th>
                  <th>日本語名</th>
                  <th>URL / 仕様</th>
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
                    <td>{imageThumb(item.image_data_url)}</td>
                    <td style={{ minWidth: 220 }}>{item.name_jp || '-'}</td>
                    <td style={{ minWidth: 240 }}>
                      <div>{item.buy_url ? <a href={item.buy_url} target="_blank" rel="noreferrer">URL</a> : '-'}</div>
                      <div style={{ color: '#64748b', fontSize: 12 }}>{item.supplier_spec}</div>
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
      </div>}

      {activeTab === 'work' && <div className="card">
        {workLoading ? (
          <div className="loading">読み込み中...</div>
        ) : workInstructions.length === 0 ? (
          <div className="empty-state">
            <p>作業指示がありません。Excelを取り込むと表示されます。</p>
          </div>
        ) : (
          <div>
            <div style={{ display: 'flex', gap: 8, overflowX: 'auto', paddingBottom: 10, marginBottom: 12 }}>
              {workDateTabs.map(tab => (
                <button
                  key={tab.date}
                  className={`btn ${activeWorkDate === tab.date ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => setActiveWorkDate(tab.date)}
                  style={{ whiteSpace: 'nowrap' }}
                >
                  {tab.date} ({tab.count})
                </button>
              ))}
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ minWidth: 920, width: '100%', tableLayout: 'fixed' }}>
                <thead>
                  <tr>
                    <th style={{ width: 54 }}></th>
                    <th style={{ width: 54 }}>写真</th>
                    <th style={{ width: 110 }}>商品名</th>
                    <th style={{ width: 82 }}>色</th>
                    <th style={{ width: 70 }}>サイズ</th>
                    <th style={{ width: 48 }}>URL</th>
                    <th style={{ width: 58 }}>単品数</th>
                    <th style={{ width: 58 }}>換算</th>
                    <th style={{ width: 70 }}>残</th>
                    <th style={{ width: 62 }}>指示</th>
                    <th style={{ width: 120 }}>備考</th>
                    <th style={{ width: 58 }}></th>
                    <th style={{ width: 78 }}>発注時間</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleWorkInstructions.map(row => {
                    const draft = workDrafts[row.id] || {}
                    const instruction = draft.instruction ?? row.instruction
                    const remaining = draft.remaining_qty ?? workRemainingQty(row)
                    const note = draft.note ?? row.note
                    const dirty = instruction !== row.instruction || remaining !== workRemainingQty(row) || note !== row.note
                    return (
                      <tr key={row.id}>
                        <td style={{ whiteSpace: 'nowrap' }}>
                          <button
                            className="btn btn-secondary btn-sm"
                            style={{ color: '#e11d48', padding: '6px 8px' }}
                            disabled={workDeleteMutation.isPending}
                            onClick={() => {
                              if (window.confirm('この作業指示を削除しますか？')) {
                                workDeleteMutation.mutate(row.id)
                              }
                            }}
                          >
                            削除
                          </button>
                        </td>
                        <td>{imageThumb(row.image_data_url)}</td>
                        <td style={{ wordBreak: 'break-word' }}>{row.source_product_name || row.name_jp || '未照合'}</td>
                        <td style={{ color: '#e11d48' }}>{row.color || row.supplier_spec || '-'}</td>
                        <td style={{ color: '#e11d48' }}>{row.size || '-'}</td>
                        <td>{row.buy_url ? <a href={row.buy_url} target="_blank" rel="noreferrer">URL</a> : '-'}</td>
                        <td style={{ color: '#e11d48', fontWeight: 700 }}>{row.units}</td>
                        <td>{row.unit_per_set || 1}個で1</td>
                        <td style={{ minWidth: 76 }}>
                          <input
                          type="number"
                          min="0"
                          value={remaining}
                            onChange={e => setWorkDrafts(prev => ({ ...prev, [row.id]: { ...draft, remaining_qty: Number(e.target.value) } }))}
                            style={{ width: 62, textAlign: 'right', fontWeight: 700 }}
                          />
                        </td>
                        <td style={{ ...instructionCellStyle(instruction), padding: 6 }}>
                          <input
                            list="work-instruction-options"
                            value={instruction}
                            onChange={e => setWorkDrafts(prev => ({ ...prev, [row.id]: { ...draft, instruction: e.target.value } }))}
                            style={{ width: 52, minWidth: 0, background: 'transparent', border: '1px solid #cbd5e1', borderRadius: 6, padding: '6px 3px' }}
                          />
                        </td>
                        <td>
                          <input
                            value={note}
                            onChange={e => setWorkDrafts(prev => ({ ...prev, [row.id]: { ...draft, note: e.target.value } }))}
                            placeholder="備考"
                          />
                        </td>
                        <td style={{ whiteSpace: 'nowrap' }}>
                          {dirty && (
                            <button
                              className="btn btn-primary btn-sm"
                            disabled={workSaveMutation.isPending}
                            onClick={() => workSaveMutation.mutate({
                              id: row.id,
                              payload: { instruction, remaining_qty: remaining, note },
                            })}
                          >
                              保存
                            </button>
                          )}
                        </td>
                        <td style={{ whiteSpace: 'nowrap' }}>{row.order_date || fmtWorkDate(row)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              <datalist id="work-instruction-options">
                {WORK_INSTRUCTION_OPTIONS.map(opt => <option key={opt} value={opt} />)}
              </datalist>
            </div>
          </div>
        )}
      </div>}

      {activeTab === 'inventory' && <div className="card">
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
      </div>}

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
