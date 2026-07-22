import { useState, useEffect, useCallback } from 'react'

const API = import.meta.env.VITE_API_URL || ''

export default function SeoPage() {
  const [keywords, setKeywords] = useState([])
  const [latestRankings, setLatestRankings] = useState({})
  const [history, setHistory] = useState([])
  const [selectedKwId, setSelectedKwId] = useState(null)
  const [checking, setChecking] = useState(false)
  const [checkResult, setCheckResult] = useState(null)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({ keyword: '', product_sku: '', product_name: '', memo: '' })
  const [editId, setEditId] = useState(null)
  const [testKeyword, setTestKeyword] = useState('')
  const [testResult, setTestResult] = useState(null)
  const [testLoading, setTestLoading] = useState(false)

  const fetchKeywords = useCallback(async () => {
    const res = await fetch(`${API}/seo/keywords?active_only=false`)
    const data = await res.json()
    setKeywords(data.keywords || [])
  }, [])

  const fetchLatestRankings = useCallback(async () => {
    const res = await fetch(`${API}/seo/rankings`)
    const data = await res.json()
    const map = {}
    for (const r of data.rankings || []) {
      if (!map[r.seo_keyword_id]) map[r.seo_keyword_id] = []
      map[r.seo_keyword_id].push(r)
    }
    setLatestRankings(map)
  }, [])

  useEffect(() => { fetchKeywords(); fetchLatestRankings() }, [fetchKeywords, fetchLatestRankings])

  const fetchHistory = async (kwId) => {
    setSelectedKwId(kwId)
    const res = await fetch(`${API}/seo/rankings/${kwId}?days=90`)
    const data = await res.json()
    setHistory(data.rankings || [])
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
  }

  const handleEdit = (kw) => {
    setForm({ keyword: kw.keyword, product_sku: kw.product_sku || '', product_name: kw.product_name || '', memo: kw.memo || '' })
    setEditId(kw.id)
    setShowForm(true)
  }

  const handleDelete = async (id) => {
    if (!confirm('このキーワードを削除しますか？')) return
    await fetch(`${API}/seo/keywords/${id}`, { method: 'DELETE' })
    fetchKeywords()
  }

  const handleToggleActive = async (kw) => {
    await fetch(`${API}/seo/keywords/${kw.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_active: !kw.is_active }),
    })
    fetchKeywords()
  }

  const handleCheckAll = async () => {
    setChecking(true)
    setCheckResult(null)
    try {
      const res = await fetch(`${API}/seo/check`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      const data = await res.json()
      setCheckResult(data)
      fetchLatestRankings()
      if (selectedKwId) fetchHistory(selectedKwId)
    } catch (e) {
      setCheckResult({ error: e.message })
    }
    setChecking(false)
  }

  const handleCheckSingle = async (kwId) => {
    setChecking(true)
    try {
      const res = await fetch(`${API}/seo/check`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ keyword_ids: [kwId] }),
      })
      await res.json()
      fetchLatestRankings()
      if (selectedKwId === kwId) fetchHistory(kwId)
    } catch { /* ignore */ }
    setChecking(false)
  }

  const handleTestSearch = async () => {
    if (!testKeyword.trim()) return
    setTestLoading(true)
    setTestResult(null)
    try {
      const res = await fetch(`${API}/seo/check-single`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ keyword: testKeyword }),
      })
      setTestResult(await res.json())
    } catch (e) {
      setTestResult({ error: e.message })
    }
    setTestLoading(false)
  }

  const groupByDate = (rankings) => {
    const groups = {}
    for (const r of rankings) {
      const date = r.checked_at ? r.checked_at.split('T')[0] : 'unknown'
      if (!groups[date]) groups[date] = []
      groups[date].push(r)
    }
    return Object.entries(groups).sort((a, b) => b[0].localeCompare(a[0]))
  }

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>SEO順位チェッカー</h2>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={handleCheckAll} disabled={checking} style={btnPrimary}>
            {checking ? 'チェック中...' : '全キーワード順位チェック'}
          </button>
          <button onClick={() => { setShowForm(true); setEditId(null); setForm({ keyword: '', product_sku: '', product_name: '', memo: '' }) }} style={btnSecondary}>
            + キーワード追加
          </button>
        </div>
      </div>

      {checkResult && !checkResult.error && (
        <div style={{ ...card, background: '#f0fdf4', border: '1px solid #86efac', marginBottom: 16 }}>
          <b>チェック完了</b>（{checkResult.checked_at?.split('T')[0]}）
          {checkResult.results?.map((r, i) => (
            <div key={i} style={{ marginTop: 4 }}>
              「{r.keyword}」: {r.ranks?.length ? r.ranks.map(rk => `${rk.rank}位(${rk.card_type})`).join(', ') : '圏外'}
              {r.error && <span style={{ color: '#dc2626' }}> エラー: {r.error}</span>}
            </div>
          ))}
        </div>
      )}

      {showForm && (
        <div style={{ ...card, marginBottom: 16 }}>
          <h3 style={{ margin: '0 0 12px' }}>{editId ? 'キーワード編集' : 'キーワード追加'}</h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 8 }}>
            <label style={labelStyle}>
              検索キーワード *
              <input value={form.keyword} onChange={e => setForm({ ...form, keyword: e.target.value })} style={inputStyle} placeholder="スマホケース 手帳型" />
            </label>
            <label style={labelStyle}>
              商品SKU
              <input value={form.product_sku} onChange={e => setForm({ ...form, product_sku: e.target.value })} style={inputStyle} placeholder="y60" />
            </label>
            <label style={labelStyle}>
              商品名
              <input value={form.product_name} onChange={e => setForm({ ...form, product_name: e.target.value })} style={inputStyle} placeholder="手帳型ケース" />
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

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {/* 左: キーワード一覧 */}
        <div>
          <h3>登録キーワード</h3>
          <table style={tableStyle}>
            <thead>
              <tr>
                <th style={thStyle}>キーワード</th>
                <th style={thStyle}>SKU</th>
                <th style={thStyle}>最新順位</th>
                <th style={thStyle}>操作</th>
              </tr>
            </thead>
            <tbody>
              {keywords.map(kw => {
                const ranks = latestRankings[kw.id] || []
                const best = ranks.length ? Math.min(...ranks.map(r => r.rank).filter(Boolean)) : null
                return (
                  <tr key={kw.id} style={{
                    cursor: 'pointer',
                    background: selectedKwId === kw.id ? '#eff6ff' : kw.is_active ? undefined : '#f9fafb',
                    opacity: kw.is_active ? 1 : 0.5,
                  }} onClick={() => fetchHistory(kw.id)}>
                    <td style={tdStyle}>
                      {kw.keyword}
                      {kw.product_name && <span style={{ color: '#6b7280', fontSize: 12, marginLeft: 4 }}>({kw.product_name})</span>}
                    </td>
                    <td style={tdStyle}>{kw.product_sku || '-'}</td>
                    <td style={{ ...tdStyle, fontWeight: 700, color: best ? (best <= 10 ? '#16a34a' : best <= 30 ? '#ca8a04' : '#dc2626') : '#9ca3af' }}>
                      {best ? `${best}位` : ranks.length ? '圏外' : '-'}
                      {ranks.length > 0 && ranks[0].checked_at && (
                        <span style={{ color: '#9ca3af', fontWeight: 400, fontSize: 11, marginLeft: 4 }}>
                          {ranks[0].checked_at.split('T')[0]}
                        </span>
                      )}
                    </td>
                    <td style={tdStyle} onClick={e => e.stopPropagation()}>
                      <div style={{ display: 'flex', gap: 4 }}>
                        <button onClick={() => handleCheckSingle(kw.id)} disabled={checking} style={btnSmall} title="順位チェック">🔍</button>
                        <button onClick={() => handleEdit(kw)} style={btnSmall} title="編集">✏️</button>
                        <button onClick={() => handleToggleActive(kw)} style={btnSmall} title={kw.is_active ? '無効化' : '有効化'}>
                          {kw.is_active ? '⏸️' : '▶️'}
                        </button>
                        <button onClick={() => handleDelete(kw.id)} style={{ ...btnSmall, color: '#dc2626' }} title="削除">🗑️</button>
                      </div>
                    </td>
                  </tr>
                )
              })}
              {!keywords.length && (
                <tr><td colSpan={4} style={{ ...tdStyle, textAlign: 'center', color: '#9ca3af' }}>キーワードを追加してください</td></tr>
              )}
            </tbody>
          </table>

          {/* テスト検索 */}
          <div style={{ ...card, marginTop: 16 }}>
            <h3 style={{ margin: '0 0 8px' }}>テスト検索</h3>
            <div style={{ display: 'flex', gap: 8 }}>
              <input value={testKeyword} onChange={e => setTestKeyword(e.target.value)} style={{ ...inputStyle, flex: 1 }}
                placeholder="キーワードを入力" onKeyDown={e => e.key === 'Enter' && handleTestSearch()} />
              <button onClick={handleTestSearch} disabled={testLoading} style={btnPrimary}>
                {testLoading ? '検索中...' : '検索'}
              </button>
            </div>
            {testResult && !testResult.error && (
              <div style={{ marginTop: 8 }}>
                <div style={{ color: '#6b7280', fontSize: 13 }}>
                  「{testResult.keyword}」全{testResult.total_items?.toLocaleString()}件
                </div>
                {testResult.my_ranks?.length ? (
                  testResult.my_ranks.map((r, i) => (
                    <div key={i} style={{ marginTop: 4, fontWeight: 700 }}>
                      {r.rank}位 (p{r.page}, {r.card_type === 'cpc' ? 'PR' : 'organic'})
                    </div>
                  ))
                ) : (
                  <div style={{ marginTop: 4, color: '#9ca3af' }}>圏外（5ページ以内に見つかりませんでした）</div>
                )}
              </div>
            )}
            {testResult?.error && <div style={{ marginTop: 8, color: '#dc2626' }}>エラー: {testResult.error}</div>}
          </div>
        </div>

        {/* 右: 順位履歴 */}
        <div>
          <h3>順位履歴 {selectedKwId && keywords.find(k => k.id === selectedKwId) && (
            <span style={{ fontWeight: 400, color: '#6b7280' }}>
              — 「{keywords.find(k => k.id === selectedKwId)?.keyword}」
            </span>
          )}</h3>
          {selectedKwId ? (
            history.length ? (
              <div>
                {/* 簡易チャート */}
                <RankChart data={history} />
                <table style={tableStyle}>
                  <thead>
                    <tr>
                      <th style={thStyle}>日時</th>
                      <th style={thStyle}>順位</th>
                      <th style={thStyle}>ページ</th>
                      <th style={thStyle}>種別</th>
                      <th style={thStyle}>総件数</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.map(r => (
                      <tr key={r.id}>
                        <td style={tdStyle}>{r.checked_at?.replace('T', ' ').slice(0, 16)}</td>
                        <td style={{ ...tdStyle, fontWeight: 700, color: r.rank ? (r.rank <= 10 ? '#16a34a' : r.rank <= 30 ? '#ca8a04' : '#dc2626') : '#9ca3af' }}>
                          {r.rank ? `${r.rank}位` : '圏外'}
                        </td>
                        <td style={tdStyle}>{r.page || '-'}</td>
                        <td style={tdStyle}>{r.card_type === 'cpc' ? 'PR' : r.card_type === 'item' ? 'organic' : r.card_type || '-'}</td>
                        <td style={tdStyle}>{r.total_items?.toLocaleString() || '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div style={{ color: '#9ca3af', padding: 24, textAlign: 'center' }}>履歴がありません</div>
            )
          ) : (
            <div style={{ color: '#9ca3af', padding: 24, textAlign: 'center' }}>キーワードを選択してください</div>
          )}
        </div>
      </div>
    </div>
  )
}

function RankChart({ data }) {
  if (!data.length) return null
  const ranked = data.filter(d => d.rank).sort((a, b) => (a.checked_at || '').localeCompare(b.checked_at || ''))
  if (!ranked.length) return null

  const W = 600, H = 150, PAD = 40
  const maxRank = Math.max(...ranked.map(d => d.rank), 50)
  const minDate = new Date(ranked[0].checked_at)
  const maxDate = new Date(ranked[ranked.length - 1].checked_at)
  const dateRange = Math.max(maxDate - minDate, 1)

  const points = ranked.map(d => {
    const x = PAD + ((new Date(d.checked_at) - minDate) / dateRange) * (W - PAD * 2)
    const y = PAD + ((d.rank - 1) / (maxRank - 1)) * (H - PAD * 2)
    return { x, y, rank: d.rank, date: d.checked_at?.split('T')[0] }
  })

  const polyline = points.map(p => `${p.x},${p.y}`).join(' ')

  return (
    <div style={{ ...card, marginBottom: 12, overflow: 'auto' }}>
      <svg width={W} height={H} style={{ display: 'block' }}>
        <text x={PAD - 4} y={PAD} textAnchor="end" fontSize={10} fill="#6b7280">1</text>
        <text x={PAD - 4} y={H - PAD} textAnchor="end" fontSize={10} fill="#6b7280">{maxRank}</text>
        <line x1={PAD} y1={PAD} x2={PAD} y2={H - PAD} stroke="#e5e7eb" />
        <line x1={PAD} y1={H - PAD} x2={W - PAD} y2={H - PAD} stroke="#e5e7eb" />
        <polyline points={polyline} fill="none" stroke="#3b82f6" strokeWidth={2} />
        {points.map((p, i) => (
          <g key={i}>
            <circle cx={p.x} cy={p.y} r={3} fill="#3b82f6" />
            <title>{p.date}: {p.rank}位</title>
          </g>
        ))}
        <text x={PAD} y={H - 4} fontSize={9} fill="#9ca3af">{points[0]?.date}</text>
        <text x={W - PAD} y={H - 4} fontSize={9} fill="#9ca3af" textAnchor="end">{points[points.length - 1]?.date}</text>
      </svg>
      <div style={{ fontSize: 11, color: '#9ca3af', textAlign: 'center' }}>順位推移（上が1位 / 下が{maxRank}位）</div>
    </div>
  )
}

const card = { background: '#fff', borderRadius: 8, padding: 16, border: '1px solid #e5e7eb' }
const btnPrimary = { background: '#2563eb', color: '#fff', border: 'none', borderRadius: 6, padding: '8px 16px', cursor: 'pointer', fontWeight: 600 }
const btnSecondary = { background: '#f1f5f9', color: '#334155', border: '1px solid #cbd5e1', borderRadius: 6, padding: '8px 16px', cursor: 'pointer' }
const btnSmall = { background: 'none', border: 'none', cursor: 'pointer', padding: '2px 4px', fontSize: 14 }
const inputStyle = { border: '1px solid #d1d5db', borderRadius: 6, padding: '6px 10px', fontSize: 14, width: '100%', boxSizing: 'border-box' }
const labelStyle = { fontSize: 13, color: '#374151', display: 'flex', flexDirection: 'column', gap: 4 }
const tableStyle = { width: '100%', borderCollapse: 'collapse', fontSize: 14 }
const thStyle = { textAlign: 'left', padding: '8px 10px', borderBottom: '2px solid #e5e7eb', color: '#6b7280', fontWeight: 600, fontSize: 12 }
const tdStyle = { padding: '8px 10px', borderBottom: '1px solid #f3f4f6' }
