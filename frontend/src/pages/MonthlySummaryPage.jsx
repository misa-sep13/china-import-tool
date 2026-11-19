import { Fragment, useEffect, useState } from 'react'
import api from '../api/client'

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

export default function MonthlySummaryPage() {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [open, setOpen] = useState({})

  useEffect(() => {
    api.get('/accounting/summary', { params: { months: 18 } })
      .then(r => setData(r.data))
      .catch(e => setErr(e.response?.data?.detail || e.message))
  }, [])

  return (
    <div>
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
        </div>
        {err && <div style={{ color: C.bad, fontSize: 12, marginTop: 6 }}>{err}</div>}
      </div>

      {!data && !err && <div className="card" style={{ color: C.sub }}>読み込んでいます…</div>}

      {data && (
        <div className="card" style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 980 }}>
            <thead>
              <tr>
                <th style={{ ...th, textAlign: 'left' }}>月</th>
                <th style={th}>売上（楽天）</th>
                <th style={th}>売上（Amazon）</th>
                <th style={th}>売上計</th>
                <th style={th}>中国輸入の原価</th>
                <th style={th}>メーカー品の原価</th>
                <th style={th}>売上原価 計</th>
                <th style={th}>粗利</th>
                <th style={th}>粗利率</th>
                <th style={th}>販管費</th>
                <th style={th}>営業利益</th>
                <th style={th}>営業利益率</th>
                <th style={th}>輸入消費税（仮払）</th>
              </tr>
            </thead>
            <tbody>
              {data.months.map(m => (
                <Fragment key={m.ym}>
                  <tr style={{ cursor: 'pointer' }} onClick={() => setOpen(o => ({ ...o, [m.ym]: !o[m.ym] }))}>
                    <td style={{ ...td, textAlign: 'left', fontWeight: 700 }}>
                      <span style={{ color: C.sub, marginRight: 4 }}>{open[m.ym] ? '▾' : '▸'}</span>{m.ym}
                    </td>
                    <td style={td}>{m.has_rakuten_sales ? yen(m.sales_rakuten) : <span style={{ color: C.warn }}>未取込</span>}</td>
                    <td style={td}>{m.sales_amazon ? yen(m.sales_amazon) : <span style={{ color: C.sub }}>—</span>}</td>
                    <td style={{ ...td, fontWeight: 600 }}>{yen(m.sales)}</td>
                    <td style={td}>{m.china_cogs == null ? <span style={{ color: C.sub }}>在庫未確定</span> : yen(m.china_cogs)}</td>
                    <td style={td}>{yen(m.manu_cogs)}</td>
                    <td style={{ ...td, fontWeight: 600 }}>{yen(m.cogs)}</td>
                    <td style={{ ...td, fontWeight: 700, color: m.gross_profit == null ? C.sub : m.gross_profit >= 0 ? C.good : C.bad }}>
                      {yen(m.gross_profit)}
                    </td>
                    <td style={td}>{m.gross_rate == null ? '—' : `${m.gross_rate}%`}</td>
                    <td style={td}>{yen(m.sga_total)}</td>
                    <td style={{ ...td, fontWeight: 700, color: m.operating_profit == null ? C.sub : m.operating_profit >= 0 ? C.good : C.bad }}>
                      {yen(m.operating_profit)}
                    </td>
                    <td style={td}>{m.operating_rate == null ? '—' : `${m.operating_rate}%`}</td>
                    <td style={{ ...td, color: C.sub }}>{yen(m.import_vat)}</td>
                  </tr>
                  {open[m.ym] && (
                    <tr>
                      <td colSpan={14} style={{ ...td, textAlign: 'left', background: '#f8fafc', padding: '8px 12px 12px 28px' }}>
                        <table style={{ borderCollapse: 'collapse' }}>
                          <tbody>
                            <tr>
                              <td colSpan={3} style={{ ...td, textAlign: 'left', borderTop: 'none', fontWeight: 700 }}>中国輸入品の売上原価</td>
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
                              <td style={{ ...td, textAlign: 'left', fontWeight: 700 }}>当月の仕入 計</td>
                              <td style={td}></td>
                              <td style={{ ...td, fontWeight: 700 }}>{yen(m.purchase_total)}</td>
                            </tr>
                            <tr>
                              <td style={{ ...td, textAlign: 'left' }}>期末在庫（中国輸入品）</td>
                              <td style={{ ...td, color: C.sub, fontSize: 11 }}>当月末</td>
                              <td style={td}>{m.inventory_end == null ? '未確定' : `−${yen(m.inventory_end)}`}</td>
                            </tr>
                            <tr>
                              <td style={{ ...td, textAlign: 'left', fontWeight: 700 }}>中国輸入品の売上原価</td>
                              <td style={td}></td>
                              <td style={{ ...td, fontWeight: 700 }}>{yen(m.china_cogs)}</td>
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
                              <td style={{ ...td, borderTop: 'none', color: C.sub, fontSize: 11 }}>入荷した日</td>
                              <td style={{ ...td, borderTop: 'none' }}>{yen(m.manu_purchase)}</td>
                            </tr>
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
                            {SGA.map(([k, label, note]) => (
                              <tr key={k}>
                                <td style={{ ...td, textAlign: 'left', borderTop: 'none' }}>{label}</td>
                                <td style={{ ...td, borderTop: 'none', color: C.sub, fontSize: 11 }}>{note}</td>
                                <td style={{ ...td, borderTop: 'none' }}>{yen(m.sga?.[k])}</td>
                              </tr>
                            ))}
                            <tr>
                              <td style={{ ...td, textAlign: 'left', fontWeight: 700 }}>
                                販管費 計
                                <span style={{ fontWeight: 400, fontSize: 11, marginLeft: 6,
                                  color: m.fee_source === 'invoice' ? C.good : C.warn }}>
                                  {m.fee_source === 'invoice' ? '楽天は請求書の実額' : '楽天は見込み（内訳書が未取込）'}
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
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
