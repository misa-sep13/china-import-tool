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
const DELETE_UNDO_MS = 8000
const JA_SORT_OPTIONS = { numeric: true, sensitivity: 'base' }

const workDisplayName = (row) => String(row.name_jp || row.source_product_name || row.sku || '').trim()

const compareWorkInstructions = (a, b) => {
  const name = workDisplayName(a).localeCompare(workDisplayName(b), 'ja', JA_SORT_OPTIONS)
  if (name) return name

  const specA = String(a.color || a.supplier_spec || '').trim()
  const specB = String(b.color || b.supplier_spec || '').trim()
  const spec = specA.localeCompare(specB, 'ja', JA_SORT_OPTIONS)
  if (spec) return spec

  const size = String(a.size || '').trim().localeCompare(String(b.size || '').trim(), 'ja', JA_SORT_OPTIONS)
  if (size) return size

  return (b.id || 0) - (a.id || 0)
}

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
  const deleteTimersRef = useRef(new Map())
  const pendingWorkDeleteRowsRef = useRef(new Map())
  const [search, setSearch] = useState('')
  const [activeTab, setActiveTab] = useState('inventory')
  const [importResult, setImportResult] = useState(null)
  const [editing, setEditing] = useState(null)
  const [withdrawing, setWithdrawing] = useState(null)
  const [withdrawQty, setWithdrawQty] = useState(1)
  const [withdrawNote, setWithdrawNote] = useState('')
  const [inventoryDrafts, setInventoryDrafts] = useState({})
  const [remainingDrafts, setRemainingDrafts] = useState({})
  const [workDrafts, setWorkDrafts] = useState({})
  const [checkedWorkIds, setCheckedWorkIds] = useState(new Set())
  const [activeWorkDate, setActiveWorkDate] = useState('')
  const [pendingWorkDeletes, setPendingWorkDeletes] = useState([])
  const [committingWorkDeleteIds, setCommittingWorkDeleteIds] = useState([])
  const [inventorySort, setInventorySort] = useState('sku')

  const getInventoryDraftValue = (item, draft = {}) => ({
    name_jp: draft.name_jp ?? item.name_jp ?? '',
  })

  const updateInventoryDraft = (item, patch) => {
    setInventoryDrafts(prev => {
      const current = getInventoryDraftValue(item, prev[item.id] || {})
      return { ...prev, [item.id]: { ...current, ...patch } }
    })
  }

  const getWorkDraftValue = (row, draft = {}) => ({
    name_jp: draft.name_jp ?? row.name_jp ?? '',
    source_product_name: draft.source_product_name ?? row.name_jp ?? row.source_product_name ?? '',
    instruction: draft.instruction ?? row.instruction ?? '',
    remaining_qty: draft.remaining_qty ?? workRemainingQty(row),
    note: draft.note ?? row.note ?? '',
  })

  const updateWorkDraft = (row, patch) => {
    setWorkDrafts(prev => {
      const current = getWorkDraftValue(row, prev[row.id] || {})
      return { ...prev, [row.id]: { ...current, ...patch } }
    })
  }

  const { data: rawItems = [], isLoading } = useQuery({
    queryKey: ['welfare-inventory', search],
    queryFn: () => api.get('/welfare/inventory', { params: search ? { q: search } : {} }).then(r => r.data),
  })

  const items = useMemo(() => {
    if (inventorySort === 'sku') {
      return [...rawItems].sort((a, b) => (a.sku || '').localeCompare(b.sku || '', 'ja', JA_SORT_OPTIONS))
    }
    return rawItems
  }, [rawItems, inventorySort])

  const { data: movements = [] } = useQuery({
    queryKey: ['welfare-movements'],
    queryFn: () => api.get('/welfare/movements').then(r => r.data),
  })

  const { data: workInstructions = [], isLoading: workLoading } = useQuery({
    queryKey: ['welfare-work-instructions', search],
    queryFn: () => api.get('/welfare/work-instructions', { params: search ? { q: search } : {} }).then(r => r.data),
  })

  const pendingWorkDeleteIds = useMemo(
    () => new Set([...pendingWorkDeletes.map(item => item.id), ...committingWorkDeleteIds]),
    [committingWorkDeleteIds, pendingWorkDeletes]
  )

  const activeWorkInstructions = useMemo(
    () => workInstructions.filter(row => !pendingWorkDeleteIds.has(row.id)),
    [pendingWorkDeleteIds, workInstructions]
  )

  const workDateTabs = useMemo(() => {
    const groups = new Map()
    activeWorkInstructions.forEach(row => {
      const date = fmtWorkDate(row)
      if (!groups.has(date)) groups.set(date, { count: 0, maxCreatedAt: '' })
      const g = groups.get(date)
      g.count++
      const ts = row.created_at || ''
      if (ts > g.maxCreatedAt) g.maxCreatedAt = ts
    })
    return Array.from(groups, ([date, { count, maxCreatedAt }]) => ({ date, count, maxCreatedAt }))
      .sort((a, b) => {
        if (a.maxCreatedAt && b.maxCreatedAt) return b.maxCreatedAt.localeCompare(a.maxCreatedAt)
        return workDateSortValue(b.date) - workDateSortValue(a.date)
      })
  }, [activeWorkInstructions])

  const visibleWorkInstructions = useMemo(
    () => {
      const rows = activeWorkDate
        ? activeWorkInstructions.filter(row => fmtWorkDate(row) === activeWorkDate)
        : activeWorkInstructions
      return [...rows].sort(compareWorkInstructions)
    },
    [activeWorkDate, activeWorkInstructions]
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
    mutationFn: async (files) => {
      const combined = { imported: 0, work_imported: 0, unmatched: 0, imported_items: [], skipped_items: [], unmatched_items: [], file_count: files.length }
      for (const file of files) {
        const fd = new FormData()
        fd.append('file', file)
        const data = await api.post('/welfare/import-excel', fd, { headers: { 'Content-Type': 'multipart/form-data' } }).then(r => r.data)
        combined.imported += data.imported || 0
        combined.work_imported += data.work_imported || 0
        combined.unmatched += data.unmatched || 0
        if (data.imported_items) combined.imported_items.push(...data.imported_items)
        if (data.skipped_items) combined.skipped_items.push(...data.skipped_items)
        if (data.unmatched_items) combined.unmatched_items.push(...data.unmatched_items)
      }
      return combined
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

  const inventoryNameSaveMutation = useMutation({
    mutationFn: ({ id, payload }) => api.patch(`/welfare/inventory/${id}`, payload).then(r => r.data),
    onSuccess: (data, vars) => {
      // 荷受け側と同じく、再取得の間に入力が巻き戻って見えるのを防ぐためキャッシュを直接更新する
      if (data && data.id != null) {
        qc.setQueriesData({ queryKey: ['welfare-inventory'] }, old => {
          if (!Array.isArray(old)) return old
          return old.map(row => (row.id === data.id ? { ...row, ...data } : row))
        })
      }
      setInventoryDrafts(prev => {
        const current = prev[vars.id]
        if (current && current.name_jp !== vars.payload.name_jp) return prev
        const next = { ...prev }
        delete next[vars.id]
        return next
      })
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
    onSuccess: (data, vars) => {
      // 保存後にinvalidateすると、全行の画像(base64)を含む巨大なリストを再取得する間だけ
      // 入力値が古い値へ巻き戻り「入力が消えた」ように見えるため、
      // サーバーが返した更新後の行でキャッシュを直接差し替える。
      if (data && data.id != null) {
        qc.setQueriesData({ queryKey: ['welfare-work-instructions'] }, old => {
          if (!Array.isArray(old)) return old
          return old.map(row => (row.id === data.id ? { ...row, ...data } : row))
        })
      }
      setWorkDrafts(prev => {
        const current = prev[vars.id]
        if (
          current &&
          (current.name_jp !== vars.payload.name_jp ||
            current.source_product_name !== vars.payload.source_product_name ||
            current.instruction !== vars.payload.instruction ||
            current.remaining_qty !== vars.payload.remaining_qty ||
            current.note !== vars.payload.note)
        ) {
          return prev
        }
        const next = { ...prev }
        delete next[vars.id]
        return next
      })
    },
  })

  const workDeleteMutation = useMutation({
    mutationFn: (id) => api.delete(`/welfare/work-instructions/${id}`).then(r => r.data),
    onSuccess: (_data, id) => {
      pendingWorkDeleteRowsRef.current.delete(id)
      setPendingWorkDeletes(prev => prev.filter(item => item.id !== id))
      setCommittingWorkDeleteIds(prev => prev.filter(itemId => itemId !== id))
      setWorkDrafts(prev => {
        const next = { ...prev }
        delete next[id]
        return next
      })
      qc.invalidateQueries(['welfare-work-instructions'])
    },
    onError: (_error, id) => {
      pendingWorkDeleteRowsRef.current.delete(id)
      setPendingWorkDeletes(prev => prev.filter(item => item.id !== id))
      setCommittingWorkDeleteIds(prev => prev.filter(itemId => itemId !== id))
      qc.invalidateQueries(['welfare-work-instructions'])
    },
  })

  const removeWorkInstructionFromCache = (id) => {
    qc.setQueriesData({ queryKey: ['welfare-work-instructions'] }, old => {
      if (!Array.isArray(old)) return old
      return old.filter(row => row.id !== id)
    })
  }

  const handleWorkDelete = (row) => {
    if (deleteTimersRef.current.has(row.id) || pendingWorkDeleteRowsRef.current.has(row.id)) return
    pendingWorkDeleteRowsRef.current.set(row.id, row)
    setPendingWorkDeletes(prev => [{ id: row.id, row }, ...prev.filter(item => item.id !== row.id)])
    setWorkDrafts(prev => {
      const next = { ...prev }
      delete next[row.id]
      return next
    })
    removeWorkInstructionFromCache(row.id)
    const timer = setTimeout(() => {
      deleteTimersRef.current.delete(row.id)
      setCommittingWorkDeleteIds(prev => (prev.includes(row.id) ? prev : [...prev, row.id]))
      setPendingWorkDeletes(prev => prev.filter(item => item.id !== row.id))
      workDeleteMutation.mutate(row.id)
    }, DELETE_UNDO_MS)
    deleteTimersRef.current.set(row.id, timer)
  }

  const undoWorkDelete = (id) => {
    const timer = deleteTimersRef.current.get(id)
    if (timer) clearTimeout(timer)
    deleteTimersRef.current.delete(id)
    pendingWorkDeleteRowsRef.current.delete(id)
    setPendingWorkDeletes(prev => prev.filter(item => item.id !== id))
    setCommittingWorkDeleteIds(prev => prev.filter(itemId => itemId !== id))
    qc.invalidateQueries(['welfare-work-instructions'])
  }

  useEffect(() => {
    return () => {
      deleteTimersRef.current.forEach((timer, id) => {
        clearTimeout(timer)
        api.delete(`/welfare/work-instructions/${id}`).catch(() => {})
      })
      deleteTimersRef.current.clear()
      pendingWorkDeleteRowsRef.current.clear()
    }
  }, [])

  useEffect(() => {
    const timers = []
    Object.entries(inventoryDrafts).forEach(([id, draft]) => {
      const item = items.find(row => String(row.id) === String(id))
      if (!item) return

      const value = getInventoryDraftValue(item, draft)
      const base = getInventoryDraftValue(item)
      if (value.name_jp === base.name_jp) return

      timers.push(setTimeout(() => {
        inventoryNameSaveMutation.mutate({
          id: item.id,
          payload: value,
        })
      }, 800))
    })
    return () => timers.forEach(clearTimeout)
  }, [inventoryDrafts, items])

  useEffect(() => {
    const timers = []
    Object.entries(workDrafts).forEach(([id, draft]) => {
      const row = workInstructions.find(item => String(item.id) === String(id))
      if (!row) return

      const value = getWorkDraftValue(row, draft)
      const base = getWorkDraftValue(row)
      const dirty =
        value.name_jp !== base.name_jp ||
        value.source_product_name !== base.source_product_name ||
        value.instruction !== base.instruction ||
        value.remaining_qty !== base.remaining_qty ||
        value.note !== base.note

      if (!dirty) return
      timers.push(setTimeout(() => {
        workSaveMutation.mutate({
          id: row.id,
          payload: value,
        })
      }, 800))
    })
    return () => timers.forEach(clearTimeout)
  }, [workDrafts, workInstructions])

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
    const files = Array.from(e.target.files || [])
    if (!files.length) return
    setImportResult(null)
    importMutation.mutate(files)
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
          style={{ maxWidth: 320, imeMode: 'active' }}
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
        <input ref={fileRef} type="file" accept=".xlsx,.xls" multiple style={{ display: 'none' }} onChange={handleFile} />
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
          就労支援荷受け
        </button>
      </div>

      {importResult && (
        <div className="card" style={{ borderLeft: importResult.unmatched ? '4px solid #d97706' : '4px solid #16a34a' }}>
          <div style={{ fontWeight: 600, marginBottom: 8 }}>
            取込完了{importResult.file_count > 1 ? `（${importResult.file_count}ファイル）` : ''}: 在庫 {importResult.imported}行 / 就労支援荷受け {importResult.work_imported ?? importResult.imported}行
            {importResult.unmatched > 0 && <span style={{ color: '#d97706' }}> / 未照合 {importResult.unmatched}行</span>}
            {importResult.skipped_items?.length > 0 && <span style={{ color: '#64748b' }}> / 既取込済 {importResult.skipped_items.length}行</span>}
          </div>

          {importResult.imported_items?.length > 0 && (
            <details open style={{ marginBottom: 8 }}>
              <summary style={{ cursor: 'pointer', color: '#16a34a', fontWeight: 600 }}>取込済み {importResult.imported_items.length}件</summary>
              <table style={{ marginTop: 6, fontSize: 12 }}>
                <thead><tr><th>SKU</th><th>商品名</th><th>数量</th><th>換算</th><th>残量変化</th><th>区分</th></tr></thead>
                <tbody>
                  {importResult.imported_items.map((item, i) => (
                    <tr key={i}>
                      <td style={{ fontWeight: 600 }}>{item.sku}</td>
                      <td>{item.name_jp}</td>
                      <td>{item.units}</td>
                      <td>{item.qty}</td>
                      <td>{item.before_qty} → <b>{item.after_qty}</b></td>
                      <td><span style={{
                        background: item.status === '新規' ? '#dcfce7' : '#e0f2fe',
                        padding: '2px 6px', borderRadius: 4, fontSize: 11, fontWeight: 600,
                        color: item.status === '新規' ? '#166534' : '#1e40af'
                      }}>{item.status}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          )}

          {importResult.skipped_items?.length > 0 && (
            <details style={{ marginBottom: 8 }}>
              <summary style={{ cursor: 'pointer', color: '#64748b', fontWeight: 600 }}>既取込済 {importResult.skipped_items.length}件</summary>
              <table style={{ marginTop: 6, fontSize: 12 }}>
                <thead><tr><th>SKU</th><th>商品名</th><th>数量</th><th>換算</th></tr></thead>
                <tbody>
                  {importResult.skipped_items.map((item, i) => (
                    <tr key={i} style={{ color: '#94a3b8' }}>
                      <td>{item.sku}</td>
                      <td>{item.name_jp}</td>
                      <td>{item.units}</td>
                      <td>{item.qty}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          )}

          {importResult.unmatched_items?.length > 0 && (
            <details style={{ marginBottom: 8 }}>
              <summary style={{ cursor: 'pointer', color: '#d97706', fontWeight: 600 }}>未照合 {importResult.unmatched_items.length}件</summary>
              <table style={{ marginTop: 6, fontSize: 12 }}>
                <thead><tr><th>シート</th><th>商品名</th><th>仕様</th><th>数量</th><th>URL</th></tr></thead>
                <tbody>
                  {importResult.unmatched_items.map((item, i) => (
                    <tr key={i}>
                      <td>{item.sheet}</td>
                      <td>{item.name_cn}</td>
                      <td>{item.supplier_spec}</td>
                      <td>{item.units}</td>
                      <td>{item.buy_url ? <a href={item.buy_url} target="_blank" rel="noreferrer" style={{ fontSize: 11 }}>URL</a> : '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          )}
        </div>
      )}

      {activeTab === 'inventory' && <div className="card">
        <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
          <button
            className={inventorySort === 'qty' ? 'btn-primary' : 'btn-secondary'}
            onClick={() => setInventorySort('qty')}
            style={{ padding: '4px 10px', fontSize: 12 }}
          >残量順</button>
          <button
            className={inventorySort === 'sku' ? 'btn-primary' : 'btn-secondary'}
            onClick={() => setInventorySort('sku')}
            style={{ padding: '4px 10px', fontSize: 12 }}
          >SKU順</button>
        </div>
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
                {items.map(item => {
                  const draft = inventoryDrafts[item.id] || {}
                  const { name_jp: itemName } = getInventoryDraftValue(item, draft)
                  return (
                    <tr key={item.id}>
                      <td style={{ fontWeight: 700 }}>{item.sku || '-'}</td>
                      <td>{imageThumb(item.image_data_url)}</td>
                      <td style={{ minWidth: 340 }}>
                        <input
                          value={itemName}
                          onChange={e => updateInventoryDraft(item, { name_jp: e.target.value })}
                          placeholder="日本語名"
                          style={{ width: '100%', minWidth: 300 }}
                        />
                      </td>
                      <td style={{ minWidth: 240 }}>
                        <div>{item.buy_url ? <a href={item.buy_url} target="_blank" rel="noreferrer">URL</a> : '-'}</div>
                        <div style={{ color: '#64748b', fontSize: 12 }}>{item.supplier_spec}</div>
                      </td>
                      <td>{item.total_received_units}</td>
                      <td style={item.unit_per_set !== item.product_unit_per_set ? { background: '#fef3c7', fontWeight: 700, borderRadius: 4 } : undefined}>
                        {item.unit_per_set}個で1
                        {item.unit_per_set !== item.product_unit_per_set && <span title={`商品マスタ: ${item.product_unit_per_set}個で1`}> ⚠</span>}
                      </td>
                      <td>{item.total_received_qty}</td>
                      <td style={{ minWidth: 120 }}>
                        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                          <input
                            type="number"
                            min="0"
                            value={remainingDrafts[item.id] ?? item.remaining_qty}
                            onChange={e => setRemainingDrafts(prev => ({ ...prev, [item.id]: Number(e.target.value) }))}
                            onFocus={e => e.target.select()}
                            onKeyDown={e => {
                              if (e.key === 'Enter' && (remainingDrafts[item.id] ?? item.remaining_qty) !== item.remaining_qty) {
                                adjustMutation.mutate({ id: item.id, remaining_qty: remainingDrafts[item.id] })
                              }
                            }}
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
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>}

      {activeTab === 'work' && <div className="card" style={{ padding: 12 }}>
        {workLoading ? (
          <div className="loading">読み込み中...</div>
        ) : workInstructions.length === 0 ? (
          <div className="empty-state">
            <p>就労支援荷受けがありません。Excelを取り込むと表示されます。</p>
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
            {checkedWorkIds.size > 0 && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', background: '#eff6ff', borderRadius: 8, marginBottom: 10 }}>
                <span style={{ fontSize: 13, fontWeight: 600 }}>{checkedWorkIds.size}件選択中</span>
                {WORK_INSTRUCTION_OPTIONS.map(opt => (
                  <button key={opt} className="btn btn-sm" style={{ fontSize: 12 }} onClick={() => {
                    const next = { ...workDrafts }
                    checkedWorkIds.forEach(id => { next[id] = { ...(next[id] || {}), instruction: opt } })
                    setWorkDrafts(next)
                    setCheckedWorkIds(new Set())
                  }}>{opt}</button>
                ))}
                <button className="btn btn-sm btn-secondary" style={{ fontSize: 12 }} onClick={() => setCheckedWorkIds(new Set())}>解除</button>
              </div>
            )}
            <div style={{ overflowX: 'auto' }}>
              <table className="welfare-work-table" style={{ width: 1200, minWidth: 1200 }}>
                <thead>
                  <tr>
                    <th style={{ width: 56 }}></th>
                    <th style={{ width: 58 }}>写真</th>
                    <th style={{ width: 240 }}>商品名</th>
                    <th style={{ width: 110 }}>色</th>
                    <th style={{ width: 80 }}>サイズ</th>
                    <th style={{ width: 52 }}>URL</th>
                    <th style={{ width: 64 }}>単品数</th>
                    <th style={{ width: 64 }}>換算</th>
                    <th style={{ width: 74 }}>残</th>
                    <th style={{ width: 36 }}>
                      <input type="checkbox"
                        checked={visibleWorkInstructions.length > 0 && visibleWorkInstructions.every(r => checkedWorkIds.has(r.id))}
                        onChange={e => {
                          if (e.target.checked) setCheckedWorkIds(new Set(visibleWorkInstructions.map(r => r.id)))
                          else setCheckedWorkIds(new Set())
                        }}
                      />
                    </th>
                    <th style={{ width: 126 }}>指示</th>
                    <th style={{ width: 180 }}>備考</th>
                    <th style={{ width: 90 }}>発注時間</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleWorkInstructions.map(row => {
                    const draft = workDrafts[row.id] || {}
                    const { source_product_name: productName, instruction, remaining_qty: remaining, note } = getWorkDraftValue(row, draft)
                    return (
                      <tr key={row.id}>
                        <td style={{ whiteSpace: 'nowrap' }}>
                          <button
                            className="btn btn-secondary btn-sm"
                            style={{ color: '#e11d48', padding: '5px 8px' }}
                            disabled={workDeleteMutation.isPending}
                            onClick={() => handleWorkDelete(row)}
                          >
                            削除
                          </button>
                        </td>
                        <td>{imageThumb(row.image_data_url)}</td>
                        <td style={{ padding: 6 }}>
                          <input
                            value={productName}
                            onChange={e => updateWorkDraft(row, { name_jp: e.target.value, source_product_name: e.target.value })}
                            placeholder="商品名"
                            style={{ width: '100%', minWidth: 0 }}
                          />
                        </td>
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
                            onChange={e => updateWorkDraft(row, { remaining_qty: Number(e.target.value) })}
                            style={{ width: 58, textAlign: 'right', fontWeight: 700 }}
                          />
                        </td>
                        <td>
                          <input type="checkbox" checked={checkedWorkIds.has(row.id)} onChange={e => {
                            const next = new Set(checkedWorkIds)
                            e.target.checked ? next.add(row.id) : next.delete(row.id)
                            setCheckedWorkIds(next)
                          }} />
                        </td>
                        <td style={{ ...instructionCellStyle(instruction), padding: 6 }}>
                          <input
                            list="work-instruction-options"
                            value={instruction}
                            onChange={e => updateWorkDraft(row, { instruction: e.target.value })}
                            style={{ width: 112, minWidth: 0, background: 'transparent', border: '1px solid #cbd5e1', borderRadius: 6 }}
                          />
                        </td>
                        <td>
                          <input
                            value={note}
                            onChange={e => updateWorkDraft(row, { note: e.target.value })}
                            placeholder="備考"
                          />
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

      {pendingWorkDeletes.length > 0 && (
        <div style={{
          position: 'fixed',
          right: 24,
          bottom: 24,
          zIndex: 260,
          display: 'grid',
          gap: 8,
          width: 'min(360px, calc(100vw - 48px))',
        }}>
          {pendingWorkDeletes.map(({ id, row }) => (
            <div key={id} style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 12,
              background: '#1f2937',
              color: '#fff',
              padding: '10px 12px',
              borderRadius: 8,
              boxShadow: '0 8px 30px rgba(15, 23, 42, 0.25)',
            }}>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 700, fontSize: 13 }}>削除しました</div>
                <div style={{ fontSize: 12, color: '#cbd5e1', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {row.name_jp || row.source_product_name || row.sku || '就労支援荷受け'}
                </div>
              </div>
              <button
                className="btn btn-sm"
                style={{ background: '#fff', color: '#111827', flex: '0 0 auto' }}
                onClick={() => undoWorkDelete(id)}
              >
                元に戻す
              </button>
            </div>
          ))}
        </div>
      )}

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
