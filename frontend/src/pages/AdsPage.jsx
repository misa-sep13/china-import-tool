import { useState, useEffect, useRef } from 'react'
import api from '../api/client'

const POLL_INTERVAL = 2000
const TABS = ['campaigns', 'keywords', 'search-terms', 'proposals']
const TAB_LABELS = { campaigns: 'キャンペーン', keywords: 'KWパフォーマンス', 'search-terms': '検索語句', proposals: '提案一覧' }
const PROPOSAL_TABS = [
  ['phrase_promotions', 'P追加'],
  ['product_promotions', 'G追加'],
  ['exact_promotions', 'E追加'],
  ['bid_adjustments', '入札調整'],
  ['budget_adjustments', '予算調整'],
  ['new_campaigns', '新規候補'],
  ['excluded', '除外'],
]
const PROPOSAL_LABELS = Object.fromEntries(PROPOSAL_TABS)
const TYPE_COLORS = { 'A_': '#3b82f6', 'P_': '#eab308', 'G_': '#22c55e', 'E_': '#a855f7', other: '#94a3b8' }
const TYPE_FILTERS = ['全て', 'A_', 'P_', 'G_', 'E_', 'other']

const dateInput = (date) => {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

const defaultSyncRange = () => {
  const end = new Date()
  end.setDate(end.getDate() - 1)
  const start = new Date(end)
  start.setDate(start.getDate() - 13)
  return { start: dateInput(start), end: dateInput(end) }
}

const fmt = (n) => n == null ? '-' : Number(n).toLocaleString('ja-JP')
const yen = (n) => n == null ? '-' : `¥${Number(n).toLocaleString('ja-JP')}`
const pct = (n) => n == null ? '-' : `${n}%`
const acosColor = (v) => {
  if (v == null) return {}
  if (v > 30) return { color: '#dc2626' }
  if (v > 15) return { color: '#d97706' }
  return { color: '#16a34a' }
}

export default function AdsPage() {
  const initialRange = defaultSyncRange()
  const [tab, setTab] = useState('campaigns')
  const [proposalTab, setProposalTab] = useState('phrase_promotions')
  const [typeFilter, setTypeFilter] = useState('全て')
  const [search, setSearch] = useState('')
  const [syncStartDate, setSyncStartDate] = useState(initialRange.start)
  const [syncEndDate, setSyncEndDate] = useState(initialRange.end)
  const [attributionDays, setAttributionDays] = useState('14')
  const [syncStatus, setSyncStatus] = useState('idle')
  const [syncProgress, setSyncProgress] = useState('')
  const [dashboard, setDashboard] = useState(null)
  const [data, setData] = useState([])
  const [proposalData, setProposalData] = useState(null)
  const [budgetProposalData, setBudgetProposalData] = useState(null)
  const [sortKey, setSortKey] = useState('cost')
  const [sortAsc, setSortAsc] = useState(false)
  const [error, setError] = useState('')
  const pollRef = useRef(null)

  const stopPolling = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }

  const loadDashboard = async () => {
    try {
      const res = await api.get('/ads/dashboard')
      setDashboard(res.data)
    } catch { /* ignore */ }
  }

  const loadTab = async () => {
    try {
      if (tab === 'proposals') {
        const res = await api.get('/ads/proposals')
        setProposalData(res.data)
        return
      }
      const params = new URLSearchParams()
      if (typeFilter !== '全て') params.set('campaign_type', typeFilter)
      if (search) params.set('search', search)
      const url = `/ads/${tab}?${params}`
      const res = await api.get(url)
      setData(res.data)
    } catch (e) {
      setError('データ取得に失敗しました')
    }
  }

  useEffect(() => {
    loadDashboard()
  }, [])

  useEffect(() => {
    loadTab()
  }, [tab, typeFilter])

  const startSync = async ({ days = 30, startDate = '', endDate = '', attribution = 30 } = {}) => {
    stopPolling()
    setSyncStatus('running')
    setSyncProgress('開始')
    setError('')
    try {
      const params = new URLSearchParams()
      if (startDate && endDate) {
        params.set('start_date', startDate)
        params.set('end_date', endDate)
      } else {
        params.set('days', String(days))
      }
      params.set('attribution_days', String(attribution))
      const res = await api.post(`/ads/sync/start?${params.toString()}`)
      const jobId = res.data.job_id
      pollRef.current = setInterval(async () => {
        try {
          const s = await api.get(`/ads/sync/status/${jobId}`)
          setSyncProgress(s.data.progress || '')
          if (s.data.status === 'done') {
            stopPolling()
            setSyncStatus('idle')
            loadDashboard()
            loadTab()
          } else if (s.data.status === 'error') {
            stopPolling()
            setSyncStatus('idle')
            setError(s.data.error || '同期エラー')
          }
        } catch {
          stopPolling()
          setSyncStatus('idle')
        }
      }, POLL_INTERVAL)
    } catch (e) {
      setSyncStatus('idle')
      setError('同期開始に失敗しました')
    }
  }

  useEffect(() => () => stopPolling(), [])

  const handleSearch = (e) => {
    e.preventDefault()
    loadTab()
  }

  const handleBudgetCsv = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setError('')
    try {
      const csvText = await file.text()
      const res = await api.post('/ads/proposals/budget-csv', { csv_text: csvText })
      setBudgetProposalData(res.data)
      setProposalTab('budget_adjustments')
    } catch {
      setError('予算CSVの読み込みに失敗しました')
    }
  }

  const sorted = [...data].sort((a, b) => {
    const av = a[sortKey], bv = b[sortKey]
    if (av == null && bv == null) return 0
    if (av == null) return 1
    if (bv == null) return -1
    return sortAsc ? (av > bv ? 1 : -1) : (av < bv ? 1 : -1)
  })

  const toggleSort = (key) => {
    if (sortKey === key) setSortAsc(!sortAsc)
    else { setSortKey(key); setSortAsc(false) }
  }
  const sortIcon = (key) => sortKey === key ? (sortAsc ? ' ▲' : ' ▼') : ''
  const proposalRows = proposalTab === 'budget_adjustments'
    ? (budgetProposalData?.budget_adjustments || proposalData?.budget_adjustments || [])
    : (proposalData?.[proposalTab] || [])
  const budgetCount = budgetProposalData?.summary?.budget_adjust ?? proposalData?.summary?.budget_adjust ?? 0
  const budgetUp = budgetProposalData?.summary?.budget_up ?? 0
  const budgetDown = budgetProposalData?.summary?.budget_down ?? 0
  const proposalCounts = proposalData?.summary ? {
    p_add: proposalData.summary.p_add || 0,
    g_add: proposalData.summary.g_add || 0,
    e_add: proposalData.summary.e_add || 0,
    bid_adjust: proposalData.summary.bid_adjust || 0,
    budget_adjust: budgetCount,
    new_campaigns: proposalData.summary.new_campaigns || 0,
    excluded: proposalData.summary.excluded || 0,
  } : {}
  const promotionTotal = (proposalCounts.p_add || 0) + (proposalCounts.g_add || 0) + (proposalCounts.e_add || 0)

  const downloadProposalCsv = () => {
    if (!proposalRows.length) return
    const headers = Array.from(proposalRows.reduce((set, row) => {
      Object.keys(row).forEach(k => set.add(k))
      return set
    }, new Set()))
    const esc = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`
    const body = [headers.join(','), ...proposalRows.map(row => headers.map(h => esc(row[h])).join(','))].join('\n')
    const blob = new Blob([`\ufeff${body}`], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `ads_${proposalTab}_audit.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  const TypeBadge = ({ type }) => (
    <span style={{
      background: TYPE_COLORS[type] || TYPE_COLORS.other,
      color: '#fff', padding: '2px 8px', borderRadius: 4, fontSize: 12, fontWeight: 600,
    }}>{type}</span>
  )

  const StateBadge = ({ state }) => {
    const colors = { ENABLED: '#16a34a', PAUSED: '#d97706', ARCHIVED: '#94a3b8' }
    return (
      <span style={{
        color: colors[state] || '#64748b', fontWeight: 600, fontSize: 12,
      }}>{state}</span>
    )
  }

  return (
    <div style={{ padding: 24 }}>
      {/* ヘッダー */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0, color: '#1e293b' }}>📢 広告管理</h1>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {dashboard?.last_synced_at && (
            <span style={{ fontSize: 12, color: '#64748b' }}>
              最終同期: {new Date(dashboard.last_synced_at).toLocaleString('ja-JP')}
            </span>
          )}
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
            <input
              type="date"
              value={syncStartDate}
              onChange={e => setSyncStartDate(e.target.value)}
              disabled={syncStatus === 'running'}
              style={{ padding: '7px 8px', border: '1px solid #cbd5e1', borderRadius: 6, fontSize: 13 }}
            />
            <span style={{ color: '#64748b' }}>〜</span>
            <input
              type="date"
              value={syncEndDate}
              onChange={e => setSyncEndDate(e.target.value)}
              disabled={syncStatus === 'running'}
              style={{ padding: '7px 8px', border: '1px solid #cbd5e1', borderRadius: 6, fontSize: 13 }}
            />
            <select
              value={attributionDays}
              onChange={e => setAttributionDays(e.target.value)}
              disabled={syncStatus === 'running'}
              style={{ padding: '7px 8px', border: '1px solid #cbd5e1', borderRadius: 6, fontSize: 13 }}
            >
              <option value="7">7日CV</option>
              <option value="14">14日CV</option>
              <option value="30">30日CV</option>
            </select>
            <button
              onClick={() => startSync({
                startDate: syncStartDate,
                endDate: syncEndDate,
                attribution: Number(attributionDays),
              })}
              disabled={syncStatus === 'running'}
              style={{
                padding: '8px 12px', background: syncStatus === 'running' ? '#94a3b8' : '#0f766e',
                color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontWeight: 600,
              }}
            >
              指定期間で同期
            </button>
          </div>
          <button
            onClick={() => startSync({ days: 30, attribution: Number(attributionDays) })}
            disabled={syncStatus === 'running'}
            style={{
              padding: '8px 16px', background: syncStatus === 'running' ? '#94a3b8' : '#3b82f6',
              color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontWeight: 600,
            }}
          >
            {syncStatus === 'running' ? `🔄 ${syncProgress}...` : '🔄 データ同期（30日）'}
          </button>
        </div>
      </div>

      {error && <div style={{ background: '#fef2f2', color: '#dc2626', padding: 12, borderRadius: 6, marginBottom: 16 }}>{error}</div>}

      {/* サマリーカード */}
      {dashboard?.summary && (
        <div style={{ display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap' }}>
          {['A_', 'P_', 'G_', 'E_'].map(ct => {
            const s = dashboard.summary[ct]
            if (!s) return null
            return (
              <div key={ct} style={{
                flex: '1 1 200px', background: '#fff', border: '1px solid #e2e8f0',
                borderRadius: 8, padding: 16, borderTop: `3px solid ${TYPE_COLORS[ct]}`,
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <TypeBadge type={ct} />
                  <span style={{ fontSize: 12, color: '#64748b' }}>{s.count}件</span>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4, fontSize: 13 }}>
                  <span style={{ color: '#64748b' }}>費用</span>
                  <span style={{ textAlign: 'right', fontWeight: 600 }}>{yen(Math.round(s.cost))}</span>
                  <span style={{ color: '#64748b' }}>売上</span>
                  <span style={{ textAlign: 'right', fontWeight: 600 }}>{yen(Math.round(s.sales))}</span>
                  <span style={{ color: '#64748b' }}>ACOS</span>
                  <span style={{ textAlign: 'right', fontWeight: 600, ...acosColor(s.acos) }}>{pct(s.acos)}</span>
                  <span style={{ color: '#64748b' }}>ROAS</span>
                  <span style={{ textAlign: 'right', fontWeight: 600 }}>{s.roas != null ? `${s.roas}x` : '-'}</span>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* タブバー */}
      <div style={{ display: 'flex', gap: 0, borderBottom: '2px solid #e2e8f0', marginBottom: 16 }}>
        {TABS.map(t => (
          <button key={t} onClick={() => { setTab(t); setSortKey('cost'); setSortAsc(false) }}
            style={{
              padding: '10px 20px', border: 'none', background: 'none', cursor: 'pointer',
              fontWeight: tab === t ? 700 : 400, fontSize: 14, color: tab === t ? '#1e293b' : '#64748b',
              borderBottom: tab === t ? '2px solid #3b82f6' : '2px solid transparent',
              marginBottom: -2,
            }}
          >{TAB_LABELS[t]}</button>
        ))}
      </div>

      {/* フィルタ */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12, flexWrap: 'wrap' }}>
        {(tab === 'campaigns' || tab === 'keywords') && TYPE_FILTERS.map(tf => (
          <button key={tf} onClick={() => setTypeFilter(tf)}
            style={{
              padding: '4px 12px', borderRadius: 16, border: '1px solid',
              borderColor: typeFilter === tf ? '#3b82f6' : '#cbd5e1',
              background: typeFilter === tf ? '#eff6ff' : '#fff',
              color: typeFilter === tf ? '#1d4ed8' : '#334155',
              cursor: 'pointer', fontSize: 13, fontWeight: typeFilter === tf ? 600 : 400,
            }}
          >{tf}</button>
        ))}
        <form onSubmit={handleSearch} style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
          <input value={search} onChange={e => setSearch(e.target.value)}
            placeholder="検索..." style={{ padding: '6px 12px', border: '1px solid #cbd5e1', borderRadius: 6, fontSize: 13 }}
          />
          <button type="submit" style={{ padding: '6px 12px', background: '#f1f5f9', border: '1px solid #cbd5e1', borderRadius: 6, cursor: 'pointer', fontSize: 13 }}>🔍</button>
        </form>
      </div>

      {tab === 'proposals' && proposalData?.summary && (
        <div style={{ marginBottom: 12, border: '1px solid #dbeafe', background: '#fff' }}>
          <div style={{
            padding: '10px 14px', borderBottom: '1px solid #dbeafe',
            fontWeight: 700, color: '#0369a1', borderLeft: '4px solid #38bdf8',
          }}>
            結果
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', padding: '12px 14px 8px' }}>
            {[
              ['p_add', 'P追加'], ['g_add', 'G追加'], ['e_add', 'E追加'],
              ['bid_adjust', '入札調整'], ['budget_adjust', '予算調整'],
              ['new_campaigns', '新規候補'], ['excluded', '除外'],
            ].map(([key, label]) => (
              <button key={key} onClick={() => {
                const map = {
                  p_add: 'phrase_promotions',
                  g_add: 'product_promotions',
                  e_add: 'exact_promotions',
                  bid_adjust: 'bid_adjustments',
                  budget_adjust: 'budget_adjustments',
                  new_campaigns: 'new_campaigns',
                  excluded: 'excluded',
                }
                setProposalTab(map[key])
              }} style={{
                background: '#eff6ff', border: '1px solid #bfdbfe', borderRadius: 6,
                padding: '8px 12px', fontSize: 13, fontWeight: 600, color: '#1e3a8a',
                cursor: 'pointer',
              }}>
                {label}: {fmt(proposalCounts[key] || 0)}件
                {key === 'bid_adjust' && `（上げ${fmt(proposalData.summary.bid_up || 0)} / 下げ${fmt(proposalData.summary.bid_down || 0)}）`}
                {key === 'budget_adjust' && budgetProposalData?.summary && `（上げ${fmt(budgetUp)} / 下げ${fmt(budgetDown)}）`}
              </button>
            ))}
            <label style={{
              marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 8,
              padding: '7px 10px', border: '1px solid #cbd5e1', borderRadius: 6,
              background: '#fff', cursor: 'pointer', fontSize: 13,
            }}>
              予算CSV
              <input type="file" accept=".csv,text/csv" onChange={handleBudgetCsv} style={{ display: 'none' }} />
            </label>
            <button onClick={downloadProposalCsv} disabled={!proposalRows.length} style={{
              padding: '7px 12px', border: 'none', borderRadius: 6,
              background: proposalRows.length ? '#2563eb' : '#cbd5e1',
              color: '#fff', cursor: proposalRows.length ? 'pointer' : 'default', fontWeight: 600,
            }}>
              監査CSV
            </button>
          </div>
          <div style={{
            background: '#ecfdf5', borderTop: '1px solid #bbf7d0', borderBottom: '1px solid #bbf7d0',
            padding: '9px 14px', color: '#166534', fontSize: 13,
          }}>
            合計 昇格{fmt(promotionTotal)}件 / 入札調整{fmt(proposalCounts.bid_adjust || 0)}件を抽出しました。
          </div>
          <div style={{ display: 'flex', gap: 4, padding: '10px 14px 0', borderBottom: '1px solid #bfdbfe', flexWrap: 'wrap' }}>
            {PROPOSAL_TABS.map(([key, label]) => (
              <button key={key} onClick={() => setProposalTab(key)}
                style={{
                  padding: '7px 12px', border: '1px solid #bfdbfe',
                  borderBottom: proposalTab === key ? '1px solid #fff' : '1px solid #bfdbfe',
                  background: proposalTab === key ? '#fff' : '#e0f2fe',
                  color: '#0f172a', cursor: 'pointer', borderRadius: '6px 6px 0 0',
                  fontWeight: proposalTab === key ? 700 : 500, fontSize: 13,
                }}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* テーブル */}
      <div style={{ overflowX: 'auto' }}>
        {tab === 'campaigns' && (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ background: '#f8fafc', position: 'sticky', top: 0 }}>
                {[
                  ['name', '名前'], ['campaign_type', '種別'], ['state', '状態'],
                  ['budget_amount', '予算'], ['cost', '費用'], ['sales', '売上'],
                  ['acos', 'ACOS'], ['roas', 'ROAS'], ['clicks', 'Click'],
                  ['impressions', 'Imp'], ['ctr', 'CTR'], ['cvr', 'CVR'],
                ].map(([k, l]) => (
                  <th key={k} onClick={() => toggleSort(k)}
                    style={{ padding: '8px 10px', textAlign: k === 'name' ? 'left' : 'right', cursor: 'pointer', whiteSpace: 'nowrap', borderBottom: '2px solid #e2e8f0', color: '#475569', fontWeight: 600 }}
                  >{l}{sortIcon(k)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map(c => (
                <tr key={c.campaign_id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                  <td style={{ padding: '8px 10px', maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.name}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right' }}><TypeBadge type={c.campaign_type} /></td>
                  <td style={{ padding: '8px 10px', textAlign: 'right' }}><StateBadge state={c.state} /></td>
                  <td style={{ padding: '8px 10px', textAlign: 'right' }}>{yen(c.budget_amount)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', fontWeight: 600 }}>{yen(c.cost)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', fontWeight: 600 }}>{yen(c.sales)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', fontWeight: 600, ...acosColor(c.acos) }}>{pct(c.acos)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right' }}>{c.roas != null ? `${c.roas}x` : '-'}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right' }}>{fmt(c.clicks)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right' }}>{fmt(c.impressions)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right' }}>{pct(c.ctr)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right' }}>{pct(c.cvr)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {tab === 'keywords' && (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ background: '#f8fafc', position: 'sticky', top: 0 }}>
                {[
                  ['keyword_text', 'キーワード'], ['match_type', 'マッチ'], ['campaign_name', 'キャンペーン'],
                  ['bid', '入札額'], ['clicks', 'Click'], ['cost', '費用'],
                  ['orders', 'CV'], ['sales', '売上'], ['acos', 'ACOS'], ['cpc', 'CPC'], ['cvr', 'CVR'],
                ].map(([k, l]) => (
                  <th key={k} onClick={() => toggleSort(k)}
                    style={{ padding: '8px 10px', textAlign: ['keyword_text', 'match_type', 'campaign_name'].includes(k) ? 'left' : 'right', cursor: 'pointer', whiteSpace: 'nowrap', borderBottom: '2px solid #e2e8f0', color: '#475569', fontWeight: 600 }}
                  >{l}{sortIcon(k)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map(kw => (
                <tr key={kw.keyword_id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                  <td style={{ padding: '8px 10px', maxWidth: 240, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{kw.keyword_text}</td>
                  <td style={{ padding: '8px 10px', fontSize: 12 }}>{kw.match_type}</td>
                  <td style={{ padding: '8px 10px', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 12 }}>
                    {kw.campaign_type && <TypeBadge type={kw.campaign_type} />} {kw.campaign_name}
                  </td>
                  <td style={{ padding: '8px 10px', textAlign: 'right' }}>{yen(kw.bid)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right' }}>{fmt(kw.clicks)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', fontWeight: 600 }}>{yen(kw.cost)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', fontWeight: 600 }}>{fmt(kw.orders)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', fontWeight: 600 }}>{yen(kw.sales)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', fontWeight: 600, ...acosColor(kw.acos) }}>{pct(kw.acos)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right' }}>{yen(kw.cpc)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right' }}>{pct(kw.cvr)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {tab === 'search-terms' && (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ background: '#f8fafc', position: 'sticky', top: 0 }}>
                {[
                  ['search_term', '検索語句'], ['campaign_name', 'キャンペーン'],
                  ['impressions', 'Imp'], ['clicks', 'Click'], ['cost', '費用'],
                  ['orders', 'CV'], ['sales', '売上'], ['acos', 'ACOS'],
                ].map(([k, l]) => (
                  <th key={k} onClick={() => toggleSort(k)}
                    style={{ padding: '8px 10px', textAlign: ['search_term', 'campaign_name'].includes(k) ? 'left' : 'right', cursor: 'pointer', whiteSpace: 'nowrap', borderBottom: '2px solid #e2e8f0', color: '#475569', fontWeight: 600 }}
                  >{l}{sortIcon(k)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((st, i) => (
                <tr key={i} style={{ borderBottom: '1px solid #f1f5f9' }}>
                  <td style={{ padding: '8px 10px', maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{st.search_term}</td>
                  <td style={{ padding: '8px 10px', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 12 }}>{st.campaign_name}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right' }}>{fmt(st.impressions)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right' }}>{fmt(st.clicks)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', fontWeight: 600 }}>{yen(st.cost)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', fontWeight: 600 }}>{fmt(st.orders)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', fontWeight: 600 }}>{yen(st.sales)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', fontWeight: 600, ...acosColor(st.acos) }}>{pct(st.acos)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {tab === 'proposals' && (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              {['phrase_promotions', 'exact_promotions'].includes(proposalTab) && (
                <tr style={{ background: '#f8fafc' }}>
                  {['元', '追加先キャンペーン', 'キーワード', '一致', '入札額', '元CPC', 'CV', 'ACOS', '元キャンペーン', '新規'].map(h => (
                    <th key={h} style={{ padding: '8px 10px', textAlign: ['入札額', '元CPC', 'CV', 'ACOS'].includes(h) ? 'right' : 'left', borderBottom: '2px solid #e2e8f0', color: '#475569' }}>{h}</th>
                  ))}
                </tr>
              )}
              {proposalTab === 'product_promotions' && (
                <tr style={{ background: '#f8fafc' }}>
                  {['元', '追加先キャンペーン', 'ターゲットASIN', '入札額', '元CPC', 'CV', 'ACOS', '元キャンペーン', '新規'].map(h => (
                    <th key={h} style={{ padding: '8px 10px', textAlign: ['入札額', '元CPC', 'CV', 'ACOS'].includes(h) ? 'right' : 'left', borderBottom: '2px solid #e2e8f0', color: '#475569' }}>{h}</th>
                  ))}
                </tr>
              )}
              {proposalTab === 'bid_adjustments' && (
                <tr style={{ background: '#f8fafc' }}>
                  {['キャンペーン', '種別', '対象', '現入札', '新入札', '増減', 'Click', 'CV', 'ACOS', 'CPC', '適用ルール'].map(h => (
                    <th key={h} style={{ padding: '8px 10px', textAlign: ['現入札', '新入札', '増減', 'Click', 'CV', 'ACOS', 'CPC'].includes(h) ? 'right' : 'left', borderBottom: '2px solid #e2e8f0', color: '#475569' }}>{h}</th>
                  ))}
                </tr>
              )}
              {proposalTab === 'new_campaigns' && (
                <tr style={{ background: '#f8fafc' }}>
                  {['作成先', 'キャンペーン名', 'SKU', '予算', '初期入札', '関連候補'].map(h => (
                    <th key={h} style={{ padding: '8px 10px', textAlign: ['予算', '初期入札', '関連候補'].includes(h) ? 'right' : 'left', borderBottom: '2px solid #e2e8f0', color: '#475569' }}>{h}</th>
                  ))}
                </tr>
              )}
              {proposalTab === 'excluded' && (
                <tr style={{ background: '#f8fafc' }}>
                  {['元キャンペーン', '検索語句', '昇格先', 'CV', 'ACOS', '除外理由'].map(h => (
                    <th key={h} style={{ padding: '8px 10px', textAlign: ['CV', 'ACOS'].includes(h) ? 'right' : 'left', borderBottom: '2px solid #e2e8f0', color: '#475569' }}>{h}</th>
                  ))}
                </tr>
              )}
              {proposalTab === 'budget_adjustments' && (
                <tr style={{ background: '#f8fafc' }}>
                  {['キャンペーン', '現予算', '新予算', '増減', 'ACOS', '適用ルール'].map(h => (
                    <th key={h} style={{ padding: '8px 10px', textAlign: ['現予算', '新予算', '増減', 'ACOS'].includes(h) ? 'right' : 'left', borderBottom: '2px solid #e2e8f0', color: '#475569' }}>{h}</th>
                  ))}
                </tr>
              )}
            </thead>
            <tbody>
              {['phrase_promotions', 'exact_promotions'].includes(proposalTab) && proposalRows.map((r, i) => (
                <tr key={i} style={{ borderBottom: '1px solid #f1f5f9' }}>
                  <td style={{ padding: '8px 10px' }}><TypeBadge type={r.source_type} /></td>
                  <td style={{ padding: '8px 10px' }}>{r.campaign}</td>
                  <td style={{ padding: '8px 10px' }}>{r.keyword}</td>
                  <td style={{ padding: '8px 10px' }}>{r.match_type}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', fontWeight: 600 }}>{yen(r.bid)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right' }}>{yen(r.source_cpc)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right' }}>{fmt(r.orders)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', ...acosColor(r.acos) }}>{pct(r.acos)}</td>
                  <td style={{ padding: '8px 10px', fontSize: 12 }}>{r.source_campaign}</td>
                  <td style={{ padding: '8px 10px' }}>{r.needs_campaign ? '要' : ''}</td>
                </tr>
              ))}
              {proposalTab === 'product_promotions' && proposalRows.map((r, i) => (
                <tr key={i} style={{ borderBottom: '1px solid #f1f5f9' }}>
                  <td style={{ padding: '8px 10px' }}><TypeBadge type={r.source_type} /></td>
                  <td style={{ padding: '8px 10px' }}>{r.campaign}</td>
                  <td style={{ padding: '8px 10px' }}>{r.target_asin}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', fontWeight: 600 }}>{yen(r.bid)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right' }}>{yen(r.source_cpc)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right' }}>{fmt(r.orders)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', ...acosColor(r.acos) }}>{pct(r.acos)}</td>
                  <td style={{ padding: '8px 10px', fontSize: 12 }}>{r.source_campaign}</td>
                  <td style={{ padding: '8px 10px' }}>{r.needs_campaign ? '要' : ''}</td>
                </tr>
              ))}
              {proposalTab === 'bid_adjustments' && proposalRows.map((r, i) => (
                <tr key={i} style={{ borderBottom: '1px solid #f1f5f9' }}>
                  <td style={{ padding: '8px 10px', maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.campaign}</td>
                  <td style={{ padding: '8px 10px' }}>{r.kind}</td>
                  <td style={{ padding: '8px 10px', maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.target}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right' }}>{yen(r.current_bid)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', fontWeight: 600 }}>{yen(r.new_bid)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', color: r.delta > 0 ? '#15803d' : '#dc2626' }}>{r.delta > 0 ? '+' : ''}{r.delta}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right' }}>{fmt(r.clicks)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right' }}>{fmt(r.orders)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', ...acosColor(r.acos) }}>{pct(r.acos)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right' }}>{yen(r.cpc)}</td>
                  <td style={{ padding: '8px 10px', fontSize: 12 }}>{r.rule}</td>
                </tr>
              ))}
              {proposalTab === 'new_campaigns' && proposalRows.map((r, i) => (
                <tr key={i} style={{ borderBottom: '1px solid #f1f5f9' }}>
                  <td style={{ padding: '8px 10px', fontWeight: 600 }}>{r.create_type}</td>
                  <td style={{ padding: '8px 10px' }}>{r.campaign}</td>
                  <td style={{ padding: '8px 10px' }}>{r.sku}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right' }}>{yen(r.budget)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right' }}>{yen(r.initial_bid)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right' }}>{fmt(r.related_count)}</td>
                </tr>
              ))}
              {proposalTab === 'budget_adjustments' && proposalRows.map((r, i) => (
                <tr key={i} style={{ borderBottom: '1px solid #f1f5f9' }}>
                  <td style={{ padding: '8px 10px' }}>{r.campaign}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right' }}>{yen(r.current_budget)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', fontWeight: 600 }}>{yen(r.new_budget)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', color: r.delta > 0 ? '#15803d' : '#dc2626' }}>{r.delta > 0 ? '+' : ''}{yen(r.delta)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', ...acosColor(r.acos) }}>{pct(r.acos)}</td>
                  <td style={{ padding: '8px 10px' }}>{r.rule}</td>
                </tr>
              ))}
              {proposalTab === 'excluded' && proposalRows.map((r, i) => (
                <tr key={i} style={{ borderBottom: '1px solid #f1f5f9' }}>
                  <td style={{ padding: '8px 10px', maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.source_campaign}</td>
                  <td style={{ padding: '8px 10px' }}>{r.search_term}</td>
                  <td style={{ padding: '8px 10px' }}>{r.destination}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right' }}>{fmt(r.orders)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', ...acosColor(r.acos) }}>{pct(r.acos)}</td>
                  <td style={{ padding: '8px 10px' }}>{r.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {tab !== 'proposals' && data.length === 0 && syncStatus !== 'running' && (
        <div style={{ textAlign: 'center', padding: 40, color: '#94a3b8' }}>
          データがありません。「データ同期」ボタンで取得してください。
        </div>
      )}
      {tab === 'proposals' && proposalRows.length === 0 && syncStatus !== 'running' && (
        <div style={{ textAlign: 'center', padding: 40, color: '#94a3b8' }}>
          {PROPOSAL_LABELS[proposalTab]}はありません。
        </div>
      )}
    </div>
  )
}
