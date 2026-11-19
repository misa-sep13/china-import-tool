import { useEffect, useState } from 'react'
import api from '../api/client'

/**
 * 入荷日が入っていない仕入。
 *
 * メーカー品の仕入は「届いた日」で計上する。日付が無い行は月に入れられず、
 * その分だけ仕入が足りないまま売上原価が出てしまう（棚卸差異に化ける）。
 * 月次サマリーの先頭に出して、その場で入れられるようにする。
 *
 * 既定値は発注日。分納でも発注日より前に届くことはないので、
 * 直すときの出発点として一番近い。
 */

const C = { line: '#e5e7eb', sub: '#64748b', warn: '#b45309', bad: '#dc2626', good: '#16a34a' }
const td = { padding: '6px 8px', borderTop: `1px solid ${C.line}`, fontSize: 13, whiteSpace: 'nowrap' }
const yen = v => `¥${Math.round(v || 0).toLocaleString('ja-JP')}`

export default function UndatedReceipts({ onChanged }) {
  const [rows, setRows] = useState(null)
  const [dates, setDates] = useState({})
  const [busy, setBusy] = useState(0)
  const [err, setErr] = useState('')

  const load = () => api.get('/wholesale/receipts', { params: { undated: true } })
    .then(r => {
      const items = r.data.items || []
      setRows(items)
      setDates(Object.fromEntries(items.map(x => [x.id, x.order_date || ''])))
    })
    .catch(e => setErr(e.response?.data?.detail || e.message))

  useEffect(() => { load() }, [])

  const save = async (id) => {
    const d = dates[id]
    if (!/^\d{4}-\d{2}-\d{2}$/.test(d || '')) { setErr('日付は YYYY-MM-DD で入れてください'); return }
    setErr(''); setBusy(id)
    try {
      await api.put(`/wholesale/receipts/${id}`, { received_date: d })
      await load()
      onChanged && onChanged()
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(0) }
  }

  if (!rows || rows.length === 0) return null
  const total = rows.reduce((s, x) => s + (x.amount || 0), 0)

  return (
    <div className="card" style={{ marginBottom: 12, borderLeft: `4px solid ${C.warn}` }}>
      <b style={{ fontSize: 15 }}>入荷日が入っていない仕入が {rows.length}件（{yen(total)}）あります</b>
      <div style={{ fontSize: 12, color: C.sub, marginTop: 6, lineHeight: 1.9 }}>
        メーカー品の仕入は<b>届いた日</b>で計上します。日付が無いとどの月にも入らないので、
        その分だけ仕入が足りないまま売上原価が出ます（差額は棚卸差異に化けます）。
        入れると、その月の仕入に入ります。<b>初期値は発注日</b>です。
      </div>
      {err && <div style={{ color: C.bad, fontSize: 12, marginTop: 6 }}>{err}</div>}
      <div style={{ overflowX: 'auto', marginTop: 10 }}>
        <table style={{ borderCollapse: 'collapse', width: '100%' }}>
          <thead>
            <tr>
              {['発注日', '取引先', '商品', '数', '金額', '届いた日', ''].map((h, i) => (
                <th key={i} style={{ ...td, borderTop: 'none', fontSize: 12, color: C.sub,
                  textAlign: i === 3 || i === 4 ? 'right' : 'left' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.id}>
                <td style={td}>{r.order_date || '—'}</td>
                <td style={td}>{r.supplier_name}</td>
                <td style={{ ...td, whiteSpace: 'normal', maxWidth: 280 }}>{r.name}</td>
                <td style={{ ...td, textAlign: 'right' }}>{r.qty}</td>
                <td style={{ ...td, textAlign: 'right' }}>{yen(r.amount)}</td>
                <td style={td}>
                  <input type="date" value={dates[r.id] || ''}
                    onChange={e => setDates(d => ({ ...d, [r.id]: e.target.value }))}
                    style={{ padding: '4px 6px', fontSize: 13 }} />
                </td>
                <td style={td}>
                  <button className="btn btn-sm btn-primary" disabled={busy === r.id}
                    onClick={() => save(r.id)}>
                    {busy === r.id ? '…' : '入れる'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
