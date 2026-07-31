import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'

const fmtYen = (v) => `¥${Math.round(Number(v) || 0).toLocaleString()}`
const fmtNum = (v) => Number(v || 0).toLocaleString()

function prevMonth() {
  const d = new Date()
  d.setDate(1)
  d.setMonth(d.getMonth() - 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

/**
 * 期末（月末）在庫金額パネル。
 * 在庫数はマスタに現在値しか無いため、月末に「確定」して保存した値を月別に表示する。
 * platform: 'rakuten' | 'amazon'
 */
export default function PeriodInventoryPanel({ platform = 'rakuten', title = '📦 期末在庫金額' }) {
  const qc = useQueryClient()
  const [period, setPeriod] = useState(prevMonth())
  const [openPeriod, setOpenPeriod] = useState(null)
  const [result, setResult] = useState(null)

  const summaryQ = useQuery({
    queryKey: ['inventory-snapshots-summary'],
    queryFn: () => api.get('/inventory-snapshots/summary').then(r => r.data),
  })

  const detailQ = useQuery({
    queryKey: ['inventory-snapshot-detail', openPeriod, platform],
    queryFn: () => api.get('/inventory-snapshots/detail', { params: { period: openPeriod, platform } }).then(r => r.data),
    enabled: !!openPeriod,
  })

  const captureMut = useMutation({
    mutationFn: () => api.post('/inventory-snapshots/capture', { period, platform }).then(r => r.data),
    onSuccess: (data) => {
      setResult(data)
      qc.invalidateQueries(['inventory-snapshots-summary'])
      qc.invalidateQueries(['inventory-snapshot-detail'])
    },
    onError: (e) => setResult({ error: e.response?.data?.detail || '確定でエラーが発生しました' }),
  })

  // この画面のプラットフォームのデータがある月だけ表示する
  const rows = useMemo(() => {
    const periods = summaryQ.data?.periods || []
    return periods
      .filter(p => p.platforms?.[platform])
      .map(p => ({ period: p.period, ...p.platforms[platform] }))
  }, [summaryQ.data, platform])

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 10 }}>
        <h3 style={{ margin: 0 }}>{title}</h3>
        <span style={{ fontSize: 12, color: '#64748b' }}>実在庫 × 原価。セット販売ページは二重計上を避けて除外</span>
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
          <input type="month" value={period} onChange={e => setPeriod(e.target.value)} style={{ width: 150 }} />
          <button
            className="btn btn-primary"
            style={{ fontSize: 13, whiteSpace: 'nowrap' }}
            disabled={captureMut.isPending}
            onClick={() => {
              if (!window.confirm(
                `${period} の期末在庫を「今の在庫数」で確定します。\n`
                + `同じ月の確定分は上書きされます。よろしいですか？`
              )) return
              setResult(null)
              captureMut.mutate()
            }}
          >
            {captureMut.isPending ? '確定中...' : 'この月で確定'}
          </button>
        </div>
      </div>

      {result && (
        <div style={{
          fontSize: 12, marginBottom: 10, padding: '6px 10px', borderRadius: 6,
          background: result.error ? '#fef2f2' : '#f0fdf4',
          color: result.error ? '#dc2626' : '#166534',
        }}>
          {result.error
            ? result.error
            : `${result.period} を確定しました：${result.items}件 / ${fmtYen(result.total_amount)}`
              + (result.no_cost_skus?.length ? `（原価未設定 ${result.no_cost_skus.length}件は0円で計上）` : '')}
        </div>
      )}

      {rows.length === 0 ? (
        <div style={{ fontSize: 13, color: '#64748b' }}>
          まだ確定した月がありません。対象月を選んで「この月で確定」を押すと、その時点の在庫で保存されます。
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', fontSize: 13 }}>
            <thead>
              <tr>
                <th style={{ textAlign: 'left' }}>対象月</th>
                <th style={{ textAlign: 'right' }}>中国輸入</th>
                <th style={{ textAlign: 'right' }}>日本メーカー品</th>
                <th style={{ textAlign: 'right' }}>合計</th>
                <th style={{ textAlign: 'right' }}>在庫数</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map(r => {
                const china = r.categories?.china
                const manu = r.categories?.manufacturer
                const stock = (china?.stock || 0) + (manu?.stock || 0)
                return (
                  <tr key={r.period} style={{ borderTop: '1px solid #e2e8f0' }}>
                    <td style={{ fontWeight: 700 }}>{r.period}</td>
                    <td style={{ textAlign: 'right' }}>{china ? fmtYen(china.amount) : '—'}</td>
                    <td style={{ textAlign: 'right' }}>{manu ? fmtYen(manu.amount) : '—'}</td>
                    <td style={{ textAlign: 'right', fontWeight: 700 }}>{fmtYen(r.total_amount)}</td>
                    <td style={{ textAlign: 'right', color: '#64748b' }}>{fmtNum(stock)}</td>
                    <td style={{ textAlign: 'right' }}>
                      <button
                        className="btn btn-secondary"
                        style={{ fontSize: 11, padding: '3px 10px' }}
                        onClick={() => setOpenPeriod(openPeriod === r.period ? null : r.period)}
                      >
                        {openPeriod === r.period ? '閉じる' : '明細'}
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {openPeriod && (
        <div style={{ marginTop: 12, borderTop: '1px solid #e2e8f0', paddingTop: 10 }}>
          <div style={{ fontWeight: 700, marginBottom: 6 }}>{openPeriod} の明細</div>
          {detailQ.isLoading ? <div style={{ fontSize: 13, color: '#64748b' }}>読み込み中...</div> : (
            <div style={{ maxHeight: 360, overflowY: 'auto' }}>
              <table style={{ width: '100%', fontSize: 12 }}>
                <thead>
                  <tr>
                    <th style={{ textAlign: 'left' }}>SKU</th>
                    <th style={{ textAlign: 'left' }}>商品名</th>
                    <th style={{ textAlign: 'left' }}>区分</th>
                    <th style={{ textAlign: 'right' }}>在庫</th>
                    <th style={{ textAlign: 'right' }}>原価</th>
                    <th style={{ textAlign: 'right' }}>金額</th>
                  </tr>
                </thead>
                <tbody>
                  {(detailQ.data?.items || []).map((it, i) => (
                    <tr key={i} style={{ borderTop: '1px solid #f1f5f9', background: it.cost_jpy ? undefined : '#fffbeb' }}>
                      <td style={{ fontFamily: 'monospace' }}>{it.sku}</td>
                      <td>{it.name}</td>
                      <td>{it.category_label}</td>
                      <td style={{ textAlign: 'right' }}>{fmtNum(it.stock)}</td>
                      <td style={{ textAlign: 'right' }}>{it.cost_jpy ? fmtYen(it.cost_jpy) : <span style={{ color: '#d97706' }}>未設定</span>}</td>
                      <td style={{ textAlign: 'right', fontWeight: 600 }}>{fmtYen(it.amount)}</td>
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
