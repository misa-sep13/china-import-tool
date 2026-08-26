import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '../api/client'

const yen = (v) => `¥${Math.round(v || 0).toLocaleString()}`

const thisMonth = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

const fmtMonth = (m) => {
  const [y, mm] = String(m || '').split('-')
  return mm ? `${Number(mm)}月分` : m
}

/**
 * 就労支援さん向けの再梱包の作業依頼一覧。
 * 上部に月の合計金額を出すのは、そのまま請求書を作れるようにするため。
 */
export default function WelfarePackingOrders({ readOnly = true }) {
  const [month, setMonth] = useState(thisMonth())

  const { data: monthsData } = useQuery({
    queryKey: ['packing-order-months'],
    queryFn: () => api.get('/welfare/packing-orders/months').then(r => r.data),
    refetchInterval: 60000,
  })

  const { data, isLoading } = useQuery({
    queryKey: ['packing-orders', month],
    queryFn: () => api.get('/welfare/packing-orders', { params: { month } }).then(r => r.data),
    refetchInterval: 60000,
  })

  const months = monthsData?.months || []
  const items = data?.items || []

  // 選んだ月がまだ無いときは、実績のある最新の月に寄せる
  const activeMonth = useMemo(() => {
    if (months.some(m => m.month === month)) return month
    return months[0]?.month || month
  }, [month, months])

  const rows = activeMonth === month ? items : []
  const total = data?.total_amount || 0
  const totalSets = data?.total_sets || 0

  return (
    <div>
      {/* 請求書がそのまま作れるよう、月の合計を最初に大きく出す */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        gap: 16, flexWrap: 'wrap',
        padding: '14px 18px', marginBottom: 16, borderRadius: 10,
        background: '#eff6ff', border: '1px solid #bfdbfe',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <select
            value={month}
            onChange={e => setMonth(e.target.value)}
            style={{ width: 'auto', padding: '6px 10px', fontSize: 15 }}
          >
            {(months.length ? months : [{ month }]).map(m => (
              <option key={m.month} value={m.month}>{fmtMonth(m.month)}</option>
            ))}
          </select>
          <div style={{ fontSize: 13, color: '#1e40af' }}>
            {rows.length}件 ／ 合計 {totalSets.toLocaleString()}セット
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: 12, color: '#1e40af' }}>{fmtMonth(activeMonth)} 合計金額</div>
          <div style={{ fontSize: 30, fontWeight: 700, color: '#1e3a8a', lineHeight: 1.2 }}>
            {yen(total)}
          </div>
        </div>
      </div>

      {isLoading ? (
        <div style={{ padding: 40, textAlign: 'center', color: '#9ca3af' }}>読み込み中...</div>
      ) : rows.length === 0 ? (
        <div style={{ padding: 40, textAlign: 'center', color: '#9ca3af' }}>
          {fmtMonth(activeMonth)}の作業依頼はまだありません
        </div>
      ) : (
        <div style={{ overflowX: 'auto', border: '1px solid #e5e7eb', borderRadius: 8 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ background: '#f8fafc', borderBottom: '2px solid #e2e8f0' }}>
                {['優先', '写真', '商品名', '全数量', 'セット数', '作業内容', '単価', '金額', '状態']
                  .map(h => (
                    <th key={h} style={{
                      padding: '10px 12px', whiteSpace: 'nowrap',
                      textAlign: ['商品名', '作業内容', '状態'].includes(h) ? 'left' : 'right',
                    }}>{h}</th>
                  ))}
              </tr>
            </thead>
            <tbody>
              {rows.map(r => {
                const done = r.status === 'done'
                return (
                  <tr key={r.id} style={{
                    borderBottom: '1px solid #f1f5f9',
                    background: done ? '#f8fafc' : undefined,
                    color: done ? '#94a3b8' : undefined,
                  }}>
                    <td style={{ padding: '10px 12px', textAlign: 'right', fontWeight: 600 }}>
                      {r.priority ?? '-'}
                    </td>
                    <td style={{ padding: '6px 12px' }}>
                      {r.image_data_url
                        ? <img src={r.image_data_url} alt="" style={{
                            width: 42, height: 42, objectFit: 'cover',
                            borderRadius: 4, display: 'block',
                          }} />
                        : '-'}
                    </td>
                    <td style={{ padding: '10px 12px' }}>
                      <div style={{ fontWeight: 600 }}>{r.name_jp || r.sku}</div>
                      {r.sku && <div style={{ fontSize: 11, color: '#94a3b8' }}>{r.sku}</div>}
                    </td>
                    <td style={{ padding: '10px 12px', textAlign: 'right' }}>{r.set_qty || '-'}</td>
                    <td style={{ padding: '10px 12px', textAlign: 'right', fontWeight: 600 }}>
                      {(r.set_count || 0).toLocaleString()}
                    </td>
                    <td style={{ padding: '10px 12px', maxWidth: 380 }}>
                      {r.packing_material && (
                        <div style={{ fontSize: 12, color: '#0f766e' }}>{r.packing_material}</div>
                      )}
                      <div style={{ whiteSpace: 'pre-wrap' }}>{r.packing_method}</div>
                      {r.note && (
                        <div style={{ fontSize: 12, color: '#b45309', marginTop: 2 }}>{r.note}</div>
                      )}
                    </td>
                    <td style={{ padding: '10px 12px', textAlign: 'right' }}>{yen(r.unit_price)}</td>
                    <td style={{ padding: '10px 12px', textAlign: 'right', fontWeight: 600 }}>
                      {yen(r.amount)}
                    </td>
                    <td style={{ padding: '10px 12px' }}>
                      {done
                        ? <span style={{ color: '#16a34a', fontWeight: 600 }}>完了</span>
                        : <span style={{ color: '#f59e0b' }}>依頼中</span>}
                    </td>
                  </tr>
                )
              })}
            </tbody>
            <tfoot>
              <tr style={{ background: '#f8fafc', borderTop: '2px solid #e2e8f0', fontWeight: 700 }}>
                <td colSpan={4} style={{ padding: '12px', textAlign: 'right' }}>合計</td>
                <td style={{ padding: '12px', textAlign: 'right' }}>{totalSets.toLocaleString()}</td>
                <td />
                <td />
                <td style={{ padding: '12px', textAlign: 'right', fontSize: 15 }}>{yen(total)}</td>
                <td />
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </div>
  )
}
