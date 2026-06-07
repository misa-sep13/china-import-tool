import { useState, useEffect, useRef } from 'react'
import api from '../api/client'

const POLL_INTERVAL = 3000
const PERIODS = [
  { label: '1日', value: 1 },
  { label: '7日', value: 7 },
  { label: '30日', value: 30 },
  { label: '60日', value: 60 },
  { label: '90日', value: 90 },
]

const fmt = (n) => n == null ? '-' : Number(n).toLocaleString('ja-JP')
const fmtDate = (d) => `${d.getFullYear()}年${d.getMonth()+1}月${d.getDate()}日`
const periodLabel = (days) => {
  const end = new Date(); end.setDate(end.getDate() - 1)
  const start = new Date(end); start.setDate(start.getDate() - (days - 1))
  return `${fmtDate(start)} 〜 ${fmtDate(end)}`
}
const fmtRate = (n) => n == null ? '-' : `${n}%`
const yen = (n) => n == null ? '-' : `¥${Number(n).toLocaleString('ja-JP')}`

export default function AnalyticsPage() {
  const [period, setPeriod] = useState(30)
  const [jobStatus, setJobStatus] = useState('idle')
  const [jobElapsed, setJobElapsed] = useState(0)
  const [summary, setSummary] = useState(null)
  const [items, setItems] = useState([])
  const [error, setError] = useState('')
  const [sortKey, setSortKey] = useState('revenue')
  const [sortAsc, setSortAsc] = useState(false)
  const pollRef = useRef(null)

  const stopPolling = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }

  const startFetch = async (d = period, force = false) => {
    stopPolling()
    setJobStatus('running')
    setError('')
    setSummary(null)
    setItems([])
    try {
      const res = await api.post(`/analytics/start?days=${d}&force=${force}`)
      const id = res.data.job_id
      pollRef.current = setInterval(async () => {
        try {
          const st = await api.get(`/analytics/status/${id}`)
          setJobElapsed(st.data.elapsed)
          if (st.data.status === 'done') {
            stopPolling()
            setSummary(st.data.result?.summary || {})
            setItems(st.data.result?.items || [])
            setJobStatus('done')
          } else if (st.data.status === 'error') {
            stopPolling()
            setError(st.data.error || 'データ取得に失敗しました')
            setJobStatus('error')
          }
        } catch {
          stopPolling()
          setError('ステータス取得に失敗しました')
          setJobStatus('error')
        }
      }, POLL_INTERVAL)
    } catch {
      setJobStatus('error')
      setError('データ取得の開始に失敗しました')
    }
  }

  useEffect(() => {
    startFetch(period)
    return () => stopPolling()
  }, [])

  const handlePeriod = (d) => {
    setPeriod(d)
    startFetch(d, true)
  }

  const handleSort = (key) => {
    if (sortKey === key) setSortAsc(a => !a)
    else { setSortKey(key); setSortAsc(false) }
  }

  const sorted = [...items].sort((a, b) => {
    let va = a[sortKey] ?? -Infinity
    let vb = b[sortKey] ?? -Infinity
    return sortAsc ? va - vb : vb - va
  })

  const sortIcon = (key) => sortKey === key ? (sortAsc ? ' ▲' : ' ▼') : ''
  const th = (key, label) => (
    <th style={{ cursor: 'pointer', userSelect: 'none', whiteSpace: 'nowrap', background: sortKey === key ? '#f0f4ff' : undefined, textAlign: 'right' }}
      onClick={() => handleSort(key)}>
      {label}{sortIcon(key)}
    </th>
  )

  const isLoading = jobStatus === 'idle' || jobStatus === 'running'

  const profitColor = (rate) => {
    if (rate == null) return '#aaa'
    if (rate < 0) return '#dc2626'
    if (rate < 10) return '#f59e0b'
    return '#16a34a'
  }

  return (
    <div>
      <h1>📈 商品分析</h1>

      {/* コントロール */}
      <div className="card">
        <div className="top-actions" style={{ alignItems: 'center' }}>
          <div style={{ display: 'flex', gap: 6 }}>
            {PERIODS.map(p => (
              <button
                key={p.value}
                className={`btn ${period === p.value ? 'btn-primary' : 'btn-secondary'}`}
                style={{ padding: '4px 12px', fontSize: 13 }}
                onClick={() => handlePeriod(p.value)}
                disabled={isLoading}
              >{p.label}</button>
            ))}
          </div>
          <button className="btn btn-secondary" onClick={() => startFetch(period, true)} disabled={isLoading}>
            {isLoading ? '取得中...' : '🔄 再計算'}
          </button>
        </div>
        <div style={{ fontSize: 12, color: '#666', marginTop: 6 }}>
          集計期間: {periodLabel(period)}
        </div>
        {error && <p className="error-msg">{error}</p>}
      </div>

      {/* サマリー */}
      {summary && (
        <div className="card" style={{ display: 'flex', gap: 32, flexWrap: 'wrap', padding: '16px 24px' }}>
          <div>
            <div style={{ fontSize: 12, color: '#888', marginBottom: 4 }}>売上合計</div>
            <div style={{ fontSize: 22, fontWeight: 700 }}>{yen(summary.revenue)}</div>
          </div>
          <div>
            <div style={{ fontSize: 12, color: '#888', marginBottom: 4 }}>総販売数</div>
            <div style={{ fontSize: 22, fontWeight: 700 }}>{fmt(summary.units)} 個</div>
          </div>
          <div>
            <div style={{ fontSize: 12, color: '#888', marginBottom: 4 }}>粗利益</div>
            <div style={{ fontSize: 22, fontWeight: 700, color: summary.profit >= 0 ? '#16a34a' : '#dc2626' }}>
              {yen(summary.profit)}
            </div>
          </div>
          <div>
            <div style={{ fontSize: 12, color: '#888', marginBottom: 4 }}>粗利益率</div>
            <div style={{ fontSize: 22, fontWeight: 700, color: profitColor(summary.profit_rate) }}>
              {fmtRate(summary.profit_rate)}
            </div>
          </div>
        </div>
      )}

      {/* ローディング */}
      {isLoading && (
        <div className="card" style={{ textAlign: 'center', padding: 40 }}>
          <div style={{ fontSize: 32, marginBottom: 12 }}>⏳</div>
          <p style={{ fontWeight: 600, marginBottom: 8 }}>SP-APIからデータを取得中...</p>
          <p style={{ fontSize: 13, color: '#888' }}>売上・在庫データを集計しています。</p>
          {jobElapsed > 0 && <p style={{ fontSize: 13, color: '#aaa', marginTop: 8 }}>経過時間: {jobElapsed}秒</p>}
        </div>
      )}

      {/* テーブル */}
      {!isLoading && jobStatus === 'done' && (
        <div className="card">
          <h2>商品別分析（{items.length}件 / {period}日間）</h2>
          <div style={{ overflowX: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th style={{ minWidth: 60 }}>画像</th>
                  <th style={{ textAlign: 'left', minWidth: 200 }}>商品名</th>
                  <th style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>評価</th>
                  {th('units', '販売数')}
                  {th('revenue', '売上')}
                  {th('vine_revenue', 'VINE売上')}
                  {th('avg_price', '平均単価')}
                  {th('fba_fee', 'FBA手数料')}
                  {th('amazon_fee', 'Amazon手数料')}
                  {th('cost_jpy', '仕入原価')}
                  {th('profit', '粗利益')}
                  {th('profit_rate', '粗利益率')}
                  <th style={{ textAlign: 'right', whiteSpace: 'nowrap', color: '#aaa' }}>広告費※</th>
                  <th style={{ textAlign: 'right', whiteSpace: 'nowrap', color: '#aaa' }}>ACOS※</th>
                  <th style={{ textAlign: 'right', whiteSpace: 'nowrap', color: '#aaa' }}>ROAS※</th>
                  <th style={{ textAlign: 'right', whiteSpace: 'nowrap', color: '#aaa' }}>TACOS※</th>
                  <th style={{ textAlign: 'right', whiteSpace: 'nowrap', color: '#aaa' }}>インプレッション※</th>
                  <th style={{ textAlign: 'right', whiteSpace: 'nowrap', color: '#aaa' }}>クリック数※</th>
                  <th style={{ textAlign: 'right', whiteSpace: 'nowrap', color: '#aaa' }}>CTR※</th>
                  <th style={{ textAlign: 'right', whiteSpace: 'nowrap', color: '#aaa' }}>広告注文数※</th>
                  <th style={{ textAlign: 'right', whiteSpace: 'nowrap', color: '#aaa' }}>広告CVR※</th>
                  <th style={{ textAlign: 'right', whiteSpace: 'nowrap', color: '#aaa' }}>広告売上※</th>
                  <th style={{ textAlign: 'right', whiteSpace: 'nowrap', color: '#aaa' }}>広告売上率※</th>
                  {th('available', 'FBA在庫')}
                  {th('inbound', '納品中')}
                </tr>
              </thead>
              <tbody>
                {sorted.map(item => (
                  <tr key={item.product_id}>
                    <td style={{ textAlign: 'center' }}>
                      {item.photo_url
                        ? <img src={item.photo_url} alt="" style={{ width: 48, height: 48, objectFit: 'contain', borderRadius: 4 }} />
                        : <div style={{ width: 48, height: 48, background: '#f3f4f6', borderRadius: 4, display: 'inline-block' }} />
                      }
                    </td>
                    <td>
                      <a href={item.amazon_url} target="_blank" rel="noreferrer"
                        style={{ color: '#1a56db', fontSize: 13, textDecoration: 'none', display: 'block', maxWidth: 240, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {item.name}
                      </a>
                      <span style={{ fontSize: 11, color: '#888' }}>{item.sku}</span>
                      {(item.color || item.size) && (
                        <span style={{ fontSize: 11, color: '#888', marginLeft: 6 }}>{[item.color, item.size].filter(Boolean).join('/')}</span>
                      )}
                    </td>
                    <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                      {item.rating != null
                        ? <span style={{ fontWeight: 600 }}>★ {item.rating}{item.rating_count != null && <><br /><span style={{ fontSize: 11, color: '#888' }}>({fmt(item.rating_count)})</span></>}</span>
                        : <span style={{ color: '#aaa', fontSize: 12 }}>未追跡</span>
                      }
                    </td>
                    <td style={{ textAlign: 'right', fontWeight: 600 }}>{fmt(item.units)}</td>
                    <td style={{ textAlign: 'right', fontWeight: 600 }}>{yen(item.revenue)}</td>
                    <td style={{ textAlign: 'right', color: item.vine_revenue > 0 ? '#7c3aed' : '#bbb' }}>
                      {item.vine_revenue > 0 ? yen(item.vine_revenue) : '-'}
                    </td>
                    <td style={{ textAlign: 'right' }}>{yen(item.avg_price)}</td>
                    <td style={{ textAlign: 'right', color: '#555' }}>{yen(item.fba_fee)}</td>
                    <td style={{ textAlign: 'right', color: '#555' }}>{yen(item.amazon_fee)}</td>
                    <td style={{ textAlign: 'right', color: '#555' }}>{yen(item.cost_jpy)}</td>
                    <td style={{ textAlign: 'right', fontWeight: 600, color: item.profit >= 0 ? '#16a34a' : '#dc2626' }}>
                      {yen(item.profit)}
                    </td>
                    <td style={{ textAlign: 'right', fontWeight: 600, color: profitColor(item.profit_rate) }}>
                      {fmtRate(item.profit_rate)}
                    </td>
                    <td style={{ textAlign: 'right', color: '#aaa' }}>-</td>
                    <td style={{ textAlign: 'right', color: '#aaa' }}>-</td>
                    <td style={{ textAlign: 'right', color: '#aaa' }}>-</td>
                    <td style={{ textAlign: 'right', color: '#aaa' }}>-</td>
                    <td style={{ textAlign: 'right', color: '#aaa' }}>-</td>
                    <td style={{ textAlign: 'right', color: '#aaa' }}>-</td>
                    <td style={{ textAlign: 'right', color: '#aaa' }}>-</td>
                    <td style={{ textAlign: 'right', color: '#aaa' }}>-</td>
                    <td style={{ textAlign: 'right', color: '#aaa' }}>-</td>
                    <td style={{ textAlign: 'right', color: '#aaa' }}>-</td>
                    <td style={{ textAlign: 'right', color: '#aaa' }}>-</td>
                    <td style={{ textAlign: 'right' }}>{fmt(item.available)}</td>
                    <td style={{ textAlign: 'right', color: item.inbound > 0 ? '#2563eb' : '#bbb' }}>
                      {item.inbound > 0 ? fmt(item.inbound) : '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p style={{ fontSize: 12, color: '#aaa', marginTop: 12 }}>※ 広告関連指標はAmazon Ads API連携後に表示されます</p>
        </div>
      )}
    </div>
  )
}
