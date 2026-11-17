import { Fragment, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'

/**
 * デポジットの内訳分解。
 *
 * 試算表はいまチャージした日で仕入が立っている。チャージは前払金の入金で
 * あって、その月に仕入れたものではないので、月ごとの利益の見え方が振れる。
 *
 * この画面は、タオタロウの入出金明細を区分ごとに分けて
 *   原価（商品代・修正・運賃）／固定費（月会費）／前払金（チャージ）
 * の3つに切り分けて見せる。発生ベースへ組み替える最初の一歩。
 *
 * 設計の全体像は docs/月次管理表_発生ベース会計_設計.md と
 * 画面の「📘 月次管理表の設計」にある。
 */

const CAT_COLOR = {
  purchase: '#1d4ed8',
  purchase_adjust: '#0891b2',
  shipping: '#7c3aed',
  fee: '#b45309',
  charge: '#64748b',
  unknown: '#dc2626',
}

const cny = (n) => (n == null ? '-' : Number(n).toLocaleString('ja-JP', {
  minimumFractionDigits: 2, maximumFractionDigits: 2 }))
const jpy = (n) => (n == null ? '-' : Math.round(Number(n)).toLocaleString('ja-JP'))

const num = { textAlign: 'right', fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }

export default function DepositBreakdownPage() {
  const qc = useQueryClient()
  const [openYm, setOpenYm] = useState('')
  const [detail, setDetail] = useState(null)   // { ym, category, action }
  const [syncMsg, setSyncMsg] = useState('')

  const { data: status } = useQuery({
    queryKey: ['acc-taotaro-status'],
    queryFn: () => api.get('/accounting/taotaro/status').then(r => r.data),
  })

  const { data, isLoading } = useQuery({
    queryKey: ['acc-taotaro-monthly'],
    queryFn: () => api.get('/accounting/taotaro/monthly').then(r => r.data),
  })

  const months = data?.months || []
  const labels = data?.category_labels || {}

  // 出てきた区分を、原価→固定費→前払金→未分類の順に並べる
  const cats = useMemo(() => {
    const order = ['purchase', 'purchase_adjust', 'shipping', 'fee', 'charge', 'unknown']
    const seen = new Set()
    months.forEach(m => Object.keys(m.categories || {}).forEach(c => seen.add(c)))
    return order.filter(c => seen.has(c))
  }, [months])

  const syncMutation = useMutation({
    mutationFn: () => api.post('/accounting/taotaro/sync').then(r => r.data),
    onSuccess: (d) => {
      setSyncMsg(`新規 ${d.added}件 / 更新 ${d.updated}件`
        + (d.stopped_early ? '（まだ古い明細が残っています。もう一度押してください）' : ''))
      qc.invalidateQueries({ queryKey: ['acc-taotaro-monthly'] })
      qc.invalidateQueries({ queryKey: ['acc-taotaro-status'] })
    },
    onError: (e) => setSyncMsg(e?.response?.data?.detail || '取り込みに失敗しました'),
  })

  const { data: detailData, isLoading: detailLoading } = useQuery({
    queryKey: ['acc-taotaro-txn', detail],
    queryFn: () => api.get('/accounting/taotaro/transactions', { params: detail })
      .then(r => r.data),
    enabled: !!detail,
  })

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0, fontSize: 18 }}>デポジットの内訳</h2>
        <button className="btn btn-primary" disabled={syncMutation.isPending}
          onClick={() => { setSyncMsg(''); syncMutation.mutate() }}>
          {syncMutation.isPending ? '取り込み中...' : 'タオタロウから取り込む'}
        </button>
        {syncMsg && <span style={{ fontSize: 12, color: '#475569' }}>{syncMsg}</span>}
      </div>

      <div style={{ fontSize: 13, color: '#475569', lineHeight: 1.9, margin: '10px 0 16px' }}>
        チャージ（<b>前払金</b>）は原価ではありません。その月に実際に発生したぶんだけを
        見るために、明細を区分ごとに分けています。
        {status?.count ? (
          <> 取り込み済み <b>{status.count.toLocaleString()}件</b>
            （{String(status.first || '').slice(0, 10)} 〜 {String(status.last || '').slice(0, 10)}）
            {status.unknown > 0 && (
              <b style={{ color: '#dc2626' }}>　未分類 {status.unknown}件</b>
            )}
          </>
        ) : <> まだ取り込んでいません。右上のボタンを押してください。</>}
      </div>

      {isLoading ? (
        <div style={{ padding: 30, color: '#64748b' }}>読み込み中...</div>
      ) : months.length === 0 ? (
        <div className="empty-state">
          <p>明細がありません。「タオタロウから取り込む」を押してください。</p>
        </div>
      ) : (
        <div className="card" style={{ overflowX: 'auto' }}>
          <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 760 }}>
            <thead>
              <tr>
                <th style={{ textAlign: 'left', padding: '8px 10px' }}>月</th>
                {cats.map(c => (
                  <th key={c} style={{ ...num, padding: '8px 10px', color: CAT_COLOR[c] }}>
                    {labels[c] || c}
                  </th>
                ))}
                <th style={{ ...num, padding: '8px 10px' }}>原価計</th>
                <th style={{ padding: '8px 10px' }}></th>
              </tr>
            </thead>
            <tbody>
              {months.map(m => (
                <Fragment key={m.ym}>
                  <tr style={{ borderTop: '1px solid #e2e8f0' }}>
                    <td style={{ padding: '8px 10px', fontWeight: 700 }}>{m.ym}</td>
                    {cats.map(c => {
                      const v = m.categories?.[c]
                      return (
                        <td key={c} style={{ ...num, padding: '8px 10px' }}>
                          {v ? (
                            <button
                              className="btn btn-sm btn-secondary"
                              style={{ fontVariantNumeric: 'tabular-nums', fontSize: 12 }}
                              onClick={() => setDetail({ ym: m.ym, category: c })}
                              title="明細を見る"
                            >{cny(v.cny)}</button>
                          ) : '-'}
                        </td>
                      )
                    })}
                    <td style={{ ...num, padding: '8px 10px', fontWeight: 800 }}>
                      {cny(m.cost_cny)}
                    </td>
                    <td style={{ padding: '8px 10px' }}>
                      <button className="btn btn-sm btn-secondary"
                        onClick={() => setOpenYm(openYm === m.ym ? '' : m.ym)}>
                        {openYm === m.ym ? '閉じる' : '区分ごと'}
                      </button>
                    </td>
                  </tr>
                  {openYm === m.ym && (
                    <tr>
                      <td colSpan={cats.length + 3} style={{ padding: '0 10px 12px' }}>
                        <table style={{ borderCollapse: 'collapse', width: '100%' }}>
                          <thead>
                            <tr>
                              <th style={{ textAlign: 'left', fontSize: 12, padding: '6px 8px' }}>区分（タオタロウ）</th>
                              <th style={{ ...num, fontSize: 12, padding: '6px 8px' }}>件数</th>
                              <th style={{ ...num, fontSize: 12, padding: '6px 8px' }}>元</th>
                              <th style={{ ...num, fontSize: 12, padding: '6px 8px' }}>円</th>
                              <th style={{ textAlign: 'left', fontSize: 12, padding: '6px 8px' }}>扱い</th>
                            </tr>
                          </thead>
                          <tbody>
                            {Object.entries(m.actions || {})
                              .sort((a, b) => b[1].count - a[1].count)
                              .map(([name, v]) => (
                                <tr key={name} style={{ borderTop: '1px solid #f1f5f9' }}>
                                  <td style={{ fontSize: 13, padding: '6px 8px' }}>
                                    <button className="btn btn-sm btn-secondary" style={{ fontSize: 12 }}
                                      onClick={() => setDetail({ ym: m.ym, action: name })}>
                                      {name}
                                    </button>
                                  </td>
                                  <td style={{ ...num, fontSize: 13, padding: '6px 8px' }}>{v.count}</td>
                                  <td style={{ ...num, fontSize: 13, padding: '6px 8px' }}>{cny(v.cny)}</td>
                                  <td style={{ ...num, fontSize: 13, padding: '6px 8px' }}>{jpy(v.jpy)}</td>
                                  <td style={{ fontSize: 12, padding: '6px 8px', color: CAT_COLOR[v.category] }}>
                                    {labels[v.category] || v.category}
                                  </td>
                                </tr>
                              ))}
                          </tbody>
                        </table>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
          <div style={{ fontSize: 12, color: '#64748b', marginTop: 10, lineHeight: 1.9 }}>
            金額は元。引落はマイナスで入っているので、<b>原価計</b>は符号を反転した正の数です。<br />
            <b>前払金の増減（チャージ）</b>は原価に入れていません。ここが試算表とのいちばんの違いです。
          </div>
        </div>
      )}

      {detail && (
        <div className="card" style={{ marginTop: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <b>明細</b>
            <span style={{ fontSize: 13, color: '#475569' }}>
              {detail.ym}
              {detail.category ? ` / ${labels[detail.category] || detail.category}` : ''}
              {detail.action ? ` / ${detail.action}` : ''}
            </span>
            <button className="btn btn-sm btn-secondary" style={{ marginLeft: 'auto' }}
              onClick={() => setDetail(null)}>閉じる</button>
          </div>
          {detailLoading ? (
            <div style={{ padding: 16, color: '#64748b' }}>読み込み中...</div>
          ) : (
            <div style={{ overflowX: 'auto', marginTop: 10 }}>
              <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 700 }}>
                <thead>
                  <tr>
                    <th style={{ textAlign: 'left', fontSize: 12, padding: '6px 8px' }}>日時</th>
                    <th style={{ textAlign: 'left', fontSize: 12, padding: '6px 8px' }}>区分</th>
                    <th style={{ ...num, fontSize: 12, padding: '6px 8px' }}>元</th>
                    <th style={{ ...num, fontSize: 12, padding: '6px 8px' }}>円</th>
                    <th style={{ textAlign: 'left', fontSize: 12, padding: '6px 8px' }}>注文ID</th>
                    <th style={{ textAlign: 'left', fontSize: 12, padding: '6px 8px' }}>配送依頼</th>
                    <th style={{ textAlign: 'left', fontSize: 12, padding: '6px 8px' }}>メモ</th>
                  </tr>
                </thead>
                <tbody>
                  {(detailData?.items || []).map(r => (
                    <tr key={r.id} style={{ borderTop: '1px solid #f1f5f9' }}>
                      <td style={{ fontSize: 12, padding: '6px 8px', whiteSpace: 'nowrap' }}>
                        {String(r.at || '').slice(0, 16).replace('T', ' ')}
                      </td>
                      <td style={{ fontSize: 12, padding: '6px 8px' }}>{r.action}</td>
                      <td style={{ ...num, fontSize: 13, padding: '6px 8px' }}>{cny(r.money)}</td>
                      <td style={{ ...num, fontSize: 13, padding: '6px 8px' }}>{jpy(r.exchange_money)}</td>
                      <td style={{ fontSize: 12, padding: '6px 8px' }}>{r.oid || '-'}</td>
                      <td style={{ fontSize: 12, padding: '6px 8px' }}>{r.sid || '-'}</td>
                      <td style={{ fontSize: 12, padding: '6px 8px', color: '#64748b' }}>{r.remark || ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {(detailData?.items || []).length === 0 && (
                <div style={{ padding: 14, color: '#64748b', fontSize: 13 }}>該当する明細がありません。</div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
