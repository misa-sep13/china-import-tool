import { useEffect, useState } from 'react'
import api from '../api/client'

/**
 * 自動でやったこと。
 *
 * 機能が増えて、何が勝手に動いていて何を自分でやるのか分からなく
 * なっていた。説明より「いつ何をしたか」が知りたいので、記録を先に出す。
 * 下に仕組みの一覧を置き、切れるものはここで切る。
 */
const C = {
  line: '#e5e7eb', sub: '#64748b', text: '#0f172a',
  bad: '#dc2626', warn: '#b45309', good: '#16a34a', blue: '#2563eb',
}

const AREAS = [
  ['', 'すべて'],
  ['amazon', 'Amazon'],
  ['rakuten', '楽天'],
  ['both', '共通'],
]
const AREA_LABEL = { amazon: 'Amazon', rakuten: '楽天', both: '共通' }
const AREA_COLOR = { amazon: '#f59e0b', rakuten: '#dc2626', both: '#64748b' }

function when(iso) {
  const d = new Date(iso)
  if (isNaN(d)) return ''
  const now = new Date()
  const mins = Math.floor((now - d) / 60000)
  const stamp = d.toLocaleString('ja-JP', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  })
  if (mins < 1) return `${stamp}（たった今）`
  if (mins < 60) return `${stamp}（${mins}分前）`
  if (mins < 60 * 24) return `${stamp}（${Math.floor(mins / 60)}時間前）`
  return `${stamp}（${Math.floor(mins / 1440)}日前）`
}

export default function AutomationsPage() {
  const [area, setArea] = useState('')
  const [runs, setRuns] = useState([])
  const [jobs, setJobs] = useState([])
  const [busy, setBusy] = useState(null)
  const [showJobs, setShowJobs] = useState(false)

  async function load(a = area) {
    try {
      const [r, j] = await Promise.all([
        api.get('/automations/runs', { params: a ? { area: a } : {} }),
        api.get('/automations'),
      ])
      setRuns(r.data || [])
      setJobs(j.data || [])
    } catch { /* 空のまま */ }
  }
  useEffect(() => { load(area) }, [area])

  async function toggle(key, enabled) {
    setBusy(key)
    try {
      await api.put('/automations/switch', { key, enabled })
      await load()
    } catch (e) {
      alert('切り替えできませんでした: ' + (e.response?.data?.detail || e.message))
    } finally {
      setBusy(null)
    }
  }

  const stopped = jobs.reduce((a, j) => a + (j.waiting || 0), 0)
  const off = jobs.filter(j => j.switch && !j.enabled)

  const tab = (id, label) => (
    <button key={id} onClick={() => setArea(id)} style={{
      padding: '6px 14px', fontSize: 13, cursor: 'pointer',
      border: 'none', background: 'none', borderBottom: `2px solid ${area === id ? C.blue : 'transparent'}`,
      color: area === id ? C.blue : C.sub, fontWeight: area === id ? 700 : 400,
    }}>{label}</button>
  )

  return (
    <div style={{ padding: 20, maxWidth: 1000 }}>
      <h2 style={{ margin: '0 0 4px', fontSize: 20 }}>🤖 自動でやったこと</h2>
      <div style={{ color: C.sub, fontSize: 13, marginBottom: 12 }}>
        ツールが勝手にやったことの記録です。手が要るものは赤で出ます。
      </div>

      {(stopped > 0 || off.length > 0) && (
        <div style={{
          border: `1px solid ${stopped ? '#fecaca' : '#fde68a'}`, borderRadius: 8,
          background: stopped ? '#fef2f2' : '#fffbeb', padding: '8px 12px',
          marginBottom: 12, fontSize: 13,
        }}>
          {stopped > 0 && (
            <div style={{ color: C.bad, fontWeight: 700 }}>
              止まっていて手が要るもの {stopped}件
            </div>
          )}
          {off.length > 0 && (
            <div style={{ color: C.warn }}>
              切ってあるもの：{off.map(j => j.name).join('、')}
            </div>
          )}
        </div>
      )}

      <div style={{ borderBottom: `1px solid ${C.line}`, marginBottom: 8 }}>
        {AREAS.map(([id, label]) => tab(id, label))}
      </div>

      {!runs.length && (
        <div style={{ color: C.sub, fontSize: 13, padding: '16px 0' }}>
          まだ記録がありません。何かが動いたらここに並びます。
        </div>
      )}

      {runs.map(r => (
        <div key={r.id} style={{
          display: 'flex', gap: 10, alignItems: 'baseline',
          padding: '8px 0', borderBottom: `1px solid ${C.line}`,
          background: r.status === 'stopped' ? '#fff7f7' : undefined,
        }}>
          <span style={{ fontSize: 12, color: C.sub, whiteSpace: 'nowrap', minWidth: 150 }}>
            {when(r.at)}
          </span>
          <span style={{
            fontSize: 11, color: '#fff', background: AREA_COLOR[r.area] || C.sub,
            borderRadius: 4, padding: '1px 6px', whiteSpace: 'nowrap',
          }}>{AREA_LABEL[r.area] || r.area}</span>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{
              fontSize: 13, fontWeight: 700,
              color: r.status === 'stopped' ? C.bad : r.status === 'error' ? C.bad : C.text,
            }}>
              {r.status === 'stopped' ? '⚠ ' : r.status === 'error' ? '✕ ' : '✓ '}
              {r.summary}
            </div>
            <div style={{ fontSize: 11, color: C.sub }}>{r.name}</div>
          </div>
        </div>
      ))}

      <div style={{ marginTop: 24 }}>
        <button onClick={() => setShowJobs(v => !v)} style={{
          fontSize: 13, padding: '5px 12px', cursor: 'pointer',
          border: `1px solid ${C.line}`, borderRadius: 6, background: '#fff',
        }}>
          {showJobs ? '仕組みの一覧を閉じる' : `動いている仕組みを見る（${jobs.length}件）`}
        </button>
      </div>

      {showJobs && AREAS.filter(([id]) => id).map(([id, label]) => {
        const list = jobs.filter(j => j.area === id)
        if (!list.length) return null
        return (
          <div key={id} style={{ marginTop: 14 }}>
            <div style={{
              fontSize: 11, fontWeight: 700, color: C.sub, letterSpacing: 1,
              borderBottom: `1px solid ${C.line}`, paddingBottom: 4,
            }}>{label}</div>
            {list.map(j => (
              <div key={j.id} style={{ padding: '8px 0', borderBottom: `1px solid ${C.line}` }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <span style={{
                    fontSize: 11, color: C.sub, border: `1px solid ${C.line}`,
                    borderRadius: 4, padding: '1px 6px', background: '#fff', whiteSpace: 'nowrap',
                  }}>{j.every}</span>
                  <b style={{ fontSize: 13 }}>{j.name}</b>
                  {j.waiting > 0 && (
                    <span style={{ fontSize: 12, color: C.bad, fontWeight: 700 }}>
                      手が要るもの {j.waiting}件
                    </span>
                  )}
                  {j.switch && (
                    <label style={{
                      marginLeft: 'auto', display: 'inline-flex', alignItems: 'center',
                      gap: 4, fontSize: 12, cursor: 'pointer',
                      color: j.enabled ? C.good : C.warn, fontWeight: 700,
                    }}>
                      <input type="checkbox" checked={!!j.enabled}
                        disabled={busy === j.switch}
                        onChange={e => toggle(j.switch, e.target.checked)} />
                      {j.enabled ? '動いています' : '切ってあります'}
                    </label>
                  )}
                </div>
                <div style={{ fontSize: 12, color: C.sub, marginTop: 2 }}>{j.what}</div>
              </div>
            ))}
          </div>
        )
      })}
    </div>
  )
}
