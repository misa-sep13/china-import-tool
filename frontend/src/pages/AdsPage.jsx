import { useState, useEffect, useRef } from 'react'
import api from '../api/client'

const POLL_INTERVAL = 2000
const TABS = ['campaigns', 'keywords', 'search-terms']
const TAB_LABELS = { campaigns: 'キャンペーン', keywords: 'KWパフォーマンス', 'search-terms': '検索語句' }
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
  const [typeFilter, setTypeFilter] = useState('全て')
  const [search, setSearch] = useState('')
  const [syncStartDate, setSyncStartDate] = useState(initialRange.start)
  const [syncEndDate, setSyncEndDate] = useState(initialRange.end)
  const [attributionDays, setAttributionDays] = useState('30')
  const [syncStatus, setSyncStatus] = useState('idle')
  const [syncProgress, setSyncProgress] = useState('')
  const [dashboard, setDashboard] = useState(null)
  const [data, setData] = useState([])
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
      </div>

      {data.length === 0 && syncStatus !== 'running' && (
        <div style={{ textAlign: 'center', padding: 40, color: '#94a3b8' }}>
          データがありません。「データ同期」ボタンで取得してください。
        </div>
      )}
    </div>
  )
}
