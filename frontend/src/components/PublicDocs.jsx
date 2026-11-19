import { useEffect, useMemo, useState } from 'react'
import api from '../api/client'

/**
 * 税理士向けの公開ページに出す書類。
 *
 * 数字だけ見せても裏づけが無いと確かめようがないので、同じURLから
 * その月の書類もそのまま落とせるようにする。
 * 見るだけで、入れ替えや削除はできない（サーバー側でGETしか通していない）。
 */

const C = { line: '#e5e7eb', sub: '#64748b', bad: '#dc2626' }
const td = { padding: '6px 8px', borderTop: `1px solid ${C.line}`, fontSize: 13 }
const KIND_LABEL = {
  permit: '輸入許可書', invoice: 'タオタロウの請求書', rms: 'RMS店舗別内訳書',
  yamato: 'ヤマト運輸の送料請求書', wholesale: '卸請求書', other: 'その他',
}
const ymOf = (x) => {
  const d = String(x.permit_date || x.mail_date || '')
  return /^\d{4}-\d{2}/.test(d) ? d.slice(0, 7) : '日付なし'
}
const kb = (n) => (n ? `${Math.max(1, Math.round(n / 1024)).toLocaleString('ja-JP')}KB` : '')

export default function PublicDocs({ share }) {
  const [rows, setRows] = useState(null)
  const [ym, setYm] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => {
    api.get('/import-permits/', { params: { share } })
      .then(r => {
        const items = r.data.items || []
        setRows(items)
        const ms = [...new Set(items.map(ymOf))].filter(x => x !== '日付なし').sort().reverse()
        if (ms.length) setYm(ms[0])
      })
      .catch(e => setErr(e.response?.data?.detail || e.message))
  }, [share])

  const months = useMemo(() => {
    if (!rows) return []
    const m = {}
    rows.forEach(x => { const k = ymOf(x); m[k] = (m[k] || 0) + 1 })
    return Object.entries(m).filter(([k]) => k !== '日付なし')
      .sort((a, b) => (a[0] < b[0] ? 1 : -1))
  }, [rows])

  const list = (rows || []).filter(x => ymOf(x) === ym)

  const zip = async () => {
    const [y, mo] = ym.split('-')
    setBusy(true); setErr('')
    try {
      const r = await api.get('/import-permits/zip',
        { params: { year: Number(y), month: Number(mo), share }, responseType: 'blob' })
      const url = URL.createObjectURL(r.data)
      const a = document.createElement('a')
      a.href = url; a.download = `書類_${ym}.zip`; a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setErr('ZIPを作れませんでした')
    } finally { setBusy(false) }
  }

  const open = (x) => {
    const base = api.defaults.baseURL || ''
    window.open(`${base}/import-permits/${x.id}/pdf?share=${encodeURIComponent(share)}`, '_blank')
  }

  if (!rows) return null

  return (
    <div className="card" style={{ marginTop: 18 }}>
      <b style={{ fontSize: 15 }}>📑 書類</b>
      <div style={{ fontSize: 12, color: C.sub, marginTop: 6, lineHeight: 1.9 }}>
        上の数字の裏づけです。輸入許可書・タオタロウの請求書・RMS店舗別内訳書・
        ヤマト運輸の送料請求書・卸の請求書が入っています。
        月を選んで「この月をZIPで書き出す」で、まとめて落とせます。
      </div>
      {err && <div style={{ color: C.bad, fontSize: 12, marginTop: 6 }}>{err}</div>}

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', margin: '10px 0' }}>
        <select value={ym} onChange={e => setYm(e.target.value)} style={{ padding: '4px 8px', fontSize: 13 }}>
          {months.map(([k, n]) => <option key={k} value={k}>{k}（{n}件）</option>)}
        </select>
        <button className="btn btn-sm btn-secondary" disabled={!list.length || busy} onClick={zip}>
          {busy ? 'まとめています…' : '⬇ この月をZIPで書き出す'}
        </button>
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <tbody>
            {list.map(x => (
              <tr key={x.id}>
                <td style={{ ...td, color: C.sub, whiteSpace: 'nowrap' }}>
                  {KIND_LABEL[x.kind] || x.kind}
                </td>
                <td style={td}>{x.filename}</td>
                <td style={{ ...td, color: C.sub, textAlign: 'right', whiteSpace: 'nowrap' }}>{kb(x.size_bytes)}</td>
                <td style={{ ...td, textAlign: 'right' }}>
                  <button className="btn btn-sm btn-secondary" onClick={() => open(x)}>開く</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!list.length && <div style={{ padding: 12, color: C.sub, fontSize: 13 }}>この月の書類はありません。</div>}
      </div>
    </div>
  )
}
