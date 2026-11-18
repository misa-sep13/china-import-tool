import { useEffect, useMemo, useState } from 'react'
import api from '../api/client'

/**
 * 月次管理表の「📑 書類」。
 *
 * 税理士へ渡す書類を月ごとに1か所で見られるようにする。棚は輸入許可書の保管庫
 * （import_permits）をそのまま使い、種別で分ける。
 *   輸入許可書・タオタロウの請求書 … 自動で入る（メール／API。輸入許可書の画面から取り込み）
 *   RMS店舗別内訳書・ヤマト請求書・その他 … ここから手で入れる
 * 月を選ぶと、その月の書類と、まだ入っていない種別が分かる。ZIPでまとめて落とせる。
 */

const C = { line: '#e5e7eb', sub: '#64748b', text: '#0f172a', good: '#16a34a', bad: '#dc2626', warn: '#b45309' }
const th = { padding: '6px 8px', textAlign: 'left', fontSize: 12, color: C.sub, background: '#f8fafc', whiteSpace: 'nowrap' }
const td = { padding: '6px 8px', borderTop: `1px solid ${C.line}`, fontSize: 13, verticalAlign: 'middle' }

const KINDS = [
  { key: 'permit', label: '輸入許可書', auto: true, hint: '通関業者のメールから自動で取り込み' },
  { key: 'invoice', label: 'タオタロウの請求書', auto: true, hint: 'タオタロウから自動で取り込み' },
  { key: 'rms', label: 'RMS店舗別内訳書', hint: 'RMSからダウンロードしてここに入れる' },
  { key: 'yamato', label: 'ヤマト運輸の送料請求書', hint: 'ヤマトの請求書をここに入れる' },
  { key: 'other', label: 'その他', hint: '' },
]
const KIND_LABEL = Object.fromEntries(KINDS.map(k => [k.key, k.label]))
// 毎月そろっているはずの種別。欠けていたら目立たせる
const MONTHLY = ['rms', 'yamato']

const ymOf = (x) => {
  const d = String(x.permit_date || x.mail_date || '')
  return /^\d{4}-\d{2}/.test(d) ? d.slice(0, 7) : '日付なし'
}
const kb = (n) => (n ? `${Math.max(1, Math.round(n / 1024)).toLocaleString('ja-JP')}KB` : '')

async function getBlob(url, params) {
  try {
    const r = await api.get(url, { params, responseType: 'blob' })
    return r.data
  } catch (e) {
    const b = e.response?.data
    if (b instanceof Blob) {
      try { const j = JSON.parse(await b.text()); if (j.detail) e.message = j.detail } catch { /* そのまま */ }
    }
    throw e
  }
}

function saveBlob(blob, name) {
  const href = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = href
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(href), 60000)
}

const thisYm = () => {
  const d = new Date()
  d.setMonth(d.getMonth() - 1)   // 書類は前月分を入れることが多い
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

export default function AccountingDocsPage() {
  const [items, setItems] = useState(null)
  const [err, setErr] = useState('')
  const [ym, setYm] = useState('')
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState('')
  const [upKind, setUpKind] = useState('rms')
  const [upYm, setUpYm] = useState(thisYm())
  const [files, setFiles] = useState([])
  const [fileKey, setFileKey] = useState(0)

  const load = () => api.get('/import-permits/')
    .then(r => setItems((r.data.items || []).filter(x => !x.duplicate)))
    .catch(e => setErr(e.response?.data?.detail || e.message))
  useEffect(() => { load() }, [])

  const months = useMemo(() => {
    const m = new Map()
    ;(items || []).forEach(x => {
      const k = ymOf(x)
      if (!m.has(k)) m.set(k, {})
      const g = m.get(k)
      g[x.kind] = (g[x.kind] || 0) + 1
    })
    return [...m.entries()].sort((a, b) => b[0].localeCompare(a[0]))
  }, [items])

  useEffect(() => {
    if (!ym && months.length) setYm(months.find(([k]) => k !== '日付なし')?.[0] || months[0][0])
  }, [months, ym])

  const rows = useMemo(() => (items || []).filter(x => ymOf(x) === ym), [items, ym])

  const open = async (x) => {
    const w = window.open('', '_blank')
    try {
      const blob = await getBlob(`/import-permits/${x.id}/pdf`)
      const href = URL.createObjectURL(blob)
      if (w) w.location.href = href
      else saveBlob(blob, x.filename || 'document')
    } catch (e) {
      if (w) w.close()
      setErr('開けませんでした：' + (e.message || ''))
    }
  }

  const zip = async () => {
    if (!/^\d{4}-\d{2}$/.test(ym)) return
    setBusy('zip'); setErr('')
    try {
      const blob = await getBlob('/import-permits/zip', { year: Number(ym.slice(0, 4)), month: Number(ym.slice(5, 7)) })
      saveBlob(blob, `書類_${ym}.zip`)
    } catch (e) {
      setErr('ZIPを作れませんでした：' + (e.message || ''))
    } finally { setBusy('') }
  }

  const upload = async () => {
    if (!files.length) return
    setBusy('up'); setErr(''); setMsg('')
    let ok = 0
    try {
      for (const f of files) {
        const fd = new FormData()
        fd.append('file', f)
        fd.append('kind', upKind)
        if (upKind !== 'permit') fd.append('period', upYm)
        await api.post('/import-permits/upload', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
        ok++
      }
      setMsg(`${KIND_LABEL[upKind]}を${ok}件入れました${upKind !== 'permit' ? `（${upYm}）` : ''}`)
      setFiles([]); setFileKey(k => k + 1)
      if (upKind !== 'permit') setYm(upYm)
      await load()
    } catch (e) {
      setErr(`入れられませんでした（${ok}件目まで済み）：` + (e.response?.data?.detail || e.message))
    } finally { setBusy('') }
  }

  const remove = async (x) => {
    if (!window.confirm(`「${x.filename}」を削除します。元に戻せません。よろしいですか？`)) return
    try {
      await api.delete(`/import-permits/${x.id}`)
      await load()
    } catch (e) {
      setErr('削除できませんでした：' + (e.response?.data?.detail || e.message))
    }
  }

  const counts = (months.find(([k]) => k === ym) || [null, {}])[1]

  return (
    <div>
      <div className="card" style={{ marginBottom: 12 }}>
        <b style={{ fontSize: 16 }}>📑 書類（税理士へ渡すもの）</b>
        <div style={{ fontSize: 12, color: C.sub, marginTop: 6, lineHeight: 1.8 }}>
          月ごとに書類をまとめています。輸入許可書とタオタロウの請求書は自動で入ります（輸入許可書の画面から取り込み）。
          RMS店舗別内訳書とヤマト運輸の請求書は、下から手で入れてください。
          「この月をZIPで書き出す」で、その月の書類を1つにまとめて渡せます。
        </div>
        {err && <div style={{ color: C.bad, fontSize: 12, marginTop: 6 }}>{err}</div>}
        {msg && <div style={{ color: C.good, fontSize: 12, marginTop: 6 }}>{msg}</div>}

        {/* 手で入れる */}
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginTop: 12,
          padding: '10px 12px', background: '#f8fafc', borderRadius: 8 }}>
          <b style={{ fontSize: 13 }}>書類を入れる</b>
          <select value={upKind} onChange={e => setUpKind(e.target.value)} style={{ fontSize: 13, padding: '4px 8px' }}>
            {KINDS.filter(k => k.key !== 'invoice').map(k => <option key={k.key} value={k.key}>{k.label}</option>)}
          </select>
          {upKind !== 'permit'
            ? <label style={{ fontSize: 13 }}>対象月 <input type="month" value={upYm} onChange={e => setUpYm(e.target.value)} style={{ fontSize: 13 }} /></label>
            : <span style={{ fontSize: 12, color: C.sub }}>許可日はPDFから読み取ります</span>}
          <input key={fileKey} type="file" multiple accept=".pdf,.csv,.xlsx,.xls,.png,.jpg,.jpeg"
            onChange={e => setFiles([...e.target.files])} style={{ fontSize: 12 }} />
          <button className="btn btn-primary" style={{ fontSize: 12 }}
            disabled={!files.length || busy === 'up'} onClick={upload}>
            {busy === 'up' ? '入れています…' : `入れる${files.length ? `（${files.length}件）` : ''}`}
          </button>
        </div>
      </div>

      {!items && !err && <div className="card" style={{ color: C.sub }}>読み込んでいます…</div>}

      {items && (
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start', flexWrap: 'wrap' }}>
          {/* 月の一覧 */}
          <div className="card" style={{ minWidth: 220, flex: '0 0 auto', padding: 8 }}>
            {months.map(([k, c]) => {
              const lacking = /^\d{4}-\d{2}$/.test(k) ? MONTHLY.filter(x => !c[x]) : []
              const total = Object.values(c).reduce((a, b) => a + b, 0)
              return (
                <div key={k} onClick={() => setYm(k)}
                  style={{ padding: '6px 10px', borderRadius: 6, cursor: 'pointer', marginBottom: 2,
                    background: k === ym ? '#eff6ff' : undefined, fontWeight: k === ym ? 700 : 400 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: 13 }}>
                    <span>{k}</span><span style={{ color: C.sub }}>{total}件</span>
                  </div>
                  {lacking.length > 0 && (
                    <div style={{ fontSize: 11, color: C.warn, fontWeight: 400 }}>
                      未：{lacking.map(x => KIND_LABEL[x].replace('ヤマト運輸の送料', 'ヤマト')).join('・')}
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          {/* 選んだ月の書類 */}
          <div className="card" style={{ flex: 1, minWidth: 320, overflowX: 'auto' }}>
            <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap', marginBottom: 10 }}>
              <b style={{ fontSize: 15 }}>{ym} の書類 {rows.length}件</b>
              {/^\d{4}-\d{2}$/.test(ym) && (
                <button className="btn btn-secondary" style={{ fontSize: 12 }} disabled={!rows.length || busy === 'zip'} onClick={zip}>
                  {busy === 'zip' ? 'まとめています…' : '⬇ この月をZIPで書き出す'}
                </button>
              )}
            </div>
            {KINDS.map(k => {
              const list = rows.filter(x => (x.kind || 'permit') === k.key)
              if (!list.length && k.key === 'other') return null
              const need = MONTHLY.includes(k.key)
              return (
                <div key={k.key} style={{ marginBottom: 14 }}>
                  <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 4 }}>
                    {k.label}
                    <span style={{ fontWeight: 400, color: C.sub, marginLeft: 6 }}>{list.length}件</span>
                    {!list.length && need && <span style={{ color: C.warn, fontWeight: 400, marginLeft: 8 }}>まだ入っていません（{k.hint}）</span>}
                    {!list.length && !need && <span style={{ color: C.sub, fontWeight: 400, marginLeft: 8 }}>この月はありません</span>}
                  </div>
                  {list.length > 0 && (
                    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                      <thead>
                        <tr>
                          <th style={th}>日付</th>
                          <th style={th}>ファイル</th>
                          <th style={th}>番号</th>
                          <th style={{ ...th, textAlign: 'right' }}>大きさ</th>
                          <th style={th}></th>
                        </tr>
                      </thead>
                      <tbody>
                        {list.map(x => (
                          <tr key={x.id}>
                            <td style={{ ...td, whiteSpace: 'nowrap' }}>{k.auto ? (x.permit_date || String(x.mail_date || '').slice(0, 10)) : ym}</td>
                            <td style={{ ...td, wordBreak: 'break-all' }}>{x.filename}</td>
                            <td style={{ ...td, fontFamily: 'monospace', fontSize: 12 }}>{x.permit_no || ''}</td>
                            <td style={{ ...td, textAlign: 'right', color: C.sub }}>{kb(x.size_bytes)}</td>
                            <td style={{ ...td, whiteSpace: 'nowrap', textAlign: 'right' }}>
                              <button className="btn btn-secondary" style={{ fontSize: 11, padding: '2px 8px' }} onClick={() => open(x)}>開く</button>
                              {x.source === 'upload' && (
                                <button className="btn btn-secondary" style={{ fontSize: 11, padding: '2px 8px', marginLeft: 4, color: C.bad }}
                                  onClick={() => remove(x)}>削除</button>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
