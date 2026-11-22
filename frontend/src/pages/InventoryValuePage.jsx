import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '../api/client'
import PeriodInventoryPanel from '../components/PeriodInventoryPanel'

/**
 * 月次管理表の「📦 在庫金額」。
 *
 * 期末在庫金額はすでに楽天・Amazonそれぞれの画面で月末に確定・保存している
 * （inventory_snapshots）。ここでは同じものを並べて見せるだけ。
 * 上に楽天＋Amazonの合計と前月との差、下に各プラットフォームのパネル
 * （確定ボタン・SKUごとの内訳つき。楽天・Amazonの画面と同じもの）。
 */

const C = { line: '#e5e7eb', sub: '#64748b', good: '#16a34a', bad: '#dc2626' }
const th = { padding: '6px 8px', textAlign: 'right', fontSize: 12, color: C.sub, background: '#f8fafc', whiteSpace: 'nowrap' }
const td = { padding: '6px 8px', borderTop: `1px solid ${C.line}`, fontSize: 13, textAlign: 'right' }
const yen = v => (v == null ? '—' : `¥${Math.round(v).toLocaleString('ja-JP')}`)

// 日本メーカー品の原価マスタは税込（請求書の単価×1.1）。税抜にするときはここだけ割る。
// 中国輸入品の仕入にはもともと日本の消費税がかからない（輸入時の消費税は別に仮払で出している）
const MANU_TAX = 1.1

export function platformAmount(pf, taxMode) {
  if (!pf) return null
  const china = pf.categories?.china?.amount || 0
  const manu = pf.categories?.manufacturer?.amount || 0
  const other = (pf.total_amount || 0) - china - manu
  return china + other + (taxMode === 'ex' ? manu / MANU_TAX : manu)
}

export default function InventoryValuePage() {
  const q = useQuery({
    queryKey: ['inventory-snapshots-summary'],
    queryFn: () => api.get('/inventory-snapshots/summary').then(r => r.data),
  })
  const periods = q.data?.periods || []   // 新しい順
  // 税理士に渡す（決算の）在庫金額は税抜。税込は今までの数字と見比べる用
  const [taxMode, setTaxMode] = useState('ex')
  const totalOf = p => (platformAmount(p.platforms?.rakuten, taxMode) || 0) + (platformAmount(p.platforms?.amazon, taxMode) || 0)

  return (
    <div>
      <div className="card" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <b style={{ fontSize: 16 }}>📦 在庫金額（月末）</b>
          <div style={{ display: 'flex', gap: 4 }}>
            {[['ex', '税抜'], ['in', '税込']].map(([k, label]) => (
              <button key={k} className={`btn ${taxMode === k ? 'btn-primary' : 'btn-secondary'}`}
                style={{ fontSize: 12, padding: '3px 12px' }} onClick={() => setTaxMode(k)}>{label}</button>
            ))}
          </div>
        </div>
        <div style={{ fontSize: 12, color: C.sub, marginTop: 6, lineHeight: 1.8 }}>
          楽天・Amazonの売上画面で月末に確定した期末在庫金額（実在庫 × 原価）を並べています。
          「前月との差」がプラスなら在庫が増えた月（そのぶん原価は少なく計上）、マイナスなら減った月です。
          <br />
          <b>決算（税理士に渡す数字）は税抜</b>です。変わるのは日本メーカー品だけで、原価マスタ（税込）を÷1.1しています。
          中国輸入品の仕入にはもともと日本の消費税がかからないので、税込・税抜で同じです。
        </div>
        {q.isLoading && <div style={{ color: C.sub, marginTop: 8 }}>読み込んでいます…</div>}
        {q.error && <div style={{ color: C.bad, marginTop: 8 }}>{q.error.message}</div>}
        {!!periods.length && (
          <div style={{ overflowX: 'auto', marginTop: 10 }}>
            <table style={{ borderCollapse: 'collapse', minWidth: 560 }}>
              <thead>
                <tr>
                  <th style={{ ...th, textAlign: 'left' }}>月末</th>
                  <th style={th}>楽天</th>
                  <th style={th}>Amazon</th>
                  <th style={th}>合計</th>
                  <th style={th}>前月との差</th>
                </tr>
              </thead>
              <tbody>
                {periods.map((p, i) => {
                  const prev = periods[i + 1]
                  const diff = prev ? totalOf(p) - totalOf(prev) : null
                  const rk = platformAmount(p.platforms?.rakuten, taxMode)
                  const az = platformAmount(p.platforms?.amazon, taxMode)
                  return (
                    <tr key={p.period}>
                      <td style={{ ...td, textAlign: 'left', fontWeight: 600 }}>{p.period}</td>
                      <td style={td}>{rk == null ? <span style={{ color: C.sub }}>未確定</span> : yen(rk)}</td>
                      <td style={td}>{az == null ? <span style={{ color: C.sub }}>未確定</span> : yen(az)}</td>
                      <td style={{ ...td, fontWeight: 700 }}>{yen(totalOf(p))}</td>
                      <td style={{ ...td, color: diff == null ? C.sub : diff >= 0 ? C.good : C.bad }}>
                        {diff == null ? '—' : `${diff >= 0 ? '+' : ''}${yen(diff)}`}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        {!q.isLoading && !periods.length && (
          <div style={{ color: C.sub, marginTop: 8 }}>まだ確定した月がありません。下のパネルで月末在庫を確定してください。</div>
        )}
      </div>

      <PeriodInventoryPanel platform="rakuten" title="📦 期末在庫金額（楽天）" taxMode={taxMode} />
      <PeriodInventoryPanel platform="amazon" title="📦 期末在庫金額（Amazon）" taxMode={taxMode} />
    </div>
  )
}
