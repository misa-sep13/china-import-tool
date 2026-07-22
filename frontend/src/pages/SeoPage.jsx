import { useState, useEffect, useCallback } from 'react'

const API = import.meta.env.VITE_API_URL || ''

export default function SeoPage() {
  const [dates, setDates] = useState([])
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [checking, setChecking] = useState(false)
  const [checkResult, setCheckResult] = useState(null)
  const [days, setDays] = useState(14)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({ keyword: '', product_sku: '', product_name: '', memo: '' })
  const [editId, setEditId] = useState(null)
  const [keywords, setKeywords] = useState([])
  const [showManage, setShowManage] = useState(false)

  const fetchMatrix = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API}/seo/rankings/matrix?days=${days}`)
      const data = await res.json()
      setDates(data.dates || [])
      setRows(data.rows || [])
    } catch { /* ignore */ }
    setLoading(false)
  }, [days])

  const fetchKeywords = useCallback(async () => {
    const res = await fetch(`${API}/seo/keywords?active_only=false`)
    const data = await res.json()
    setKeywords(data.keywords || [])
  }, [])

  useEffect(() => { fetchMatrix() }, [fetchMatrix])

  const handleCheckAll = async () => {
    setChecking(true)
    setCheckResult(null)
    try {
      const res = await fetch(`${API}/seo/check`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
      })
      const data = await res.json()
      setCheckResult(data)
      fetchMatrix()
    } catch (e) {
      setCheckResult({ error: e.message })
    }
    setChecking(false)
  }

  const handleSave = async () => {
    if (!form.keyword.trim()) return
    if (editId) {
      await fetch(`${API}/seo/keywords/${editId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      })
    } else {
      await fetch(`${API}/seo/keywords`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      })
    }
    setForm({ keyword: '', product_sku: '', product_name: '', memo: '' })
    setEditId(null)
    setShowForm(false)
    fetchKeywords()
    fetchMatrix()
  }

  const handleDelete = async (id) => {
    if (!confirm('このキーワードを削除しますか？')) return
    await fetch(`${API}/seo/keywords/${id}`, { method: 'DELETE' })
    fetchKeywords()
    fetchMatrix()
  }

  const handleToggleActive = async (kw) => {
    await fetch(`${API}/seo/keywords/${kw.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_active: !kw.is_active }),
    })
    fetchKeywords()
    fetchMatrix()
  }

  const openManage = () => {
    fetchKeywords()
    setShowManage(true)
  }

  const grouped = groupBySku(rows)
  const displayDates = dates.slice(0, days)

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
        <h2 style={{ margin: 0 }}>SEO順位マトリクス</h2>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <select value={days} onChange={e => setDays(Number(e.target.value))} style={selectStyle}>
            <option value={7}>7日間</option>
            <option value={14}>14日間</option>
            <option value={30}>30日間</option>
            <option value={90}>90日間</option>
          </select>
          <button onClick={handleCheckAll} disabled={checking} style={btnPrimary}>
            {checking ? 'チェック中...' : '全順位チェック'}
          </button>
          <button onClick={openManage} style={btnSecondary}>キーワード管理</button>
        </div>
      </div>

      {checkResult && !checkResult.error && (
        <div style={{ ...card, background: '#f0fdf4', border: '1px solid #86efac', marginBottom: 16 }}>
          <b>チェック完了</b>（{checkResult.checked_at?.split('T')[0]}）
          — {checkResult.results?.length}件チェック済み
        </div>
      )}
      {checkResult?.error && (
        <div style={{ ...card, background: '#fef2f2', border: '1px solid #fca5a5', marginBottom: 16 }}>
          エラー: {checkResult.error}
        </div>
      )}

      <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 8, display: 'flex', gap: 16, alignItems: 'center' }}>
        <span>{rows.length} キーワード</span>
        <span>{displayDates.length} 日分</span>
        <span style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span style={{ ...rankBadge(1), display: 'inline-block', width: 12, height: 12, borderRadius: 2 }}></span> 1-10位
          <span style={{ ...rankBadge(15), display: 'inline-block', width: 12, height: 12, borderRadius: 2 }}></span> 11-30位
          <span style={{ ...rankBadge(50), display: 'inline-block', width: 12, height: 12, borderRadius: 2 }}></span> 31位+
          <span style={{ background: '#f3f4f6', display: 'inline-block', width: 12, height: 12, borderRadius: 2, border: '1px solid #e5e7eb' }}></span> 圏外
        </span>
      </div>

      {loading ? (
        <div style={{ padding: 40, textAlign: 'center', color: '#9ca3af' }}>読み込み中...</div>
      ) : rows.length === 0 ? (
        <div style={{ padding: 40, textAlign: 'center', color: '#9ca3af' }}>
          キーワードを登録してください
        </div>
      ) : (
        <div style={{ overflowX: 'auto', border: '1px solid #e5e7eb', borderRadius: 8 }}>
          <table style={{ borderCollapse: 'collapse', fontSize: 13, whiteSpace: 'nowrap', width: '100%' }}>
            <thead>
              <tr>
                <th style={stickyThFirst}>SKU</th>
                <th style={stickyThSecond}>キーワード</th>
                {displayDates.map(d => (
                  <th key={d} style={dateTh}>{formatDate(d)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {grouped.map(group => (
                group.items.map((row, idx) => (
                  <tr key={row.keyword_id} style={{ borderBottom: idx === group.items.length - 1 ? '2px solid #e5e7eb' : undefined }}>
                    {idx === 0 && (
                      <td style={skuCell} rowSpan={group.items.length}>
                        {group.sku || '-'}
                      </td>
                    )}
                    <td style={kwCell} title={row.product_name}>
                      {row.keyword}
                    </td>
                    {displayDates.map(d => {
                      const rank = row.ranks[d]
                      return (
                        <td key={d} style={rankCellStyle(rank)}>
                          {rank != null ? rank : '-'}
                        </td>
                      )
                    })}
                  </tr>
                ))
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* キーワード管理モーダル */}
      {showManage && (
        <div style={overlay} onClick={() => setShowManage(false)}>
          <div style={modal} onClick={e => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <h3 style={{ margin: 0 }}>キーワード管理 ({keywords.length}件)</h3>
              <div style={{ display: 'flex', gap: 8 }}>
                <button onClick={() => { setShowForm(true); setEditId(null); setForm({ keyword: '', product_sku: '', product_name: '', memo: '' }) }} style={btnPrimary}>
                  + 追加
                </button>
                <button onClick={() => setShowManage(false)} style={btnSecondary}>閉じる</button>
              </div>
            </div>

            {showForm && (
              <div style={{ ...card, marginBottom: 16 }}>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 8 }}>
                  <label style={labelStyle}>
                    検索キーワード *
                    <input value={form.keyword} onChange={e => setForm({ ...form, keyword: e.target.value })} style={inputStyle} />
                  </label>
                  <label style={labelStyle}>
                    商品SKU
                    <input value={form.product_sku} onChange={e => setForm({ ...form, product_sku: e.target.value })} style={inputStyle} />
                  </label>
                  <label style={labelStyle}>
                    商品名
                    <input value={form.product_name} onChange={e => setForm({ ...form, product_name: e.target.value })} style={inputStyle} />
                  </label>
                  <label style={labelStyle}>
                    メモ
                    <input value={form.memo} onChange={e => setForm({ ...form, memo: e.target.value })} style={inputStyle} />
                  </label>
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button onClick={handleSave} style={btnPrimary}>保存</button>
                  <button onClick={() => { setShowForm(false); setEditId(null) }} style={btnSecondary}>キャンセル</button>
                </div>
              </div>
            )}

            <div style={{ maxHeight: 400, overflowY: 'auto' }}>
              <table style={{ ...tableStyle, fontSize: 13 }}>
                <thead>
                  <tr>
                    <th style={thStyle}>キーワード</th>
                    <th style={thStyle}>SKU</th>
                    <th style={thStyle}>状態</th>
                    <th style={thStyle}>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {keywords.map(kw => (
                    <tr key={kw.id} style={{ opacity: kw.is_active ? 1 : 0.5 }}>
                      <td style={tdStyle}>{kw.keyword}</td>
                      <td style={tdStyle}>{kw.product_sku || '-'}</td>
                      <td style={tdStyle}>{kw.is_active ? '有効' : '無効'}</td>
                      <td style={tdStyle}>
                        <div style={{ display: 'flex', gap: 4 }}>
                          <button onClick={() => { setForm({ keyword: kw.keyword, product_sku: kw.product_sku || '', product_name: kw.product_name || '', memo: kw.memo || '' }); setEditId(kw.id); setShowForm(true) }} style={btnSmall}>編集</button>
                          <button onClick={() => handleToggleActive(kw)} style={btnSmall}>
                            {kw.is_active ? '無効化' : '有効化'}
                          </button>
                          <button onClick={() => handleDelete(kw.id)} style={{ ...btnSmall, color: '#dc2626' }}>削除</button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function groupBySku(rows) {
  const groups = []
  const map = {}
  for (const row of rows) {
    const sku = row.product_sku || ''
    if (!map[sku]) {
      map[sku] = { sku, items: [] }
      groups.push(map[sku])
    }
    map[sku].items.push(row)
  }
  return groups
}

function formatDate(dateStr) {
  const d = new Date(dateStr + 'T00:00:00')
  return `${d.getMonth() + 1}/${d.getDate()}`
}

function rankBadge(rank) {
  if (rank == null) return { background: '#f3f4f6', color: '#9ca3af' }
  if (rank <= 10) return { background: '#dcfce7', color: '#15803d' }
  if (rank <= 30) return { background: '#fef9c3', color: '#a16207' }
  return { background: '#fee2e2', color: '#dc2626' }
}

function rankCellStyle(rank) {
  const badge = rankBadge(rank)
  return {
    padding: '4px 8px',
    textAlign: 'center',
    fontWeight: rank != null ? 700 : 400,
    fontSize: 12,
    ...badge,
    borderRight: '1px solid #f3f4f6',
    borderBottom: '1px solid #f3f4f6',
  }
}

const card = { background: '#fff', borderRadius: 8, padding: 16, border: '1px solid #e5e7eb' }
const btnPrimary = { background: '#2563eb', color: '#fff', border: 'none', borderRadius: 6, padding: '8px 16px', cursor: 'pointer', fontWeight: 600, fontSize: 13 }
const btnSecondary = { background: '#f1f5f9', color: '#334155', border: '1px solid #cbd5e1', borderRadius: 6, padding: '8px 16px', cursor: 'pointer', fontSize: 13 }
const btnSmall = { background: '#f1f5f9', border: '1px solid #cbd5e1', borderRadius: 4, padding: '2px 8px', cursor: 'pointer', fontSize: 12 }
const selectStyle = { border: '1px solid #d1d5db', borderRadius: 6, padding: '6px 10px', fontSize: 13 }
const inputStyle = { border: '1px solid #d1d5db', borderRadius: 6, padding: '6px 10px', fontSize: 14, width: '100%', boxSizing: 'border-box' }
const labelStyle = { fontSize: 13, color: '#374151', display: 'flex', flexDirection: 'column', gap: 4 }
const tableStyle = { width: '100%', borderCollapse: 'collapse', fontSize: 14 }
const thStyle = { textAlign: 'left', padding: '8px 10px', borderBottom: '2px solid #e5e7eb', color: '#6b7280', fontWeight: 600, fontSize: 12 }
const tdStyle = { padding: '6px 10px', borderBottom: '1px solid #f3f4f6' }

const stickyThFirst = {
  position: 'sticky', left: 0, background: '#f9fafb', zIndex: 2,
  padding: '6px 10px', textAlign: 'left', fontWeight: 600, fontSize: 12,
  color: '#6b7280', borderBottom: '2px solid #e5e7eb', borderRight: '1px solid #e5e7eb',
  minWidth: 60,
}
const stickyThSecond = {
  position: 'sticky', left: 60, background: '#f9fafb', zIndex: 2,
  padding: '6px 10px', textAlign: 'left', fontWeight: 600, fontSize: 12,
  color: '#6b7280', borderBottom: '2px solid #e5e7eb', borderRight: '1px solid #e5e7eb',
  minWidth: 140,
}
const dateTh = {
  padding: '6px 8px', textAlign: 'center', fontWeight: 600, fontSize: 11,
  color: '#6b7280', borderBottom: '2px solid #e5e7eb', borderRight: '1px solid #f3f4f6',
  minWidth: 48,
}
const skuCell = {
  position: 'sticky', left: 0, background: '#f9fafb', zIndex: 1,
  padding: '4px 10px', fontWeight: 600, fontSize: 12, color: '#374151',
  borderRight: '1px solid #e5e7eb', verticalAlign: 'top', minWidth: 60,
}
const kwCell = {
  position: 'sticky', left: 60, background: '#fff', zIndex: 1,
  padding: '4px 10px', fontSize: 12, color: '#374151',
  borderRight: '1px solid #e5e7eb', borderBottom: '1px solid #f3f4f6',
  maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis',
  minWidth: 140,
}
const overlay = {
  position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
  background: 'rgba(0,0,0,0.4)', zIndex: 100, display: 'flex',
  alignItems: 'center', justifyContent: 'center',
}
const modal = {
  background: '#fff', borderRadius: 12, padding: 24,
  maxWidth: 800, width: '90%', maxHeight: '80vh', overflow: 'auto',
}
