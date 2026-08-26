import { useMemo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'

const yen = (v) => `¥${Math.round(v || 0).toLocaleString()}`
const today = () => new Date().toISOString().slice(0, 10)
const thisMonth = () => today().slice(0, 7)
const fmtMonth = (m) => {
  const mm = String(m || '').split('-')[1]
  return mm ? `${Number(mm)}月分` : m
}

/**
 * 再梱包の作業依頼を作る・直す管理画面。
 *
 * 梱包材・梱包方法・単価は商品マスタに持たせてあるので、商品を選べば自動で入る。
 * 今回だけ違う場合はここで上書きできる（マスタは変えない）。
 */
export default function WelfarePackingAdmin() {
  const qc = useQueryClient()
  const [month, setMonth] = useState(thisMonth())
  const [form, setForm] = useState({
    order_date: today(), priority: '', sku: '', set_count: '', note: '',
  })
  const [skuQuery, setSkuQuery] = useState('')

  const { data } = useQuery({
    queryKey: ['packing-orders', month],
    queryFn: () => api.get('/welfare/packing-orders', { params: { month } }).then(r => r.data),
  })
  const { data: monthsData } = useQuery({
    queryKey: ['packing-order-months'],
    queryFn: () => api.get('/welfare/packing-orders/months').then(r => r.data),
  })
  const { data: products = [] } = useQuery({
    queryKey: ['rakuten-products-for-packing'],
    queryFn: () => api.get('/rakuten/products').then(r => r.data),
    staleTime: 5 * 60 * 1000,
  })

  const rows = data?.items || []
  const months = monthsData?.months || []

  const candidates = useMemo(() => {
    const q = skuQuery.trim().toLowerCase()
    if (!q) return []
    return products
      .filter(p => (p.sku || '').toLowerCase().includes(q)
        || (p.name || '').toLowerCase().includes(q))
      .slice(0, 12)
  }, [products, skuQuery])

  const selected = useMemo(
    () => products.find(p => p.sku === form.sku) || null,
    [products, form.sku]
  )

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['packing-orders'] })
    qc.invalidateQueries({ queryKey: ['packing-order-months'] })
  }

  const create = useMutation({
    mutationFn: (body) => api.post('/welfare/packing-orders', body).then(r => r.data),
    onSuccess: () => {
      setForm(f => ({ order_date: f.order_date, priority: '', sku: '', set_count: '', note: '' }))
      setSkuQuery('')
      refresh()
    },
    onError: (e) => alert('登録エラー: ' + (e.response?.data?.detail || e.message)),
  })

  const update = useMutation({
    mutationFn: ({ id, body }) => api.patch(`/welfare/packing-orders/${id}`, body).then(r => r.data),
    onSuccess: refresh,
    onError: (e) => alert('更新エラー: ' + (e.response?.data?.detail || e.message)),
  })

  const remove = useMutation({
    mutationFn: (id) => api.delete(`/welfare/packing-orders/${id}`),
    onSuccess: refresh,
  })

  const submit = () => {
    if (!form.sku) return alert('商品を選んでください')
    if (!form.set_count) return alert('セット数を入れてください')
    create.mutate({
      order_date: form.order_date,
      priority: form.priority === '' ? null : Number(form.priority),
      sku: form.sku,
      set_count: Number(form.set_count),
      note: form.note || '',
    })
  }

  return (
    <div className="card">
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14, flexWrap: 'wrap' }}>
        <h3 style={{ margin: 0 }}>再梱包の作業依頼</h3>
        <select value={month} onChange={e => setMonth(e.target.value)} style={{ width: 'auto' }}>
          {(months.some(m => m.month === month) ? months : [{ month }, ...months]).map(m => (
            <option key={m.month} value={m.month}>{fmtMonth(m.month)}</option>
          ))}
        </select>
        <div style={{ marginLeft: 'auto', textAlign: 'right' }}>
          <div style={{ fontSize: 12, color: '#64748b' }}>{fmtMonth(month)} 合計</div>
          <div style={{ fontSize: 22, fontWeight: 700 }}>{yen(data?.total_amount)}</div>
        </div>
      </div>

      {/* 依頼の追加 */}
      <div style={{
        padding: 14, marginBottom: 16, borderRadius: 8,
        background: '#f8fafc', border: '1px solid #e2e8f0',
      }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 10 }}>
          <div className="form-group" style={{ margin: 0 }}>
            <label>依頼日</label>
            <input type="date" value={form.order_date}
              onChange={e => setForm(f => ({ ...f, order_date: e.target.value }))} />
          </div>
          <div className="form-group" style={{ margin: 0 }}>
            <label>優先順位</label>
            <input type="number" value={form.priority} placeholder="1"
              onChange={e => setForm(f => ({ ...f, priority: e.target.value }))} />
          </div>
          <div className="form-group" style={{ margin: 0, position: 'relative' }}>
            <label>商品（SKU・名前で検索）</label>
            <input
              value={form.sku || skuQuery}
              placeholder="ガーゼ / y104 など"
              onChange={e => { setSkuQuery(e.target.value); setForm(f => ({ ...f, sku: '' })) }}
            />
            {candidates.length > 0 && !form.sku && (
              <div style={{
                position: 'absolute', zIndex: 20, top: '100%', left: 0, right: 0,
                background: '#fff', border: '1px solid #cbd5e1', borderRadius: 6,
                maxHeight: 240, overflowY: 'auto', boxShadow: '0 4px 12px rgba(0,0,0,.08)',
              }}>
                {candidates.map(p => (
                  <div key={p.id}
                    onClick={() => { setForm(f => ({ ...f, sku: p.sku })); setSkuQuery('') }}
                    style={{ padding: '8px 10px', cursor: 'pointer', fontSize: 13, borderBottom: '1px solid #f1f5f9' }}
                  >
                    <div style={{ fontWeight: 600 }}>{p.name || p.sku}</div>
                    <div style={{ fontSize: 11, color: '#94a3b8' }}>
                      {p.sku}
                      {p.packing_unit_price ? ` ・ 単価${yen(p.packing_unit_price)}` : ' ・ 単価未設定'}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="form-group" style={{ margin: 0 }}>
            <label>セット数</label>
            <input type="number" value={form.set_count} placeholder="200"
              onChange={e => setForm(f => ({ ...f, set_count: e.target.value }))} />
          </div>
          <div className="form-group" style={{ margin: 0 }}>
            <label>備考（任意）</label>
            <input value={form.note}
              onChange={e => setForm(f => ({ ...f, note: e.target.value }))} />
          </div>
        </div>

        {selected && (
          <div style={{ marginTop: 10, fontSize: 12, color: '#475569' }}>
            {selected.packing_unit_price
              ? <>単価 <b>{yen(selected.packing_unit_price)}</b> ／ 1セット {selected.packing_set_qty || '-'}個
                  {form.set_count
                    ? <> → 金額 <b>{yen(selected.packing_unit_price * Number(form.set_count))}</b></>
                    : null}
                </>
              : <span style={{ color: '#b45309' }}>
                  ⚠ この商品は梱包の単価が未設定です。商品マスタで設定すると次回から自動で入ります
                </span>}
            {selected.packing_method && (
              <div style={{ marginTop: 4 }}>作業内容: {selected.packing_method}</div>
            )}
          </div>
        )}

        <div style={{ marginTop: 12 }}>
          <button className="btn btn-primary" onClick={submit} disabled={create.isPending}>
            {create.isPending ? '追加中...' : '依頼に追加'}
          </button>
        </div>
      </div>

      {/* 依頼一覧 */}
      {rows.length === 0 ? (
        <div style={{ padding: 30, textAlign: 'center', color: '#9ca3af' }}>
          {fmtMonth(month)}の依頼はまだありません
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ background: '#f8fafc', borderBottom: '2px solid #e2e8f0' }}>
                {['優先', '依頼日', '商品名', '全数量', 'セット数', '単価', '金額', '状態', ''].map(h => (
                  <th key={h} style={{ padding: '8px 10px', whiteSpace: 'nowrap' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map(r => (
                <tr key={r.id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                  <td style={{ padding: '8px 10px', textAlign: 'center' }}>
                    <input type="number" defaultValue={r.priority ?? ''} style={{ width: 56 }}
                      onBlur={e => {
                        const v = e.target.value === '' ? null : Number(e.target.value)
                        if (v !== r.priority) update.mutate({ id: r.id, body: { priority: v } })
                      }} />
                  </td>
                  <td style={{ padding: '8px 10px', whiteSpace: 'nowrap' }}>{r.order_date}</td>
                  <td style={{ padding: '8px 10px' }}>
                    <div style={{ fontWeight: 600 }}>{r.name_jp || r.sku}</div>
                    <div style={{ fontSize: 11, color: '#94a3b8' }}>{r.sku}</div>
                  </td>
                  <td style={{ padding: '8px 10px', textAlign: 'right' }}>{r.set_qty || '-'}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right' }}>
                    <input type="number" defaultValue={r.set_count} style={{ width: 80 }}
                      onBlur={e => {
                        const v = Number(e.target.value || 0)
                        if (v !== r.set_count) update.mutate({ id: r.id, body: { set_count: v } })
                      }} />
                  </td>
                  <td style={{ padding: '8px 10px', textAlign: 'right' }}>
                    <input type="number" step="0.1" defaultValue={r.unit_price} style={{ width: 70 }}
                      onBlur={e => {
                        const v = Number(e.target.value || 0)
                        if (v !== r.unit_price) update.mutate({ id: r.id, body: { unit_price: v } })
                      }} />
                  </td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', fontWeight: 600 }}>{yen(r.amount)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'center' }}>
                    <button
                      className="btn btn-secondary"
                      style={{ padding: '2px 10px', fontSize: 12 }}
                      onClick={() => update.mutate({
                        id: r.id, body: { status: r.status === 'done' ? 'open' : 'done' },
                      })}
                    >
                      {r.status === 'done' ? '完了' : '依頼中'}
                    </button>
                  </td>
                  <td style={{ padding: '8px 10px', textAlign: 'center' }}>
                    <button
                      className="btn btn-secondary"
                      style={{ padding: '2px 8px', fontSize: 12, color: '#dc2626' }}
                      onClick={() => { if (confirm('この依頼を削除しますか？')) remove.mutate(r.id) }}
                    >削除</button>
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr style={{ background: '#f8fafc', borderTop: '2px solid #e2e8f0', fontWeight: 700 }}>
                <td colSpan={4} style={{ padding: 10, textAlign: 'right' }}>合計</td>
                <td style={{ padding: 10, textAlign: 'right' }}>{(data?.total_sets || 0).toLocaleString()}</td>
                <td />
                <td style={{ padding: 10, textAlign: 'right' }}>{yen(data?.total_amount)}</td>
                <td colSpan={2} />
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </div>
  )
}
