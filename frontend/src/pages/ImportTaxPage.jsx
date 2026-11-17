import { useEffect, useState } from 'react'
import api from '../api/client'

/**
 * 月次管理表の「🧾 関税・消費税」。
 *
 * 輸入許可書（保存済み）を輸入許可日の月で集計する。会計上の扱いが違うので分けて出す：
 *   ・関税 … 仕入原価（仕入諸掛）
 *   ・消費税・地方消費税 … 仮払消費税（原価には入れない）
 * 申告番号で保存済みインボイスと照合し、商品原価へ按分済みかも出す。
 */

const C = { line: '#e5e7eb', sub: '#64748b', text: '#0f172a', warn: '#b45309', good: '#16a34a', bad: '#dc2626' }
const th = { padding: '6px 8px', textAlign: 'left', fontSize: 12, color: C.sub, background: '#f8fafc', whiteSpace: 'nowrap' }
const td = { padding: '6px 8px', borderTop: `1px solid ${C.line}`, fontSize: 13, verticalAlign: 'top' }
const yen = v => `¥${Math.round(v || 0).toLocaleString('ja-JP')}`

export default function ImportTaxPage() {
  const [months, setMonths] = useState([])
  const [ym, setYm] = useState('')
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    api.get('/accounting/import-tax/monthly')
      .then(r => {
        const m = r.data.months || []
        setMonths(m)
        const first = m.find(x => x.ym !== '日付なし')
        if (first) setYm(first.ym)
      })
      .catch(e => setErr(e.response?.data?.detail || e.message))
  }, [])

  useEffect(() => {
    if (!ym) return
    setData(null)
    api.get('/accounting/import-tax', { params: { ym } })
      .then(r => setData(r.data))
      .catch(e => setErr(e.response?.data?.detail || e.message))
  }, [ym])

  return (
    <div>
      <div className="card" style={{ marginBottom: 12 }}>
        <b style={{ fontSize: 16 }}>🧾 関税・消費税（輸入許可日で計上）</b>
        <div style={{ fontSize: 12, color: C.sub, marginTop: 6, lineHeight: 1.8 }}>
          保存済みの輸入許可書を、許可日の月で集計しています。
          <b>関税</b>は仕入原価（仕入諸掛）、<b>消費税・地方消費税</b>は仮払消費税で、原価には入れません。
        </div>
        {err && <div style={{ color: C.bad, fontSize: 12, marginTop: 6 }}>{err}</div>}

        {/* 月ごとの一覧。押すとその月の許可書が下に出る */}
        <div style={{ overflowX: 'auto', marginTop: 10 }}>
          <table style={{ borderCollapse: 'collapse', minWidth: 560 }}>
            <thead>
              <tr>
                <th style={th}>月（許可日）</th>
                <th style={{ ...th, textAlign: 'right' }}>件数</th>
                <th style={{ ...th, textAlign: 'right' }}>関税（原価）</th>
                <th style={{ ...th, textAlign: 'right' }}>消費税＋地方消費税（仮払）</th>
                <th style={{ ...th, textAlign: 'right' }}>納税額合計</th>
              </tr>
            </thead>
            <tbody>
              {months.map(m => (
                <tr key={m.ym} onClick={() => m.ym !== '日付なし' && setYm(m.ym)}
                  style={{ cursor: 'pointer', background: m.ym === ym ? '#eff6ff' : undefined }}>
                  <td style={{ ...td, fontWeight: m.ym === ym ? 700 : 400 }}>{m.ym}</td>
                  <td style={{ ...td, textAlign: 'right' }}>{m.count}</td>
                  <td style={{ ...td, textAlign: 'right' }}>{yen(m.customs_duty)}</td>
                  <td style={{ ...td, textAlign: 'right' }}>{yen(m.consumption_tax + m.local_consumption_tax)}</td>
                  <td style={{ ...td, textAlign: 'right', fontWeight: 600 }}>{yen(m.total_tax)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {data && (
        <div className="card">
          <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', alignItems: 'baseline', marginBottom: 8 }}>
            <b style={{ fontSize: 15 }}>{data.ym} の輸入許可書 {data.count}件</b>
            <span style={{ fontSize: 13 }}>関税 <b>{yen(data.customs_duty)}</b></span>
            <span style={{ fontSize: 13 }}>消費税 {yen(data.consumption_tax)}・地方消費税 {yen(data.local_consumption_tax)}</span>
            <span style={{ fontSize: 13 }}>合計 <b>{yen(data.total_tax)}</b></span>
          </div>
          {data.not_allocated?.length > 0 && (
            <div style={{ marginBottom: 8, padding: '6px 10px', borderRadius: 6, background: '#fffbeb',
              border: '1px solid #fde68a', color: '#92400e', fontSize: 12 }}>
              ⚠ インボイスと結び付いていない許可書：{data.not_allocated.join('、')}
              （仕入管理でインボイスに許可書を合わせて保存すると、関税・消費税が商品原価へ按分されます）
            </div>
          )}
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={th}>許可日</th>
                  <th style={th}>申告番号</th>
                  <th style={th}>便</th>
                  <th style={{ ...th, textAlign: 'right' }}>仕入書価格</th>
                  <th style={{ ...th, textAlign: 'right' }}>関税</th>
                  <th style={{ ...th, textAlign: 'right' }}>消費税</th>
                  <th style={{ ...th, textAlign: 'right' }}>地方消費税</th>
                  <th style={{ ...th, textAlign: 'right' }}>合計</th>
                  <th style={th}>インボイス</th>
                  <th style={th}></th>
                </tr>
              </thead>
              <tbody>
                {data.items.map(x => (
                  <tr key={x.id}>
                    <td style={td}>{x.permit_date}</td>
                    <td style={{ ...td, fontFamily: 'monospace' }}>{x.permit_no}</td>
                    <td style={td}>{x.transport}{x.weight ? `・${x.weight}kg` : ''}</td>
                    <td style={{ ...td, textAlign: 'right' }}>{Number(x.permit_cny || 0).toLocaleString('ja-JP')}元</td>
                    <td style={{ ...td, textAlign: 'right' }}>{yen(x.customs_duty)}</td>
                    <td style={{ ...td, textAlign: 'right' }}>{yen(x.consumption_tax)}</td>
                    <td style={{ ...td, textAlign: 'right' }}>{yen(x.local_consumption_tax)}</td>
                    <td style={{ ...td, textAlign: 'right', fontWeight: 600 }}>{yen(x.total_tax)}</td>
                    <td style={td}>
                      {x.invoices.length
                        ? <span style={{ color: C.good }}>按分済み（{x.invoices.join('、')}）</span>
                        : <span style={{ color: C.warn }}>未照合</span>}
                    </td>
                    <td style={td}>
                      {x.has_pdf && (
                        <button className="btn btn-secondary" style={{ fontSize: 11, padding: '2px 8px' }}
                          onClick={async () => {
                            // ログインの印が要るので、取ってから開く（リンクだと開けない）
                            const w = window.open('', '_blank')
                            try {
                              const r = await api.get(`/import-permits/${x.id}/pdf`, { responseType: 'blob' })
                              const href = URL.createObjectURL(r.data)
                              if (w) w.location.href = href
                              else window.location.href = href
                            } catch (e) {
                              if (w) w.close()
                              setErr('PDFを開けませんでした：' + (e.message || ''))
                            }
                          }}>PDF</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
