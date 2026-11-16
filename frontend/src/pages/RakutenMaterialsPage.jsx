import { useEffect, useMemo, useState } from 'react'
import api from '../api/client'

/**
 * 資材・プレゼント発注。
 *
 * 宅配袋やOPP袋、レビューキャンペーンのプレゼントは売り物ではないので、
 * 発注推奨にも在庫一覧にも出てこない。「そろそろ袋が切れる」に気づける
 * 場所がこれまで無く、気づいたときには残り1袋ということが起きていた。
 *
 * 袋はサイズ違いが多く、名前だけでは見分けられないので画像を出す。
 * 画像は仕入先（1688・淘宝）のものをタオタロウ経由で取ってきて持つ。
 *
 * 発注の記録は商品の発注履歴とは別の表（material_orders）に入れる。
 * 混ぜると売り物の発注一覧に紛れて見づらくなるため。
 */

const C = {
  line: '#e5e7eb', sub: '#64748b', text: '#0f172a',
  key: '#2563eb', soft: '#f8fafc', warn: '#b45309', bad: '#dc2626', good: '#16a34a',
}
const card = {
  background: '#fff', border: `1px solid ${C.line}`, borderRadius: 10,
  padding: 16, marginBottom: 16,
}
const th = {
  padding: '8px 10px', textAlign: 'left', whiteSpace: 'nowrap',
  fontSize: 12, color: C.sub, borderBottom: `2px solid ${C.line}`,
}
const td = { padding: '8px 10px', borderBottom: `1px solid #f1f5f9`, fontSize: 13 }

const today = () => {
  const d = new Date()
  const p = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

// 在庫が少ないものを上に出すための目安。袋は100枚入りで数えるので
// 「残り2袋」はもう危ない。プレゼントは1個単位なので桁が違う
const lowLimit = (kind) => (kind === 'material' ? 3 : 20)

// 仕入先の画像は直リンクでは弾かれるので、サーバー経由で読む
const IMG = (sku) =>
  `${api.defaults.baseURL}/materials/items/${encodeURIComponent(sku)}/image`

function Thumb({ src, alt, size = 56 }) {
  const [err, setErr] = useState(false)
  const box = {
    width: size, height: size, borderRadius: 6, objectFit: 'cover',
    border: `1px solid ${C.line}`, background: C.soft, flexShrink: 0,
  }
  if (!src || err) {
    return (
      <div style={{ ...box, display: 'flex', alignItems: 'center',
        justifyContent: 'center', fontSize: 10, color: '#94a3b8' }}>
        画像なし
      </div>
    )
  }
  return <img src={src} alt={alt || ''} style={box} onError={() => setErr(true)} />
}

export default function RakutenMaterialsPage() {
  const [tab, setTab] = useState('material')   // material / promo / orders
  const [items, setItems] = useState([])
  const [orders, setOrders] = useState([])
  const [loading, setLoading] = useState(true)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [qty, setQty] = useState({})           // sku -> 入力中の発注数
  const [orderDate, setOrderDate] = useState(today())

  const load = async () => {
    setLoading(true)
    try {
      const [a, b] = await Promise.all([
        api.get('/materials/items'),
        api.get('/materials/orders'),
      ])
      setItems(a.data.items || [])
      setOrders(b.data.items || [])
    } catch (e) {
      setMsg(e.response?.data?.detail || '読み込めませんでした')
    }
    setLoading(false)
  }
  useEffect(() => { load() }, [])

  const shown = useMemo(() => {
    const list = items.filter(i => i.kind === tab)
    // 在庫が少ない順。切れそうなものを先に見せる
    return [...list].sort((a, b) => (a.stock || 0) - (b.stock || 0))
  }, [items, tab])

  const submit = async (sku) => {
    const n = Number(qty[sku] || 0)
    if (!n || n <= 0) { setMsg('発注数を入れてください'); return }
    setBusy(true); setMsg('')
    try {
      await api.post('/materials/orders', { sku, qty: n, ordered_at: orderDate })
      setQty(q => ({ ...q, [sku]: '' }))
      await load()
      setMsg(`${sku} を ${n} 発注として記録しました`)
    } catch (e) {
      setMsg(e.response?.data?.detail || '記録できませんでした')
    }
    setBusy(false)
  }

  const markReceived = async (o) => {
    setBusy(true); setMsg('')
    try {
      const { data } = await api.patch(`/materials/orders/${o.id}`,
        { received_at: o.received_at ? '' : today() })
      await load()
      setMsg(o.received_at
        ? `${o.sku} を未入荷に戻しました（在庫 ${data.stock}）`
        : `${o.sku} を入荷にしました（在庫 ${data.stock}）`)
    } catch (e) {
      setMsg(e.response?.data?.detail || '変えられませんでした')
    }
    setBusy(false)
  }

  const removeOrder = async (o) => {
    if (!confirm(`${o.ordered_at} の ${o.name}（${o.qty}）を消しますか？`
      + (o.received_at ? '\n入荷済みなので在庫も戻します。' : ''))) return
    setBusy(true)
    try {
      await api.delete(`/materials/orders/${o.id}`)
      await load()
    } catch (e) {
      setMsg(e.response?.data?.detail || '消せませんでした')
    }
    setBusy(false)
  }

  const fetchImages = async () => {
    setBusy(true); setMsg('仕入先から画像を取っています…')
    try {
      const { data } = await api.post('/materials/fetch-images?only_missing=true')
      await load()
      setMsg(`画像を ${data.done}/${data.total} 件入れました`
        + (data.failed?.length ? `（取れなかったもの: ${data.failed.join(' / ')}）` : ''))
    } catch (e) {
      setMsg(e.response?.data?.detail || '画像を取れませんでした')
    }
    setBusy(false)
  }

  const noPhoto = items.filter(i => !i.photo_url).length

  return (
    <div style={{ padding: 20, maxWidth: 1200 }}>
      <h2 style={{ margin: '0 0 4px' }}>📦 資材・プレゼント発注</h2>
      <div style={{ fontSize: 12, color: C.sub, marginBottom: 14 }}>
        宅配袋・OPP袋などの梱包資材と、レビューキャンペーンのプレゼント。
        売り物ではないので発注推奨には出てきません。ここで数えます
      </div>

      <div style={{ display: 'flex', gap: 8, marginBottom: 14, alignItems: 'center', flexWrap: 'wrap' }}>
        {[['material', `資材（${items.filter(i => i.kind === 'material').length}）`],
          ['promo', `プレゼント（${items.filter(i => i.kind === 'promo').length}）`],
          ['orders', `発注の記録（${orders.length}）`]].map(([k, label]) => (
          <button key={k} onClick={() => setTab(k)}
            className={`btn ${tab === k ? 'btn-primary' : 'btn-secondary'}`}>
            {label}
          </button>
        ))}
        <button className="btn btn-secondary" style={{ marginLeft: 'auto' }}
          onClick={fetchImages} disabled={busy}>
          🖼 画像を取ってくる{noPhoto ? `（${noPhoto}件未取得）` : ''}
        </button>
      </div>

      {msg && (
        <div style={{ ...card, padding: 10, fontSize: 13, color: C.text, background: C.soft }}>
          {msg}
        </div>
      )}

      {loading ? (
        <div style={{ padding: 30, color: C.sub }}>読み込み中…</div>
      ) : tab === 'orders' ? (
        <div style={card}>
          {orders.length === 0 ? (
            <div style={{ padding: 20, color: C.sub }}>まだ発注の記録がありません</div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr>
                    {['', '発注日', '品名', '数', '入荷', '', ''].map((h, i) =>
                      <th key={i} style={th}>{h}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {orders.map(o => (
                    <tr key={o.id}>
                      <td style={td}><Thumb src={o.photo_url ? IMG(o.sku) : ''} alt={o.name} size={40} /></td>
                      <td style={{ ...td, whiteSpace: 'nowrap' }}>{o.ordered_at || '—'}</td>
                      <td style={td}>
                        {o.name}
                        <div style={{ fontSize: 11, color: C.sub }}>
                          {o.sku}・{o.kind === 'promo' ? 'プレゼント' : '資材'}
                        </div>
                      </td>
                      <td style={{ ...td, textAlign: 'right', fontWeight: 700 }}>{o.qty}</td>
                      <td style={{ ...td, whiteSpace: 'nowrap',
                        color: o.received_at ? C.good : C.warn }}>
                        {o.received_at || '未入荷'}
                      </td>
                      <td style={td}>
                        <button className="btn btn-secondary" disabled={busy}
                          style={{ padding: '2px 10px', fontSize: 12 }}
                          onClick={() => markReceived(o)}>
                          {o.received_at ? '未入荷に戻す' : '入荷にする'}
                        </button>
                      </td>
                      <td style={td}>
                        <button className="btn btn-secondary" disabled={busy}
                          style={{ padding: '2px 8px', fontSize: 12, color: C.bad }}
                          onClick={() => removeOrder(o)}>削除</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ) : (
        <div style={card}>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center',
            marginBottom: 12, fontSize: 13 }}>
            <span>発注日</span>
            <input type="date" value={orderDate}
              onChange={e => setOrderDate(e.target.value)} />
            <span style={{ color: C.sub, fontSize: 12 }}>
              在庫の少ない順に並んでいます。入荷したら「発注の記録」で入荷にすると在庫に足されます
            </span>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  {['', '品名 / 仕入れ仕様', '在庫', '発注済', '前回', '発注数', ''].map((h, i) =>
                    <th key={i} style={th}>{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {shown.map(it => {
                  const low = (it.stock || 0) <= lowLimit(it.kind)
                  return (
                    <tr key={it.sku} style={low ? { background: '#fff7ed' } : undefined}>
                      <td style={td}><Thumb src={it.photo_url ? IMG(it.sku) : ''} alt={it.name} /></td>
                      <td style={{ ...td, minWidth: 260 }}>
                        <div style={{ fontWeight: 600 }}>{it.name || it.sku}</div>
                        <div style={{ fontSize: 11, color: C.sub }}>
                          {it.sku}
                          {it.supplier_spec ? `・${it.supplier_spec}` : ''}
                          {it.price_cny ? `・${it.price_cny}元` : ''}
                        </div>
                        {it.buy_url && (
                          <a href={it.buy_url} target="_blank" rel="noreferrer"
                            style={{ fontSize: 11, color: C.key }}>仕入先を開く →</a>
                        )}
                      </td>
                      <td style={{ ...td, textAlign: 'right', fontWeight: 700,
                        color: low ? C.bad : C.text }}>
                        {it.stock}
                        {low && <div style={{ fontSize: 10, color: C.bad }}>少ない</div>}
                      </td>
                      <td style={{ ...td, textAlign: 'right',
                        color: it.pending_qty ? C.warn : '#cbd5e1' }}>
                        {it.pending_qty || '—'}
                      </td>
                      <td style={{ ...td, whiteSpace: 'nowrap', color: C.sub, fontSize: 12 }}>
                        {it.last_ordered_at
                          ? <>{it.last_ordered_at}<div>{it.last_qty} 個</div></>
                          : '—'}
                      </td>
                      <td style={td}>
                        <input type="number" min="0" style={{ width: 80 }}
                          value={qty[it.sku] ?? ''}
                          onChange={e => setQty(q => ({ ...q, [it.sku]: e.target.value }))}
                          onKeyDown={e => { if (e.key === 'Enter') submit(it.sku) }} />
                      </td>
                      <td style={td}>
                        <button className="btn btn-primary" disabled={busy}
                          style={{ padding: '3px 12px', fontSize: 12 }}
                          onClick={() => submit(it.sku)}>発注</button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
