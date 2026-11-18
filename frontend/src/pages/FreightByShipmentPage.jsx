import { Fragment, useEffect, useState } from 'react'
import api from '../api/client'

/**
 * 月次管理表の「🚢 便ごとの送料」。
 *
 * 入出金明細には国際運賃の行がほとんど出ないので、配送依頼（便）ごとの費用を
 * タオタロウから取り込んで保存し、出荷日の月で並べる。
 * 送料の商品ごとの按分は、仕入管理（インボイスの取り込み）がすでにやっている
 * （箱の重量で按分。箱データが無い便は金額比）。その結果を便の下に出す。
 * インボイスを取り込んでいない便は「未取り込み」と出す。
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
  const [meta, setMeta] = useState(null)
  const [syncing, setSyncing] = useState(false)
  const [syncMsg, setSyncMsg] = useState('')
  const [reload, setReload] = useState(0)

  const loadMonths = () => api.get('/accounting/freight/months')
    .then(r => {
      const m = r.data.months || []
      setMonths(m)
      setMeta(r.data)
      setYm(cur => (cur && m.includes(cur)) ? cur : (m[0] || ''))
      setReload(n => n + 1)
    })
    .catch(e => setErr(e.response?.data?.detail || e.message))

  useEffect(() => { loadMonths() }, [])

  useEffect(() => {
    if (!ym) return
    setData(null)
    api.get('/accounting/freight', { params: { ym } })
      .then(r => setData(r.data))
      .catch(e => setErr(e.response?.data?.detail || e.message))
  }, [ym, reload])

  const sync = async () => {
    setSyncing(true); setSyncMsg(''); setErr('')
    try {
      const r = await api.post('/accounting/freight/sync', null, { timeout: 300000 })
      const d = r.data
      setSyncMsg(`取り込みました：新しい便 ${d.added}・更新 ${d.updated}・変わりなし ${d.skipped}`
        + (d.errors?.length ? `（取れなかった便：${d.errors.join('、')}）` : ''))
      await loadMonths()
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally {
      setSyncing(false)
    }
  }

  return (
    <div>
      <div className="card" style={{ marginBottom: 12 }}>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <b style={{ fontSize: 16 }}>🚢 便ごとの送料</b>
          <select value={ym} onChange={e => setYm(e.target.value)} style={{ fontSize: 13, padding: '4px 8px' }}>
            {months.map(m => <option key={m} value={m}>{m}</option>)}
          </select>
          <button className="btn btn-secondary" style={{ fontSize: 12 }} disabled={syncing} onClick={sync}>
            {syncing ? '取り込み中…（1〜2分）' : '🔄 タオタロウから取り込む'}
          </button>
          {data && (
            <span style={{ fontSize: 13, color: C.text }}>
              送料（国内＋国際） <b>{yuan(data.totals?.shipping)}</b>　／　便 {data.ship_count}　／
              インボイス取り込み済み <b style={{ color: data.imported_count === data.ship_count ? C.good : C.warn }}>
                {data.imported_count}/{data.ship_count}</b>
            </span>
          )}
        </div>
        <div style={{ fontSize: 12, color: C.sub, marginTop: 8, lineHeight: 1.8 }}>
          配送依頼（便）ごとの費用をタオタロウから取り込み、<b>出荷日の月</b>で数えています。
          費用が確定した便（出荷待ち・出荷済み・受け取り済み）だけが対象です。
          商品ごとの内訳は、仕入管理でインボイスを保存したときの按分結果です
          （送料は箱の重量で按分。箱データが無い便は金額比）。
          「差」は、便の送料（国内＋国際）とインボイスで按分した送料の差です。
          {meta && <> 取り込み済み {meta.count}便{meta.synced_at ? `（最終 ${meta.synced_at.slice(0, 16).replace('T', ' ')}）` : ''}。</>}
        </div>
        {syncMsg && <div style={{ color: C.good, fontSize: 12, marginTop: 6 }}>{syncMsg}</div>}
        {data?.totals && (
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 12, color: C.text, marginTop: 8 }}>
            <span>国内運賃 {yuan(data.totals.domestic)}</span>
            <span>国際送料 {yuan(data.totals.international)}</span>
            <span>通関手数料 {yuan(data.totals.customs_fee)}</span>
            <span>代行手数料 {yuan(data.totals.server_fee)}</span>
            {data.totals.remote_fee > 0 && <span>遠隔地 {yuan(data.totals.remote_fee)}</span>}
            <span>便の請求合計 <b>{yuan(data.totals.total_send_fee)}</b></span>
          </div>
        )}
        {data?.missing?.length > 0 && (
          <div style={{ marginTop: 8, padding: '8px 12px', borderRadius: 6, background: '#fffbeb',
            border: '1px solid #fde68a', color: '#92400e', fontSize: 13 }}>
            ⚠ インボイスをまだ取り込んでいない便：{data.missing.join('、')}
            <div style={{ fontSize: 12 }}>仕入管理（Amazon／楽天）でインボイスを取り込むと、商品ごとの内訳が出ます。</div>
          </div>
        )}
        {err && <div style={{ color: C.bad, fontSize: 12, marginTop: 6 }}>{err}</div>}
      </div>

      {!data && !err && ym && <div className="card" style={{ color: C.sub }}>読み込んでいます…</div>}
      {meta && !meta.count && !syncing && (
        <div className="card" style={{ color: C.sub }}>まだ便を取り込んでいません。「🔄 タオタロウから取り込む」を押してください。</div>
      )}

      {data && (
        <div className="card" style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th style={th}>便（配送依頼番号）</th>
                <th style={th}>出荷日</th>
                <th style={{ ...th, textAlign: 'right' }}>国内運賃</th>
                <th style={{ ...th, textAlign: 'right' }}>国際送料</th>
                <th style={{ ...th, textAlign: 'right' }}>送料計</th>
                <th style={{ ...th, textAlign: 'right' }}>通関・代行ほか</th>
                <th style={th}>インボイス</th>
                <th style={{ ...th, textAlign: 'right' }}>按分した送料</th>
                <th style={{ ...th, textAlign: 'right' }}>差</th>
              </tr>
            </thead>
            <tbody>
              {data.ships.map(s => {
                const key = s.sn || s.sid
                const bigDiff = s.diff_cny != null && Math.abs(s.diff_cny) > Math.max(5, s.shipping * 0.05)
                const others = (s.customs_fee || 0) + (s.server_fee || 0) + (s.remote_fee || 0)
                return (
                  <Fragment key={key}>
                    <tr style={{ cursor: s.imported ? 'pointer' : 'default' }}
                      onClick={() => s.imported && setOpen(o => ({ ...o, [key]: !o[key] }))}>
                      <td style={{ ...td, fontWeight: 600 }}>
                        {s.imported && <span style={{ color: C.sub, marginRight: 4 }}>{open[key] ? '▾' : '▸'}</span>}
                        {s.sn || '—'}
                        <div style={{ fontSize: 11, color: C.sub, fontWeight: 400 }}>
                          {s.delivery_name}{s.weight ? `・${s.weight}kg` : ''}{s.state_label ? `・${s.state_label}` : ''}
                        </div>
                      </td>
                      <td style={{ ...td, color: C.sub }}>{s.shipped_date}</td>
                      <td style={{ ...td, textAlign: 'right' }}>{yuan(s.domestic)}</td>
                      <td style={{ ...td, textAlign: 'right' }}>{yuan(s.international)}</td>
                      <td style={{ ...td, textAlign: 'right', fontWeight: 700 }}>{yuan(s.shipping)}</td>
                      <td style={{ ...td, textAlign: 'right', color: C.sub }}>{yuan(others)}</td>
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
                        <td colSpan={9} style={{ ...td, background: '#f8fafc', padding: '6px 8px 10px 28px' }}>
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
                <tr><td colSpan={9} style={{ ...td, color: C.sub, textAlign: 'center', padding: 24 }}>
                  この月に出荷された便はありません
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
