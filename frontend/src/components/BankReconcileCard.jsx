import { useEffect, useState } from 'react'
import api from '../api/client'
import { isPublicView } from '../lib/publicView'

/**
 * 銀行の出金で卸の仕入を合わせる。
 *
 * 請求書が残っていない仕入がある（再発行もできない）ので、最終的には
 * 実際に払った額で合わせる。楽天銀行の入出金明細CSVを入れると、
 * 卸への出金だけを拾って請求書と1件ずつ突き合わせる。
 * マレフィオーレの「請求書の無い出金」は、税抜にして出金日の月の仕入に足す。
 */

const C = { line: '#e5e7eb', sub: '#64748b', good: '#16a34a', bad: '#dc2626', warn: '#b45309' }
const th = { padding: '6px 8px', fontSize: 12, color: C.sub, background: '#f8fafc', whiteSpace: 'nowrap', textAlign: 'left' }
const td = { padding: '6px 8px', borderTop: `1px solid ${C.line}`, fontSize: 13, whiteSpace: 'nowrap' }
const yen = v => (v == null ? '—' : `¥${Math.round(v).toLocaleString('ja-JP')}`)

export default function BankReconcileCard({ onChanged }) {
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const [key, setKey] = useState(0)

  const load = () => api.get('/accounting/bank/reconcile')
    .then(r => setData(r.data))
    .catch(e => setErr(e.response?.data?.detail || e.message))
  useEffect(() => { load() }, [])

  const upload = async (file) => {
    if (!file) return
    setBusy(true); setErr(''); setMsg('')
    try {
      const fd = new FormData()
      fd.append('file', file)
      const r = await api.post('/accounting/bank/import', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
      const s = Object.entries(r.data.suppliers || {}).map(([k, v]) => `${k} ${v}件`).join('・')
      setMsg(`${r.data.from}〜${r.data.to} の明細から、卸への出金を${r.data.found}件見つけました`
        + `（新しく入れたのは${r.data.added}件）${s ? `：${s}` : ''}`)
      await load()
      onChanged && onChanged()
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally {
      setBusy(false); setKey(k => k + 1)
    }
  }

  const fills = (data?.unmatched || []).filter(x => x.fill)
  const others = (data?.unmatched || []).filter(x => !x.fill)

  return (
    <div className="card" style={{ marginBottom: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <b style={{ fontSize: 15 }}>🏦 銀行の出金で合わせる</b>
        {data?.from && <span style={{ fontSize: 12, color: C.sub }}>入っている明細：{data.from}〜{data.to}</span>}
        {!isPublicView() && (
          <label className="btn btn-secondary" style={{ fontSize: 12, cursor: busy ? 'wait' : 'pointer', margin: 0 }}>
            {busy ? '読んでいます…' : '楽天銀行のCSVを入れる'}
            <input key={key} type="file" accept=".csv" style={{ display: 'none' }}
              disabled={busy} onChange={e => upload(e.target.files[0])} />
          </label>
        )}
      </div>
      <div style={{ fontSize: 12, color: C.sub, marginTop: 6, lineHeight: 1.9 }}>
        請求書が残っていない仕入があるので、最終的には実際に払った額で合わせます。
        楽天銀行の「入出金明細」CSVをそのまま入れてください（卸への出金だけを拾い、ほかの行は保存しません）。
        マレフィオーレは納品ごとに請求額×1.1をその日に振り込んでいるので、出金と請求書を1件ずつ当てます。
        <b>請求書の無い出金は、税抜にして出金日の月の仕入に足します。</b>
      </div>
      {msg && <div style={{ color: C.good, fontSize: 12, marginTop: 6 }}>{msg}</div>}
      {err && <div style={{ color: C.bad, fontSize: 12, marginTop: 6 }}>{err}</div>}

      {data && data.from && (
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: 13, marginBottom: 6 }}>
            請求書と一致した出金 <b style={{ color: C.good }}>{data.matched_count}件</b>
            ／ 請求書の無い出金（仕入に足した） <b style={{ color: fills.length ? C.warn : C.good }}>{fills.length}件</b>
          </div>
          {fills.length > 0 && (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ borderCollapse: 'collapse', minWidth: 420 }}>
                <thead>
                  <tr>
                    <th style={th}>出金日</th><th style={th}>取引先</th>
                    <th style={{ ...th, textAlign: 'right' }}>出金（税込）</th>
                    <th style={{ ...th, textAlign: 'right' }}>仕入に足した額（税抜）</th>
                  </tr>
                </thead>
                <tbody>
                  {fills.map(x => (
                    <tr key={x.key}>
                      <td style={td}>{x.paid_on}</td><td style={td}>{x.supplier}</td>
                      <td style={{ ...td, textAlign: 'right' }}>{yen(x.amount)}</td>
                      <td style={{ ...td, textAlign: 'right', fontWeight: 600 }}>{yen(x.net)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {others.length > 0 && (
            <details style={{ marginTop: 8, fontSize: 12 }}>
              <summary style={{ cursor: 'pointer', color: C.sub }}>
                ほかの卸への出金 {others.length}件（請求書を保存していない取引先。仕入は入荷履歴のまま・参考）
              </summary>
              <table style={{ borderCollapse: 'collapse', marginTop: 6 }}>
                <tbody>
                  {others.map(x => (
                    <tr key={x.key}>
                      <td style={td}>{x.paid_on}</td><td style={td}>{x.supplier}</td>
                      <td style={{ ...td, textAlign: 'right' }}>{yen(x.amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          )}
          {data.unpaid_docs?.length > 0 && (
            <div style={{ fontSize: 12, color: C.warn, marginTop: 8 }}>
              出金が見当たらない請求書：
              {data.unpaid_docs.map(d => `${d.issued} ${d.supplier} ${yen(d.amount * 1.1)}`).join('、')}
              （明細の期間の端か、別の口座から払った可能性）
            </div>
          )}
        </div>
      )}
    </div>
  )
}
