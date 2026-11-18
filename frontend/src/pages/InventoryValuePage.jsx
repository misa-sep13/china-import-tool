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

export default function InventoryValuePage() {
  const q = useQuery({
    queryKey: ['inventory-snapshots-summary'],
    queryFn: () => api.get('/inventory-snapshots/summary').then(r => r.data),
  })
  const periods = q.data?.periods || []   // 新しい順

  return (
    <div>
      <div className="card" style={{ marginBottom: 16 }}>
        <b style={{ fontSize: 16 }}>📦 在庫金額（月末）</b>
        <div style={{ fontSize: 12, color: C.sub, marginTop: 6, lineHeight: 1.8 }}>
          楽天・Amazonの売上画面で月末に確定した期末在庫金額（実在庫 × 原価）を並べています。
          「前月との差」がプラスなら在庫が増えた月（そのぶん原価は少なく計上）、マイナスなら減った月です。
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
                  const diff = prev ? p.total_amount - prev.total_amount : null
                  const rk = p.platforms?.rakuten?.total_amount
                  const az = p.platforms?.amazon?.total_amount
                  return (
                    <tr key={p.period}>
                      <td style={{ ...td, textAlign: 'left', fontWeight: 600 }}>{p.period}</td>
                      <td style={td}>{rk == null ? <span style={{ color: C.sub }}>未確定</span> : yen(rk)}</td>
                      <td style={td}>{az == null ? <span style={{ color: C.sub }}>未確定</span> : yen(az)}</td>
                      <td style={{ ...td, fontWeight: 700 }}>{yen(p.total_amount)}</td>
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

      <PeriodInventoryPanel platform="rakuten" title="📦 期末在庫金額（楽天）" />
      <PeriodInventoryPanel platform="amazon" title="📦 期末在庫金額（Amazon）" />
    </div>
  )
}
