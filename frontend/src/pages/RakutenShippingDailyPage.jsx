import { useCallback, useEffect, useState } from 'react'
import api from '../api/client'

/**
 * 楽天の1日ぶんの発送件数と売上金額。
 *
 * 日付は「発送日」。注文日ではない。実際に出した日で並べたい、という用途。
 * 受注APIから数えるので時間がかかる。一度数えた日はサーバーに溜めてあり、
 * 見るだけなら待たずに出る。
 */

const C = {
  line: '#e5e7eb', sub: '#64748b', text: '#0f172a',
  good: '#16a34a', warn: '#b45309', bad: '#dc2626', key: '#2563eb',
}

const th = {
  padding: '6px 10px', fontSize: 11, color: C.sub, background: '#f8fafc',
  whiteSpace: 'nowrap',
}
const td = {
  padding: '5px 10px', fontSize: 13, borderTop: `1px solid ${C.line}`,
  whiteSpace: 'nowrap',
}
const num = { ...td, textAlign: 'right' }

const yen = (v) => `¥${Math.round(v || 0).toLocaleString()}`
const WEEK = ['日', '月', '火', '水', '木', '金', '土']

export default function RakutenShippingDailyPage() {
  const [from, setFrom] = useState('2025-07-01')
  const [to, setTo] = useState(() => new Date().toLocaleDateString('sv-SE'))
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [job, setJob] = useState(null)
  const [view, setView] = useState('month')   // month / day

  const load = useCallback(async () => {
    setErr('')
    try {
      const r = await api.get('/rakuten/shipping-daily',
        { params: { date_from: from, date_to: to } })
      setData(r.data)
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    }
  }, [from, to])

  useEffect(() => { load() }, [load])

  // 取り込みは月ごとに順に進む。終わるまで様子を見に行く
  useEffect(() => {
    if (!job?.job_id || job.status === 'done' || job.status === 'error') return
    const t = setTimeout(async () => {
      try {
        const r = await api.get(`/rakuten/shipping-daily/import/${job.job_id}`)
        setJob({ ...r.data, job_id: job.job_id })
        if (r.data.status === 'done') { setBusy(false); load() }
        if (r.data.status === 'error') { setBusy(false); setErr(r.data.error) }
      } catch { /* 次の回で拾う */ }
    }, 3000)
    return () => clearTimeout(t)
  }, [job, load])

  const runImport = async () => {
    if (!window.confirm(
      `${from} 〜 ${to} を受注APIから数え直します。\n`
      + '月ごとに順に取りに行くので、1年ぶんだと10分ほどかかります。\n'
      + 'この画面を開いたままにしてください。')) return
    setBusy(true); setErr(''); setJob(null)
    try {
      const r = await api.post('/rakuten/shipping-daily/import', null,
        { params: { date_from: from, date_to: to } })
      setJob({ ...r.data, status: 'running' })
    } catch (e) {
      setBusy(false)
      setErr(e.response?.data?.detail || e.message)
    }
  }

  const t = data?.total

  return (
    <div style={{ padding: 2, minWidth: 0 }}>
      <h2 style={{ fontSize: 18, marginBottom: 4 }}>📦 楽天 発送と売上（日ごと）</h2>
      <div style={{ fontSize: 12, color: C.sub, marginBottom: 12 }}>
        その日に発送した件数と、その注文の売上金額です。注文日ではなく発送日で並べています。
      </div>

      {err && (
        <div style={{
          background: '#fef2f2', border: '1px solid #fecaca', color: '#991b1b',
          padding: 10, borderRadius: 6, marginBottom: 10, fontSize: 13,
        }}>{err}</div>
      )}

      <div className="card" style={{ marginBottom: 12, display: 'flex', gap: 10,
        alignItems: 'center', flexWrap: 'wrap' }}>
        <label style={{ fontSize: 12, color: C.sub }}>
          期間
          <input type="date" value={from} onChange={e => setFrom(e.target.value)}
            style={{ marginLeft: 4, fontSize: 12, width: 140 }} />
        </label>
        <span style={{ color: C.sub }}>〜</span>
        <input type="date" value={to} onChange={e => setTo(e.target.value)}
          style={{ fontSize: 12, width: 140 }} />
        <button className="btn btn-secondary btn-sm" onClick={load} disabled={busy}>
          表示
        </button>
        <button className="btn btn-primary btn-sm" onClick={runImport} disabled={busy}>
          {busy ? '取り込み中…' : '📥 受注APIから数え直す'}
        </button>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
          {[['month', '月ごと'], ['day', '日ごと']].map(([v, l]) => (
            <button key={v} className="btn btn-sm" onClick={() => setView(v)}
              style={{ fontSize: 12,
                background: view === v ? '#2563eb' : '#f1f5f9',
                color: view === v ? '#fff' : '#334155',
                border: `1px solid ${view === v ? '#2563eb' : C.line}` }}>
              {l}
            </button>
          ))}
        </div>
      </div>

      {busy && job && (
        <div style={{ marginBottom: 12, fontSize: 13, padding: '8px 10px',
          borderRadius: 6, background: '#eff6ff', border: '1px solid #bfdbfe',
          color: '#1e40af' }}>
          取り込み中… {job.done_months || 0}/{job.total_months || '?'}か月
          {job.now && `（${job.now}）`}
          　{job.saved || 0}日ぶんを保存しました
        </div>
      )}

      {t && (
        <div className="card" style={{ marginBottom: 12, display: 'flex',
          gap: 24, flexWrap: 'wrap' }}>
          <Stat label="発送した注文" value={`${t.order_count.toLocaleString()}件`} />
          <Stat label="送付先の数" value={`${t.package_count.toLocaleString()}件`} />
          <Stat label="売上（請求金額）" value={yen(t.total_price)} big />
          <Stat label="うち商品代" value={yen(t.goods_price)} />
        </div>
      )}

      {data && view === 'month' && (
        <Table
          head={['月', '日数', '発送した注文', '送付先', '売上（請求）', '商品代', '1日あたり']}
          rows={(data.months || []).map(m => [
            m.month, `${m.days}日`, `${m.order_count.toLocaleString()}件`,
            `${m.package_count.toLocaleString()}件`,
            yen(m.total_price), yen(m.goods_price),
            m.days ? yen(m.total_price / m.days) : '—',
          ])}
        />
      )}

      {data && view === 'day' && (
        <Table
          head={['日', '曜', '発送した注文', '送付先', '売上（請求）', '商品代']}
          rows={(data.days || []).map(d => {
            const dt = new Date(d.day + 'T00:00:00')
            return [
              d.day, WEEK[dt.getDay()],
              `${d.order_count.toLocaleString()}件`,
              `${d.package_count.toLocaleString()}件`,
              yen(d.total_price), yen(d.goods_price),
            ]
          })}
        />
      )}

      {data && (data.days || []).length === 0 && (
        <div style={{ fontSize: 13, color: C.sub, padding: 20 }}>
          この期間のデータがまだありません。
          「📥 受注APIから数え直す」を押すと、楽天から取ってきます。
        </div>
      )}
    </div>
  )
}

function Stat({ label, value, big }) {
  return (
    <div>
      <div style={{ fontSize: 11, color: C.sub }}>{label}</div>
      <div style={{ fontSize: big ? 22 : 17, fontWeight: 700,
        color: big ? C.good : C.text }}>{value}</div>
    </div>
  )
}

function Table({ head, rows }) {
  return (
    <div className="card" style={{ padding: 0, overflow: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>{head.map((h, i) => (
            <th key={h} style={{ ...th, textAlign: i === 0 || i === 1 ? 'left' : 'right' }}>
              {h}
            </th>
          ))}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {r.map((c, j) => (
                <td key={j} style={j === 0 || j === 1 ? td : num}>{c}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
