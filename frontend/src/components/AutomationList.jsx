import { useEffect, useState } from 'react'
import api from '../api/client'

/**
 * いま自動で動いているものの一覧。
 *
 * 機能が増えるほど「何が勝手に動いていて、何を自分でやるのか」が
 * 分からなくなる。毎日最初に開く画面の一番上に出しておく。
 *
 * 並びはサーバーが持つ（/api/automations）。画面に書くと、巡回に
 * 足したのに一覧へ書き忘れる。
 */
const C = {
  line: '#e5e7eb', sub: '#64748b', text: '#0f172a',
  bad: '#dc2626', warn: '#b45309', good: '#16a34a',
}

const AREAS = [
  ['amazon', 'Amazon'],
  ['rakuten', '楽天'],
  ['both', '共通'],
]

export default function AutomationList() {
  const [rows, setRows] = useState(null)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(null)

  async function load() {
    try {
      const r = await api.get('/automations')
      setRows(r.data || [])
    } catch {
      setRows([])
    }
  }
  useEffect(() => { load() }, [])

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

  if (!rows || !rows.length) return null

  const stopped = rows.reduce((a, r) => a + (r.waiting || 0), 0)
  const off = rows.filter(r => r.switch && !r.enabled)

  return (
    <div style={{
      border: `1px solid ${C.line}`, borderRadius: 10, padding: '12px 14px',
      marginBottom: 16, background: '#f8fafc',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <b style={{ fontSize: 14 }}>⚙️ 自動で動いているもの</b>
        <span style={{ fontSize: 12, color: C.sub }}>{rows.length}件</span>
        {stopped > 0 && (
          <span style={{ fontSize: 12, color: C.bad, fontWeight: 700 }}>
            止まっていて手が要るもの {stopped}件
          </span>
        )}
        {off.length > 0 && (
          <span style={{ fontSize: 12, color: C.warn, fontWeight: 700 }}>
            切ってあるもの {off.length}件
          </span>
        )}
        <button
          onClick={() => setOpen(o => !o)}
          style={{
            marginLeft: 'auto', fontSize: 12, padding: '3px 10px', cursor: 'pointer',
            border: `1px solid ${C.line}`, borderRadius: 6, background: '#fff',
          }}>
          {open ? '閉じる' : '中身を見る'}
        </button>
      </div>

      {!open && (
        <div style={{ fontSize: 12, color: C.sub, marginTop: 6 }}>
          {AREAS.map(([id, label]) => {
            const n = rows.filter(r => r.area === id).length
            return n ? `${label} ${n}件` : null
          }).filter(Boolean).join('　／　')}
        </div>
      )}

      {open && AREAS.map(([id, label]) => {
        const list = rows.filter(r => r.area === id)
        if (!list.length) return null
        return (
          <div key={id} style={{ marginTop: 12 }}>
            <div style={{
              fontSize: 11, fontWeight: 700, color: C.sub, letterSpacing: 1,
              borderBottom: `1px solid ${C.line}`, paddingBottom: 4,
            }}>{label}</div>
            {list.map(r => (
              <div key={r.id} style={{ padding: '8px 0', borderBottom: `1px solid ${C.line}` }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <span style={{
                    fontSize: 11, color: C.sub, border: `1px solid ${C.line}`,
                    borderRadius: 4, padding: '1px 6px', background: '#fff',
                    whiteSpace: 'nowrap',
                  }}>{r.every}</span>
                  <b style={{ fontSize: 13 }}>{r.name}</b>
                  {r.waiting > 0 && (
                    <span style={{ fontSize: 12, color: C.bad, fontWeight: 700 }}>
                      手が要るもの {r.waiting}件
                    </span>
                  )}
                  {r.switch && (
                    <label style={{
                      marginLeft: 'auto', display: 'inline-flex', alignItems: 'center',
                      gap: 4, fontSize: 12, cursor: 'pointer',
                      color: r.enabled ? C.good : C.warn, fontWeight: 700,
                    }}>
                      <input type="checkbox" checked={!!r.enabled}
                        disabled={busy === r.switch}
                        onChange={e => toggle(r.switch, e.target.checked)} />
                      {r.enabled ? '動いています' : '切ってあります'}
                    </label>
                  )}
                </div>
                <div style={{ fontSize: 12, color: C.sub, marginTop: 2 }}>{r.what}</div>
              </div>
            ))}
          </div>
        )
      })}
    </div>
  )
}
