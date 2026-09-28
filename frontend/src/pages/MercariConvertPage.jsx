import { useRef, useState } from 'react'
import api from '../api/client'

/**
 * メルカリShopsの注文CSVを、ラベル発行ツールの形に変換する。
 *
 * これまではスプレッドシートのマクロでやっていたが、使えなくなった。
 * ファイルを選ぶと中身を見せ、確かめてからCSVを落とす。
 *
 * メルカリShopsのCSVは注文1件につき2行（order と product）あり、
 * 送付先は product 行にしか入っていない。そこはサーバー側でまとめている。
 */

const C = {
  line: '#e5e7eb', sub: '#64748b', text: '#0f172a',
  good: '#16a34a', warn: '#b45309', bad: '#dc2626', key: '#2563eb',
}

const th = {
  padding: '6px 8px', textAlign: 'left', fontSize: 11, color: C.sub,
  background: '#f8fafc', whiteSpace: 'nowrap',
}
const td = {
  padding: '6px 8px', fontSize: 12, borderTop: `1px solid ${C.line}`,
  whiteSpace: 'nowrap',
}

export default function MercariConvertPage() {
  const [file, setFile] = useState(null)
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const inputRef = useRef(null)

  const pick = async (f) => {
    setFile(f); setData(null); setErr('')
    if (!f) return
    setBusy(true)
    try {
      const fd = new FormData()
      fd.append('file', f)
      const r = await api.post('/mercari/preview', fd)
      setData(r.data)
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  const download = async () => {
    if (!file) return
    setBusy(true); setErr('')
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await api.post('/mercari/convert', fd, { responseType: 'blob' })
      const a = document.createElement('a')
      a.href = URL.createObjectURL(res.data)
      const cd = res.headers['content-disposition'] || ''
      const m = cd.match(/filename=(.+)/)
      a.download = m ? m[1].trim() : 'mercari.csv'
      a.click()
      URL.revokeObjectURL(a.href)
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  return (
    <div style={{ padding: 2, minWidth: 0 }}>
      <h2 style={{ fontSize: 18, marginBottom: 4 }}>🛍️ メルカリShops変換</h2>
      <div style={{ fontSize: 12, color: C.sub, marginBottom: 12 }}>
        メルカリShopsの注文CSVを、ラベル発行ツールが読む形に変換します。
        変換したCSVはダウンロードフォルダに入ります。
      </div>

      {err && (
        <div style={{
          background: '#fef2f2', border: '1px solid #fecaca', color: '#991b1b',
          padding: 10, borderRadius: 6, marginBottom: 10, fontSize: 13,
        }}>{err}</div>
      )}

      <div className="card" style={{
        marginBottom: 12, display: 'flex', gap: 12, alignItems: 'center',
        flexWrap: 'wrap',
      }}>
        <input ref={inputRef} type="file" accept=".csv,text/csv"
          onChange={e => pick(e.target.files?.[0] || null)}
          style={{ fontSize: 12 }} />
        {file && (
          <span style={{ fontSize: 12, color: C.sub }}>{file.name}</span>
        )}
        {busy && <span style={{ fontSize: 12, color: C.sub }}>読み込み中…</span>}
        {data && (
          <button className="btn btn-primary" onClick={download} disabled={busy}
            style={{ marginLeft: 'auto' }}>
            📥 CSVをダウンロード（{data.rows.length}件）
          </button>
        )}
      </div>

      {/* 気づいたことは黙って捨てず、必ず出す */}
      {data && data.notes.length > 0 && (
        <div style={{
          marginBottom: 12, fontSize: 12, padding: '8px 10px', borderRadius: 6,
          background: '#fffbeb', border: '1px solid #fcd34d', color: '#92400e',
        }}>
          <b>確かめてください</b>
          {data.notes.map((n, i) => <div key={i}>・{n}</div>)}
        </div>
      )}

      {data && (
        <div className="card" style={{ padding: 0, overflow: 'auto' }}>
          <table style={{ borderCollapse: 'collapse', minWidth: '100%' }}>
            <thead>
              <tr>{data.headers.map(h => <th key={h} style={th}>{h}</th>)}</tr>
            </thead>
            <tbody>
              {data.rows.map((r, i) => (
                <tr key={i}>
                  {data.headers.map(h => (
                    <td key={h} style={{
                      ...td,
                      maxWidth: h === '商品名' ? 260 : undefined,
                      overflow: 'hidden', textOverflow: 'ellipsis',
                    }} title={r[h]}>{r[h]}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!data && !busy && (
        <div style={{ fontSize: 12, color: C.sub, lineHeight: 1.9 }}>
          メルカリShopsの管理画面で落とした注文CSV（orders_〜.csv）を選んでください。
          <br />
          注文1件につき2行（注文の行と商品の行）になっているファイルです。
          送付先は商品の行に入っているので、こちらで1行にまとめます。
        </div>
      )}
    </div>
  )
}
