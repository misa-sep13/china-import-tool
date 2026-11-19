import { useEffect, useState } from 'react'
import api from '../api/client'

/**
 * 卸の仕入（メーカー品）。請求書と入荷履歴の突合。
 *
 * 発注どおりに届くとは限らない。9/4の請求書はバナナ480本なのに発注は
 * 360本で、ピーチ60本は発注自体が無かった。実際に請求された額が仕入なので、
 * 請求書があればそれを使い、無い月は入荷履歴で埋める。
 *
 * この画面はその差を見るためのもの。差が出たら、請求書のDL漏れか、
 * 発注と実際のズレか、どちらかが起きている。
 */

const C = { line: '#e5e7eb', sub: '#64748b', good: '#16a34a', bad: '#dc2626', warn: '#b45309' }
const th = { padding: '6px 8px', fontSize: 12, color: C.sub, background: '#f8fafc', whiteSpace: 'nowrap', textAlign: 'right' }
const td = { padding: '6px 8px', borderTop: `1px solid ${C.line}`, fontSize: 13, textAlign: 'right', whiteSpace: 'nowrap' }
const yen = v => (v == null ? '—' : `¥${Math.round(v).toLocaleString('ja-JP')}`)

export default function WholesaleInvoicePage() {
  const [months, setMonths] = useState(null)
  const [ym, setYm] = useState('')
  const [rec, setRec] = useState(null)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState('')

  const loadMonths = () => api.get('/accounting/wholesale-invoices/monthly')
    .then(r => {
      setMonths(r.data.months || [])
      if (!ym && r.data.months?.length) setYm(r.data.months[0].ym)
    })
    .catch(e => setErr(e.response?.data?.detail || e.message))

  useEffect(() => { loadMonths() }, [])
  useEffect(() => {
    if (!ym) return
    setRec(null)
    api.get('/accounting/wholesale-invoices/reconcile', { params: { ym } })
      .then(r => setRec(r.data))
      .catch(e => setErr(e.response?.data?.detail || e.message))
  }, [ym])

  const parse = async () => {
    setBusy('parse'); setErr(''); setMsg('')
    try {
      const r = await api.post('/accounting/wholesale-invoices/parse')
      const f = r.data.failed || []
      setMsg(`請求書 ${r.data.read}枚から ${r.data.lines}行を読みました`
        + (r.data.moved ? `／書類タブの月を ${r.data.moved}枚ぶん請求日に直しました` : '')
        + (f.length ? `（読めなかったもの ${f.length}枚：${f.map(x => x.file).slice(0, 3).join(' / ')}）` : ''))
      await loadMonths()
      if (ym) {
        const d = await api.get('/accounting/wholesale-invoices/reconcile', { params: { ym } })
        setRec(d.data)
      }
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy('') }
  }

  return (
    <div>
      <div className="card" style={{ marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <b style={{ fontSize: 16 }}>🧾 卸の仕入（メーカー品）</b>
          <button className="btn btn-primary" disabled={busy === 'parse'} onClick={parse}>
            {busy === 'parse' ? '読んでいます…' : '請求書を読み直す'}
          </button>
        </div>
        <div style={{ fontSize: 12, color: C.sub, marginTop: 6, lineHeight: 1.9 }}>
          仕入は<b>請求書を正</b>にしています（発注どおりに届くとは限らず、多く届くことも、
          頼んでいないものが入ることもあるため）。請求書は納品のたびに出ているので、
          <b>請求日</b>をそのまま発生日に使います。請求書が無い月は入荷履歴で埋めます。
          <br />
          請求書は<b>書類タブの「卸請求書」</b>から入れてください。まとめて選べます。
        </div>
        {msg && <div style={{ fontSize: 12, color: C.good, marginTop: 6 }}>{msg}</div>}
        {err && <div style={{ fontSize: 12, color: C.bad, marginTop: 6 }}>{err}</div>}
      </div>

      {months && months.length === 0 && (
        <div className="empty-state">
          <p>請求書がまだ入っていません。書類タブの「卸請求書」から入れて、上のボタンを押してください。</p>
        </div>
      )}

      {months && months.length > 0 && (
        <div className="card" style={{ marginBottom: 12, overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 560 }}>
            <thead>
              <tr>
                <th style={{ ...th, textAlign: 'left' }}>月</th>
                <th style={th}>請求書</th>
                <th style={th}>枚数</th>
                <th style={{ ...th, textAlign: 'left' }}>取引先ごと</th>
              </tr>
            </thead>
            <tbody>
              {months.map(m => (
                <tr key={m.ym} style={{ background: m.ym === ym ? '#eff6ff' : undefined, cursor: 'pointer' }}
                  onClick={() => setYm(m.ym)}>
                  <td style={{ ...td, textAlign: 'left', fontWeight: 700 }}>{m.ym}</td>
                  <td style={{ ...td, fontWeight: 600 }}>{yen(m.amount)}</td>
                  <td style={td}>{m.invoices}</td>
                  <td style={{ ...td, textAlign: 'left', whiteSpace: 'normal', color: C.sub, fontSize: 12 }}>
                    {Object.entries(m.suppliers).map(([k, v]) => `${k} ${yen(v)}`).join(' ／ ')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {rec && (
        <div className="card">
          <b style={{ fontSize: 15 }}>{rec.ym} の突合</b>
          <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', margin: '10px 0 4px' }}>
            <div><div style={{ fontSize: 11, color: C.sub }}>請求書</div><b>{yen(rec.invoice_total)}</b></div>
            <div><div style={{ fontSize: 11, color: C.sub }}>入荷履歴</div><b>{yen(rec.receipt_total)}</b></div>
            <div>
              <div style={{ fontSize: 11, color: C.sub }}>差</div>
              <b style={{ color: rec.diff === 0 ? C.good : C.bad }}>{yen(rec.diff)}</b>
            </div>
          </div>
          <div style={{ fontSize: 12, color: C.sub, lineHeight: 1.9, marginBottom: 10 }}>
            差がプラスなら<b>ツールに入っていない仕入</b>（発注より多く届いた、頼んでいないものが来た）。
            マイナスなら<b>請求書のDL漏れ</b>か、下書きの発注が混ざっている可能性があります。
          </div>

          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 840 }}>
              <thead>
                <tr>
                  <th style={{ ...th, textAlign: 'left' }}>請求日</th>
                  <th style={{ ...th, textAlign: 'left' }}>品名（請求書）</th>
                  <th style={th}>請求 数</th>
                  <th style={th}>請求 金額</th>
                  <th style={th}>入荷 数</th>
                  <th style={th}>入荷 金額</th>
                  <th style={th}>差</th>
                </tr>
              </thead>
              <tbody>
                {rec.rows.map((r, i) => (
                  <tr key={i}>
                    <td style={{ ...td, textAlign: 'left', color: C.sub }}>{r.issued || '—'}</td>
                    <td style={{ ...td, textAlign: 'left', whiteSpace: 'normal', maxWidth: 300 }}>
                      {r.name}
                      {!r.rec_name && (
                        <span style={{ color: C.bad, fontSize: 11, marginLeft: 6 }}>入荷に無し</span>
                      )}
                    </td>
                    <td style={td}>{r.inv_qty}</td>
                    <td style={td}>{yen(r.inv_amount)}</td>
                    <td style={td}>{r.rec_qty == null ? '—' : r.rec_qty}</td>
                    <td style={td}>{yen(r.rec_amount)}</td>
                    <td style={{ ...td, fontWeight: 700, color: r.diff_amount ? C.bad : C.sub }}>
                      {r.diff_amount == null ? '—' : yen(r.diff_amount)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {rec.only_receipt.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <b style={{ fontSize: 13 }}>請求書に見当たらない入荷（{rec.only_receipt.length}件）</b>
              <div style={{ fontSize: 12, color: C.sub, marginTop: 4, lineHeight: 1.8 }}>
                請求書のDL漏れか、別の月の請求書に載っているか、品名が結び付かなかったかです。
              </div>
              <table style={{ borderCollapse: 'collapse', marginTop: 6 }}>
                <tbody>
                  {rec.only_receipt.map((r, i) => (
                    <tr key={i}>
                      <td style={{ ...td, textAlign: 'left' }}>{r.supplier}</td>
                      <td style={{ ...td, textAlign: 'left' }}>{r.name}</td>
                      <td style={td}>{r.qty}</td>
                      <td style={td}>{yen(r.amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
