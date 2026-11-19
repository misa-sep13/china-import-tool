import { Fragment, useEffect, useState } from 'react'
import api from '../api/client'
import UndatedReceipts from '../components/UndatedReceipts'

/**
 * 月次管理表の「📈 月次サマリー」。
 *
 * 各タブの数字を月ごとに1行にまとめる。
 *   売上       … 楽天（売上管理で取り込んだ月）＋ Amazon（日別実績）
 *   当月の仕入 … 発生ベース（商品代・中国国内送料・代行手数料・国際送料・通関手数料・関税）
 *   売上原価   … 期首在庫 ＋ 当月の仕入 − 期末在庫
 *   粗利       … 売上 − 売上原価
 *   販管費     … 広告宣伝費・販売促進費・支払手数料
 *   営業利益   … 粗利 − 販管費
 * 輸入消費税（仮払）は原価に入れず別に出す。
 */

const C = { line: '#e5e7eb', sub: '#64748b', text: '#0f172a', good: '#16a34a', bad: '#dc2626', warn: '#b45309' }
const th = { padding: '6px 8px', textAlign: 'right', fontSize: 12, color: C.sub, background: '#f8fafc', whiteSpace: 'nowrap' }
const td = { padding: '6px 8px', borderTop: `1px solid ${C.line}`, fontSize: 13, textAlign: 'right', whiteSpace: 'nowrap' }
const yen = v => (v == null ? '—' : `¥${Math.round(v).toLocaleString('ja-JP')}`)

const SGA = [
  ['ad', '広告宣伝費', 'RPP・クーポン広告・アフィリエイト'],
  ['promo', '販売促進費', 'ポイント原資・クーポン'],
  ['platform_fee', '支払手数料（楽天）', '決済手数料・システム利用料・出店料'],
  ['shipping', '荷造運賃', 'ヤマト運輸の請求書'],
  ['fixed', '支払手数料（代行）', 'タオタロウ月会費'],
]

const PURCHASE = [
  ['goods', '商品代（値引・調整・削除を含む）', '明細の日'],
  ['domestic', '中国国内送料', '便の出荷日'],
  ['agency', '代行手数料', '便の出荷日'],
  ['international', '国際送料', '便の出荷日'],
  ['customs_fee', '通関手数料', '便の出荷日'],
  ['duty', '関税', '輸入許可日'],
]

export default function MonthlySummaryPage({ share = '' }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [open, setOpen] = useState({})
  const [showOld, setShowOld] = useState(false)
  // 売上も原価も出ていない古い月は、最初はたたんでおく（見たい月が埋もれるので）。
  // 数字が出ている最初の月から後ろは、売上がまだ無い直近の月も出す
  const allMonths = data?.months || []
  const activeYms = allMonths.filter(m => m.has_rakuten_sales || m.cogs != null || m.sales_amazon > 0).map(m => m.ym)
  const firstActive = activeYms.length ? activeYms[activeYms.length - 1] : ''
  const visibleMonths = showOld || !firstActive ? allMonths : allMonths.filter(m => m.ym >= firstActive)
  const hiddenCount = allMonths.length - allMonths.filter(m => !firstActive || m.ym >= firstActive).length

  // share が入っているのは税理士向けの公開ページ。合言葉つきで読むだけ
  const load = () => api.get('/accounting/summary',
    { params: share ? { months: 18, share } : { months: 18 } })
    .then(r => setData(r.data))
    .catch(e => setErr(e.response?.data?.detail || e.message))

  useEffect(() => { load() }, [])

  // タオタロウの注文ごとに、Amazon向けか楽天向けかを決め直す（仕入を販路で分けるため）
  const [chBusy, setChBusy] = useState(false)
  const [chMsg, setChMsg] = useState('')
  const syncChannel = async () => {
    setChBusy(true); setChMsg('')
    try {
      const r = await api.post('/accounting/channel/sync', null, { timeout: 300000 })
      const b = r.data.by_channel || {}
      setChMsg(`タオタロウの注文 ${r.data.seen}件を振り分けました（Amazon ${b.amazon || 0}件・楽天 ${b.rakuten || 0}件）`)
      await load()
    } catch (e) {
      setChMsg('振り分けできませんでした：' + (e.response?.data?.detail || e.message))
    } finally { setChBusy(false) }
  }

  return (
    <div>
      {!share && <UndatedReceipts onChanged={load} />}

      <div className="card" style={{ marginBottom: 12 }}>
        <b style={{ fontSize: 16 }}>📈 月次サマリー（発生ベース）</b>
        <div style={{ fontSize: 12, color: C.sub, marginTop: 6, lineHeight: 1.9 }}>
          売上原価は2つに分けて出しています。
          <b>中国輸入品 ＝ 期首在庫 ＋ 当月の仕入 − 期末在庫</b>（在庫は中国輸入品のぶんだけ）、
          <b>日本メーカー品 ＝ 売れた数 × 原価</b>（メーカー品の仕入はツールに無いため、楽天の売上管理の原価を使用）。
          仕入はその月に実際に発生したぶん（商品代は明細の日、送料・手数料は便の出荷日、関税は輸入許可日）で、
          チャージ（前払金）は入れていません。元はその月のタオタロウ明細の実勢レートで円にしています。
          <br />
          輸入時の消費税は仮払消費税なので原価に入れず、別に出しています。
          <b>販管費</b>は広告宣伝費・販売促進費（ポイント・クーポン）・支払手数料で、粗利から引くと営業利益です。
          楽天への費用は<b>店舗別内訳書の実額</b>を使います（読めていない月だけ率からの見込み）。
          内訳書は<b>精算対象期間の月</b>に入れています。3月分のシステム利用料が6月発行の請求書に
          載るなど、品目ごとに遅れ方が違うためです。ヤマトの送料は請求書の締め月に入れています。
          人件費・地代など、ツールの外にある費用はまだ入っていません。
          行を押すと内訳が出ます。
          <br />
          <b>楽天とAmazonは分けて計算しています。</b>タオタロウの仕入は注文ごとに（FBAの印・ASIN・マスタで）Amazon向けか楽天向けかを見分け、
          便の送料・手数料は便の中身の金額の割合、関税はその月の商品代の割合で配ります。見分けがつかない注文は楽天に入れます。
          Amazonは月末在庫の記録が始まるまで、仕入を「売れていない在庫」として原価に入れません。
        </div>
        {!share && (
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginTop: 8, flexWrap: 'wrap' }}>
            <button className="btn btn-secondary" style={{ fontSize: 12 }} disabled={chBusy} onClick={syncChannel}>
              {chBusy ? '振り分けています…（1〜2分）' : '🔀 楽天／Amazonの振り分けを更新'}
            </button>
            {chMsg && <span style={{ fontSize: 12, color: chMsg.startsWith('振り分けでき') ? C.bad : C.good }}>{chMsg}</span>}
          </div>
        )}
        {err && <div style={{ color: C.bad, fontSize: 12, marginTop: 6 }}>{err}</div>}
      </div>

      {!data && !err && <div className="card" style={{ color: C.sub }}>読み込んでいます…</div>}

      {data && (
        <div className="card" style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 1100 }}>
            <thead>
              <tr>
                <th style={{ ...th, textAlign: 'left' }}>月</th>
                <th style={{ ...th, textAlign: 'left' }}>販路</th>
                <th style={th}>売上</th>
                <th style={th}>中国輸入の原価</th>
                <th style={th}>メーカー品の原価</th>
                <th style={th}>売上原価 計</th>
                <th style={th}>粗利</th>
                <th style={th}>粗利率</th>
                <th style={th}>販管費</th>
                <th style={th}>営業利益</th>
                <th style={th}>営業利益率</th>
                <th style={th} title="仕入れて、まだ売れていない分。Amazonは月末在庫の記録が始まるまで原価に入れず、ここに積みます">
                  在庫へ積んだ仕入
                </th>
                <th style={th}>輸入消費税（仮払）</th>
              </tr>
            </thead>
            <tbody>
              {visibleMonths.map(m => {
                const dash = <span style={{ color: '#cbd5e1' }}>—</span>
                const pct = (a, b) => (a != null && b ? `${Math.round(a / b * 1000) / 10}%` : null)
                const money = (v, color) => (v == null ? dash
                  : <span style={color ? { color: v >= 0 ? C.good : C.bad, fontWeight: 700 } : undefined}>{yen(v)}</span>)
                // 楽天：中国輸入（楽天向け）＋メーカー品。販管費は今のところ全部楽天の費用
                const rkSales = m.has_rakuten_sales ? m.sales_rakuten : null
                const rkCogs = m.china_cogs != null ? m.china_cogs + (m.manu_cogs || 0) : null
                const rkGross = rkSales != null && rkCogs != null ? rkSales - rkCogs : null
                const rkOp = rkGross != null ? rkGross - (m.sga_total || 0) : null
                // Amazon：在庫の記録が始まるまでは原価0、仕入は在庫へ積む。販管費（Amazonの手数料など）はまだ取り込んでいない
                const amzSales = m.sales_amazon || 0
                const amzCogs = m.amazon_cogs || 0
                const amzGross = amzSales || amzCogs ? amzSales - amzCogs : null
                const amzStock = m.amazon_method === 'inventory' ? null : (m.purchase_amazon_total || 0)
                const rows = [
                  { key: 'rk', label: '楽天', sales: rkSales, salesNote: m.has_rakuten_sales ? null : '未取込',
                    china: m.china_cogs, manu: m.manu_cogs, cogs: rkCogs, gross: rkGross,
                    sga: m.sga_total, op: rkOp, stock: null, vat: (m.import_vat || 0) - (m.import_vat_amazon || 0) },
                  { key: 'amz', label: 'Amazon', sales: amzSales || null, salesNote: amzSales ? null : '—',
                    china: m.amazon_method === 'inventory' ? amzCogs : (amzSales ? 0 : null), manu: null,
                    cogs: amzGross != null ? amzCogs : null, gross: amzGross,
                    sga: null, sgaNote: amzSales ? '未取込' : null, op: null,
                    stock: amzStock >= 1000 ? amzStock : null, vat: m.import_vat_amazon || 0 },
                  { key: 'all', label: '合計', sales: m.has_rakuten_sales ? m.sales : null, salesNote: m.has_rakuten_sales ? null : '—',
                    china: m.china_cogs != null ? m.china_cogs + amzCogs : null, manu: m.manu_cogs, cogs: m.cogs,
                    gross: m.gross_profit, sga: m.sga_total, op: m.operating_profit,
                    stock: amzStock >= 1000 ? amzStock : null, vat: m.import_vat || 0 },
                ]
                return (
                <Fragment key={m.ym}>
                  {rows.map((r, i) => {
                    const isAll = r.key === 'all'
                    const rowTd = { ...td, ...(isAll ? { fontWeight: 700, background: '#f8fafc' } : {}),
                      ...(i === 0 ? { borderTop: '2px solid #cbd5e1' } : { borderTop: `1px dashed ${C.line}` }) }
                    return (
                      <tr key={r.key} style={{ cursor: 'pointer' }} onClick={() => setOpen(o => ({ ...o, [m.ym]: !o[m.ym] }))}>
                        {i === 0 && (
                          <td rowSpan={3} style={{ ...td, textAlign: 'left', fontWeight: 700, verticalAlign: 'top',
                            borderTop: '2px solid #cbd5e1' }}>
                            <span style={{ color: C.sub, marginRight: 4 }}>{open[m.ym] ? '▾' : '▸'}</span>{m.ym}
                          </td>
                        )}
                        <td style={{ ...rowTd, textAlign: 'left',
                          color: r.key === 'rk' ? '#bf0000' : r.key === 'amz' ? '#c45500' : C.text }}>{r.label}</td>
                        <td style={rowTd}>
                          {r.sales != null ? yen(r.sales)
                            : <span style={{ color: r.salesNote === '未取込' ? C.warn : '#cbd5e1', fontWeight: 400 }}>{r.salesNote || '—'}</span>}
                        </td>
                        <td style={rowTd}>{r.key === 'rk' && r.china == null ? <span style={{ color: C.sub, fontWeight: 400 }}>在庫未確定</span> : money(r.china)}</td>
                        <td style={rowTd}>{money(r.manu)}</td>
                        <td style={rowTd}>{money(r.cogs)}</td>
                        <td style={rowTd}>{money(r.gross, true)}</td>
                        <td style={{ ...rowTd, color: C.sub }}>{pct(r.gross, r.sales) || dash}</td>
                        <td style={rowTd}>{r.sga != null ? yen(r.sga) : (r.sgaNote ? <span style={{ color: C.warn, fontWeight: 400 }}>{r.sgaNote}</span> : dash)}</td>
                        <td style={rowTd}>{money(r.op, true)}</td>
                        <td style={{ ...rowTd, color: C.sub }}>{pct(r.op, r.sales) || dash}</td>
                        <td style={{ ...rowTd, color: C.sub }}>{r.stock ? yen(r.stock) : dash}</td>
                        <td style={{ ...rowTd, color: C.sub }}>{r.vat ? yen(r.vat) : dash}</td>
                      </tr>
                    )
                  })}
                  {open[m.ym] && (
                    <tr>
                      <td colSpan={13}style={{ ...td, textAlign: 'left', background: '#f8fafc', padding: '8px 12px 12px 28px' }}>
                        {/* 売上原価の内訳（表では1列にまとめている） */}
                        <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', fontSize: 13, marginBottom: 10,
                          padding: '8px 10px', background: '#fff', border: `1px solid ${C.line}`, borderRadius: 6 }}>
                          <b>売上原価の内訳</b>
                          <span>中国輸入（楽天） <b>{m.china_cogs == null ? '在庫未確定' : yen(m.china_cogs)}</b></span>
                          <span>メーカー品 <b>{yen(m.manu_cogs)}</b></span>
                          <span>Amazon <b>{yen(m.amazon_cogs)}</b>
                            {m.amazon_method !== 'inventory' && m.purchase_amazon_total > 0 &&
                              <span style={{ color: C.sub }}>（仕入 {yen(m.purchase_amazon_total)} は在庫へ）</span>}
                          </span>
                          {m.sales_amazon > 0 && <span>売上：楽天 {yen(m.sales_rakuten)}・Amazon {yen(m.sales_amazon)}</span>}
                        </div>
                        <table style={{ borderCollapse: 'collapse' }}>
                          <tbody>
                            <tr>
                              <td colSpan={3} style={{ ...td, textAlign: 'left', borderTop: 'none', fontWeight: 700 }}>中国輸入品の売上原価（楽天）</td>
                            </tr>
                            <tr>
                              <td style={{ ...td, textAlign: 'left', borderTop: 'none' }}>期首在庫（中国輸入品）</td>
                              <td style={{ ...td, borderTop: 'none', color: C.sub, fontSize: 11 }}>前月末</td>
                              <td style={{ ...td, borderTop: 'none' }}>{m.inventory_begin == null ? '未確定' : yen(m.inventory_begin)}</td>
                            </tr>
                            {PURCHASE.map(([k, label, when]) => (
                              <tr key={k}>
                                <td style={{ ...td, textAlign: 'left', borderTop: 'none' }}>{label}</td>
                                <td style={{ ...td, borderTop: 'none', color: C.sub, fontSize: 11 }}>{when}</td>
                                <td style={{ ...td, borderTop: 'none' }}>{yen(m.purchase[k])}</td>
                              </tr>
                            ))}
                            <tr>
                              <td style={{ ...td, textAlign: 'left', fontWeight: 700 }}>当月の仕入 計（楽天向け）</td>
                              <td style={td}></td>
                              <td style={{ ...td, fontWeight: 700 }}>{yen(m.purchase_total)}</td>
                            </tr>
                            <tr>
                              <td style={{ ...td, textAlign: 'left' }}>期末在庫（中国輸入品）</td>
                              <td style={{ ...td, color: C.sub, fontSize: 11 }}>当月末</td>
                              <td style={td}>{m.inventory_end == null ? '未確定' : `−${yen(m.inventory_end)}`}</td>
                            </tr>
                            <tr>
                              <td style={{ ...td, textAlign: 'left', fontWeight: 700 }}>中国輸入品の売上原価（楽天）</td>
                              <td style={td}></td>
                              <td style={{ ...td, fontWeight: 700 }}>{yen(m.china_cogs)}</td>
                            </tr>
                            <tr>
                              <td colSpan={3} style={{ ...td, textAlign: 'left', fontWeight: 700, paddingTop: 14 }}>Amazon（FBA）</td>
                            </tr>
                            <tr>
                              <td style={{ ...td, textAlign: 'left', borderTop: 'none' }}>期首在庫（Amazon）</td>
                              <td style={{ ...td, borderTop: 'none', color: C.sub, fontSize: 11 }}>前月末</td>
                              <td style={{ ...td, borderTop: 'none' }}>{m.amazon_inventory_begin == null ? '未記録' : yen(m.amazon_inventory_begin)}</td>
                            </tr>
                            {PURCHASE.map(([k, label]) => (
                              <tr key={'amz-' + k}>
                                <td style={{ ...td, textAlign: 'left', borderTop: 'none', paddingLeft: 24, color: C.sub }}>{label}</td>
                                <td style={{ ...td, borderTop: 'none' }}></td>
                                <td style={{ ...td, borderTop: 'none', color: C.sub }}>{yen(m.purchase_amazon?.[k])}</td>
                              </tr>
                            ))}
                            <tr>
                              <td style={{ ...td, textAlign: 'left', borderTop: 'none' }}>当月の仕入（Amazon向け）</td>
                              <td style={{ ...td, borderTop: 'none' }}></td>
                              <td style={{ ...td, borderTop: 'none' }}>{yen(m.purchase_amazon_total)}</td>
                            </tr>
                            <tr>
                              <td style={{ ...td, textAlign: 'left', borderTop: 'none' }}>期末在庫（Amazon）</td>
                              <td style={{ ...td, borderTop: 'none', color: C.sub, fontSize: 11 }}>当月末</td>
                              <td style={{ ...td, borderTop: 'none' }}>{m.amazon_inventory_end == null ? '未記録' : `−${yen(m.amazon_inventory_end)}`}</td>
                            </tr>
                            <tr>
                              <td style={{ ...td, textAlign: 'left', fontWeight: 700 }}>
                                Amazonの売上原価
                                <span style={{ fontWeight: 400, color: C.sub, fontSize: 11, marginLeft: 6 }}>
                                  {m.amazon_method === 'inventory' ? '在庫式' : '在庫の記録がまだ無いので、仕入は全部「売れていない在庫」に積んでいます'}
                                </span>
                              </td>
                              <td style={td}></td>
                              <td style={{ ...td, fontWeight: 700 }}>{yen(m.amazon_cogs)}</td>
                            </tr>
                            <tr>
                              <td colSpan={3} style={{ ...td, textAlign: 'left', fontWeight: 700, paddingTop: 14 }}>日本メーカー品の売上原価</td>
                            </tr>
                            <tr>
                              <td style={{ ...td, textAlign: 'left', borderTop: 'none' }}>期首在庫（メーカー品）</td>
                              <td style={{ ...td, borderTop: 'none', color: C.sub, fontSize: 11 }}>前月末</td>
                              <td style={{ ...td, borderTop: 'none' }}>{m.manu_inventory_begin == null ? '未確定' : yen(m.manu_inventory_begin)}</td>
                            </tr>
                            <tr>
                              <td style={{ ...td, textAlign: 'left', borderTop: 'none' }}>当月の仕入（メーカー品）</td>
                              <td style={{ ...td, borderTop: 'none', color: C.sub, fontSize: 11 }}>
                                {m.manu_purchase_source === 'invoice' ? '請求書（請求日）'
                                  : m.manu_purchase_source === 'mixed' ? '取引先ごとに請求書／入荷日'
                                  : '入荷した日'}
                              </td>
                              <td style={{ ...td, borderTop: 'none' }}>{yen(m.manu_purchase)}</td>
                            </tr>
                            {Object.entries(m.manu_by_supplier || {}).map(([sup, v]) => (
                              <tr key={sup}>
                                <td style={{ ...td, textAlign: 'left', borderTop: 'none', paddingLeft: 24, color: C.sub }}>
                                  {sup || '（取引先不明）'}
                                </td>
                                <td style={{ ...td, borderTop: 'none', fontSize: 11,
                                  color: v.source === 'receipt' ? C.warn : C.good }}>
                                  {{ invoice: '請求書', bank: '銀行の出金', bank_invoice: '請求書＋銀行の出金' }[v.source] || '入荷履歴'}
                                  {v.gap > 0 && (v.source === 'invoice' || v.source === 'receipt') && (
                                    <span style={{ color: C.bad, marginLeft: 6 }}>
                                      {v.source === 'receipt' ? '請求書が不足しています'
                                        : '入荷の記録が不足しています'}
                                    </span>
                                  )}
                                </td>
                                <td style={{ ...td, borderTop: 'none', color: C.sub }}>{yen(v.used)}</td>
                              </tr>
                            ))}
                            <tr>
                              <td style={{ ...td, textAlign: 'left', borderTop: 'none' }}>期末在庫（メーカー品）</td>
                              <td style={{ ...td, borderTop: 'none', color: C.sub, fontSize: 11 }}>当月末</td>
                              <td style={{ ...td, borderTop: 'none' }}>{m.manu_inventory_end == null ? '未確定' : `−${yen(m.manu_inventory_end)}`}</td>
                            </tr>
                            <tr>
                              <td style={{ ...td, textAlign: 'left', fontWeight: 700 }}>
                                メーカー品の売上原価
                                <span style={{ fontWeight: 400, color: C.sub, fontSize: 11, marginLeft: 6 }}>
                                  {m.manu_method === 'inventory' ? '在庫式' : '販売式（在庫が未確定のため）'}
                                </span>
                              </td>
                              <td style={td}></td>
                              <td style={{ ...td, fontWeight: 700 }}>{yen(m.manu_cogs)}</td>
                            </tr>
                            {m.manu_variance != null && (
                              <>
                                <tr>
                                  <td style={{ ...td, textAlign: 'left', borderTop: 'none', color: C.sub }}>参考：売れた数 × 原価</td>
                                  <td style={{ ...td, borderTop: 'none', color: C.sub, fontSize: 11 }}>売上 {yen(m.manu_sales)} 分</td>
                                  <td style={{ ...td, borderTop: 'none', color: C.sub }}>{yen(m.manu_cogs_sold)}</td>
                                </tr>
                                <tr>
                                  <td style={{ ...td, textAlign: 'left', borderTop: 'none' }}>棚卸差異</td>
                                  <td style={{ ...td, borderTop: 'none', color: C.sub, fontSize: 11 }}>破損・紛失・原価ズレ・記録漏れ</td>
                                  <td style={{ ...td, borderTop: 'none', fontWeight: 700, color: Math.abs(m.manu_variance) > 100000 ? C.bad : C.sub }}>
                                    {yen(m.manu_variance)}
                                  </td>
                                </tr>
                              </>
                            )}
                            <tr>
                              <td colSpan={3} style={{ ...td, textAlign: 'left', fontWeight: 700, paddingTop: 14 }}>販売費及び一般管理費</td>
                            </tr>
                            {SGA.map(([k, label, note]) => {
                              const src = m.sga_source?.[k]
                              return (
                                <tr key={k}>
                                  <td style={{ ...td, textAlign: 'left', borderTop: 'none' }}>
                                    {label}
                                    {src === 'estimate' && (
                                      <span style={{ fontSize: 11, color: C.warn, marginLeft: 6 }}>見込み</span>
                                    )}
                                    {src === 'invoice' && (
                                      <span style={{ fontSize: 11, color: C.good, marginLeft: 6 }}>請求書</span>
                                    )}
                                  </td>
                                  <td style={{ ...td, borderTop: 'none', color: C.sub, fontSize: 11 }}>{note}</td>
                                  <td style={{ ...td, borderTop: 'none' }}>{yen(m.sga?.[k])}</td>
                                </tr>
                              )
                            })}
                            <tr>
                              <td style={{ ...td, textAlign: 'left', fontWeight: 700 }}>
                                販管費 計
                                <span style={{ fontWeight: 400, fontSize: 11, marginLeft: 6,
                                  color: m.fee_source === 'invoice' ? C.good : C.warn }}>
                                  {m.fee_source === 'invoice' ? '楽天は請求書の実額'
                                    : m.fee_source === 'mixed' ? '楽天は一部まだ請求書が届いていません'
                                    : '楽天は見込み（内訳書が未取込）'}
                                </span>
                                {!m.has_shipping_invoice && (
                                  <span style={{ fontWeight: 400, fontSize: 11, marginLeft: 6, color: C.bad }}>
                                    ヤマト送料なし
                                  </span>
                                )}
                              </td>
                              <td style={td}></td>
                              <td style={{ ...td, fontWeight: 700 }}>{yen(m.sga_total)}</td>
                            </tr>
                          </tbody>
                        </table>
                        <div style={{ fontSize: 12, color: C.sub, marginTop: 8, lineHeight: 1.8 }}>
                          レート {m.rate}円/元{m.rate_is_default ? '（明細が無い月なので設定値）' : '（その月の明細の実勢）'}
                          ・この月のチャージ {yen(m.charge)}（前払金なので原価には入れていません）
                          {m.inventory_end != null && <>・期末在庫の内訳 {m.inventory_platforms.map(p => p === 'rakuten' ? '楽天' : 'Amazon').join('＋')}</>}
                        </div>
                        {m.cogs == null && (
                          <div style={{ fontSize: 12, color: C.warn, marginTop: 4 }}>
                            期首または期末の在庫金額が確定していないため、売上原価と粗利は出せません（在庫金額タブで確定できます）。
                          </div>
                        )}
                      </td>
                    </tr>
                  )}
                </Fragment>
                )
              })}
            </tbody>
          </table>
          {hiddenCount > 0 && (
            <div style={{ marginTop: 8 }}>
              <button className="btn btn-secondary" style={{ fontSize: 12 }} onClick={() => setShowOld(v => !v)}>
                {showOld ? '古い月をたたむ' : `売上・原価の出ていない古い月も表示（${hiddenCount}か月）`}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
