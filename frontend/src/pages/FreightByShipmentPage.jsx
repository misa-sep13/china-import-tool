import { Fragment, useEffect, useState } from 'react'
import api from '../api/client'

/**
 * 月次管理表の「🚢 便ごとの送料」。
 *
 * 送料の商品ごとの按分は、仕入管理（インボイスの取り込み）がすでにやっている
 * （箱の重量で按分。箱データが無い便は金額比）。ここでは作り直さず、
 *   ・その月に引き落とされた運賃（タオタロウの明細の国際運賃・国内運賃）
 *   ・保存済みインボイスの按分結果（インボイス番号＝配送依頼の番号）
 * を便ごとに並べる。インボイスを取り込んでいない便は「未取り込み」と出す。
 */

const C = { line: '#e5e7eb', sub: '#64748b', text: '#0f172a', bad: '#dc2626', warn: '#b45309', good: '#16a34a' }
const th = { padding: '6px 8px', textAlign: 'left', fontSize: 12, color: C.sub, background: '#f8fafc', whiteSpace: 'nowrap' }
const td = { padding: '6px 8px', borderTop: `1px solid ${C.line}`, fontSize: 13, verticalAlign: 'top' }
const yuan = v => (v == null ? '—' : `${Number(v).toLocaleString('ja-JP', { maximumFractionDigits: 2 })}元`)
const yen = v => (v == null ? '—' : `¥${Math.round(v).toLocaleString('ja-JP')}`)

export default function FreightByShipmentPage() {
  const [months, setMonths] = useState([])
  const [ym, setYm] = useState('')
  const [data, setData] = useState(null)
  const [open, setOpen] = useState({})
  const [err, setErr] = useState('')

  useEffect(() => {
    api.get('/accounting/freight/months')
      .then(r => {
        const m = r.data.months || []
        setMonths(m)
        if (m.length) setYm(m[0])
      })
      .catch(e => setErr(e.response?.data?.detail || e.message))
  }, [])

  useEffect(() => {
    if (!ym) return
    setData(null)
    api.get('/accounting/freight', { params: { ym } })
      .then(r => setData(r.data))
      .catch(e => setErr(e.response?.data?.detail || e.message))
  }, [ym])

  return (
    <div>
      <div className="card" style={{ marginBottom: 12 }}>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <b style={{ fontSize: 16 }}>🚢 便ごとの送料</b>
          <select value={ym} onChange={e => setYm(e.target.value)} style={{ fontSize: 13, padding: '4px 8px' }}>
            {months.map(m => <option key={m} value={m}>{m}</option>)}
          </select>
          {data && (
            <span style={{ fontSize: 13, color: C.text }}>
              運賃 <b>{yuan(data.total_cny)}</b>　／　便 {data.ship_count}　／
              インボイス取り込み済み <b style={{ color: data.imported_count === data.ship_count ? C.good : C.warn }}>
                {data.imported_count}/{data.ship_count}</b>
            </span>
          )}
        </div>
        <div style={{ fontSize: 12, color: C.sub, marginTop: 8, lineHeight: 1.8 }}>
          運賃はタオタロウから引き落とされた月で数えています（国際運賃・国内運賃）。
          商品ごとの内訳は、仕入管理でインボイスを保存したときの按分結果です
          （送料は箱の重量で按分。箱データが無い便は金額比）。
          「差」は、引き落とされた運賃とインボイスで按分した送料の差です。
        </div>
        {data?.missing?.length > 0 && (
          <div style={{ marginTop: 8, padding: '8px 12px', borderRadius: 6, background: '#fffbeb',
            border: '1px solid #fde68a', color: '#92400e', fontSize: 13 }}>
            ⚠ インボイスをまだ取り込んでいない便：{data.missing.join('、')}
            <div style={{ fontSize: 12 }}>仕入管理（Amazon／楽天）でインボイスを取り込むと、商品ごとの内訳が出ます。</div>
          </div>
        )}
        {err && <div style={{ color: C.bad, fontSize: 12, marginTop: 6 }}>{err}</div>}
      </div>

      {!data && !err && <div className="card" style={{ color: C.sub }}>読み込んでいます…</div>}

      {data && (
        <div className="card" style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th style={th}>便（配送依頼番号）</th>
                <th style={th}>引落日</th>
                <th style={{ ...th, textAlign: 'right' }}>国内運賃</th>
                <th style={{ ...th, textAlign: 'right' }}>国際運賃</th>
                <th style={{ ...th, textAlign: 'right' }}>運賃計</th>
                <th style={th}>インボイス</th>
                <th style={{ ...th, textAlign: 'right' }}>按分した送料</th>
                <th style={{ ...th, textAlign: 'right' }}>差</th>
              </tr>
            </thead>
            <tbody>
              {data.ships.map(s => {
                const key = s.sn || s.sid
                const bigDiff = s.diff_cny != null && Math.abs(s.diff_cny) > Math.max(5, s.total * 0.05)
                return (
                  <Fragment key={key}>
                    <tr style={{ cursor: s.imported ? 'pointer' : 'default' }}
                      onClick={() => s.imported && setOpen(o => ({ ...o, [key]: !o[key] }))}>
                      <td style={{ ...td, fontWeight: 600 }}>
                        {s.imported && <span style={{ color: C.sub, marginRight: 4 }}>{open[key] ? '▾' : '▸'}</span>}
                        {s.sn || '—'}
                        <div style={{ fontSize: 11, color: C.sub, fontWeight: 400 }}>sid {s.sid}</div>
                      </td>
                      <td style={{ ...td, color: C.sub }}>{(s.first_at || '').slice(0, 10)}</td>
                      <td style={{ ...td, textAlign: 'right' }}>{yuan(s.domestic)}</td>
                      <td style={{ ...td, textAlign: 'right' }}>{yuan(s.international)}</td>
                      <td style={{ ...td, textAlign: 'right', fontWeight: 700 }}>{yuan(s.total)}</td>
                      <td style={td}>
                        {s.imported
                          ? <span style={{ color: C.good }}>取り込み済み（{s.items.length}行・{s.method || '—'}）</span>
                          : <span style={{ color: C.warn }}>未取り込み</span>}
                      </td>
                      <td style={{ ...td, textAlign: 'right' }}>{s.imported ? yuan(s.allocated_cny) : '—'}</td>
                      <td style={{ ...td, textAlign: 'right', color: bigDiff ? C.bad : C.sub, fontWeight: bigDiff ? 700 : 400 }}>
                        {s.diff_cny == null ? '—' : yuan(s.diff_cny)}
                      </td>
                    </tr>
                    {open[key] && (
                      <tr>
                        <td colSpan={8} style={{ ...td, background: '#f8fafc', padding: '6px 8px 10px 28px' }}>
                          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                            <thead>
                              <tr>
                                <th style={th}>種類</th>
                                <th style={th}>SKU</th>
                                <th style={{ ...th, textAlign: 'right' }}>数</th>
                                <th style={{ ...th, textAlign: 'right' }}>商品代</th>
                                <th style={{ ...th, textAlign: 'right' }}>按分した送料</th>
                                <th style={{ ...th, textAlign: 'right' }}>税</th>
                                <th style={{ ...th, textAlign: 'right' }}>通関料</th>
                                <th style={{ ...th, textAlign: 'right' }}>原価（1セット／資材は合計）</th>
                              </tr>
                            </thead>
                            <tbody>
                              {s.items.map((x, i) => (
                                <tr key={i}>
                                  <td style={td}>{x.kind}{x.source ? `（${x.source === 'rakuten' ? '楽天' : 'Amazon'}）` : ''}</td>
                                  <td style={td}>{x.sku}</td>
                                  <td style={{ ...td, textAlign: 'right' }}>{x.qty}</td>
                                  <td style={{ ...td, textAlign: 'right' }}>{yuan(x.goods_cny)}</td>
                                  <td style={{ ...td, textAlign: 'right', fontWeight: 600 }}>{yuan(x.freight_cny)}</td>
                                  <td style={{ ...td, textAlign: 'right' }}>{yen(x.tax_jpy)}</td>
                                  <td style={{ ...td, textAlign: 'right' }}>{yen(x.customs_jpy)}</td>
                                  <td style={{ ...td, textAlign: 'right' }}>{yen(x.cost_jpy)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
              {!data.ships.length && (
                <tr><td colSpan={8} style={{ ...td, color: C.sub, textAlign: 'center', padding: 24 }}>
                  この月に運賃の引落はありません
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
