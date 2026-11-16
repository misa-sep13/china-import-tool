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
 * 画像は仕入先（1688・淘宝）のもの。直リンクでは弾かれるのでサーバー経由。
 *
 * 在庫は持たない。棚を見ないと実数が分からず、ここで足し引きしても
 * 実物と合わないため。代わりに「前回いつ何個頼んだか」を手がかりにする。
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
const td = { padding: '8px 10px', borderBottom: '1px solid #f1f5f9', fontSize: 13 }

const today = () => {
  const d = new Date()
  const p = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

// 仕入先の画像は直リンクでは弾かれるので、サーバー経由で読む
const IMG = (sku) =>
  `${api.defaults.baseURL}/materials/items/${encodeURIComponent(sku)}/image`

// 資材の並び。宅配袋 → プチプチ → OPP の順に見たい（棚の並びと同じ）。
// SKUでは分けられない：宅小中とA4宅大は中身が宅配袋なのにSKUが opp
const group = (it) => {
  const n = it.name || ''
  if (n.startsWith('OPP')) return 2
  if (n.includes('プチプチ')) return 1
  return 0
}
// 大きさ。仕入れ仕様か名前にある「17*30」「5×8」から拾う。
// 宅小（仕入れ仕様が「打包袋」だけ）は拾えないので0＝いちばん小さい扱い
const size = (it) => {
  const m = `${it.supplier_spec || ''} ${it.name || ''}`.match(/(\d+)\s*[*×x]\s*(\d+)/)
  return m ? Number(m[1]) * 1000 + Number(m[2]) : 0
}

function Thumb({ sku, has, alt, size: boxSize = 56 }) {
  const [err, setErr] = useState(false)
  const box = {
    width: boxSize, height: boxSize, borderRadius: 6, objectFit: 'cover',
    border: `1px solid ${C.line}`, background: C.soft, flexShrink: 0,
  }
  if (!has || err) {
    return (
      <div style={{ ...box, display: 'flex', alignItems: 'center',
        justifyContent: 'center', fontSize: 10, color: '#94a3b8' }}>
        画像なし
      </div>
    )
  }
  return <img src={IMG(sku)} alt={alt || ''} style={box} onError={() => setErr(true)} />
}

export default function RakutenMaterialsPage() {
  const [tab, setTab] = useState('material')   // material / promo / orders
  const [items, setItems] = useState([])
  const [orders, setOrders] = useState([])
  const [loading, setLoading] = useState(true)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [qty, setQty] = useState({})           // sku -> 発注数
  const [picked, setPicked] = useState({})     // sku -> レ点
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
    if (tab !== 'material') {
      // プレゼントは色違いが隣に並ぶよう名前順
      return [...list].sort((a, b) => (a.name || '').localeCompare(b.name || '', 'ja'))
    }
    // 資材は棚の並びと同じ 宅配袋 → プチプチ → OPP。中はサイズの小さい順
    return [...list].sort((a, b) =>
      (group(a) - group(b)) || (size(a) - size(b))
      || (a.name || '').localeCompare(b.name || '', 'ja'))
  }, [items, tab])

  // レ点が付いていて数量が入っているものだけが発注の対象
  const ready = useMemo(
    () => shown.filter(i => picked[i.sku] && Number(qty[i.sku] || 0) > 0),
    [shown, picked, qty])

  const toggleAll = () => {
    const all = shown.length > 0 && shown.every(i => picked[i.sku])
    const next = { ...picked }
    shown.forEach(i => { next[i.sku] = !all })
    setPicked(next)
  }

  const submitPicked = async () => {
    if (!ready.length) { setMsg('レ点を付けて、発注数を入れてください'); return }
    const lines = ready.map(i => `${i.name}　${qty[i.sku]}`).join('\n')
    if (!confirm(`${ready.length}件を ${orderDate} の発注として記録します。\n\n${lines}`)) return
    setBusy(true); setMsg('')
    try {
      const { data } = await api.post('/materials/orders/bulk', {
        ordered_at: orderDate,
        items: ready.map(i => ({ sku: i.sku, qty: Number(qty[i.sku]) })),
      })
      setQty({}); setPicked({})
      await load()
      setMsg(`${data.count}件を記録しました`)
    } catch (e) {
      setMsg(e.response?.data?.detail || '記録できませんでした')
    }
    setBusy(false)
  }

  const markReceived = async (o) => {
    setBusy(true); setMsg('')
    try {
      await api.patch(`/materials/orders/${o.id}`,
        { received_at: o.received_at ? '' : today() })
      await load()
    } catch (e) {
      setMsg(e.response?.data?.detail || '変えられませんでした')
    }
    setBusy(false)
  }

  const removeOrder = async (o) => {
    if (!confirm(`${o.ordered_at} の ${o.name}（${o.qty}）を消しますか？`)) return
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
        <div style={{ ...card, padding: 10, fontSize: 13, background: C.soft }}>{msg}</div>
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
                  <tr>{['', '発注日', '品名', '数', '入荷', '', ''].map((h, i) =>
                    <th key={i} style={th}>{h}</th>)}</tr>
                </thead>
                <tbody>
                  {orders.map(o => (
                    <tr key={o.id}>
                      <td style={td}>
                        <Thumb sku={o.sku} has={!!o.photo_url} alt={o.name} size={40} />
                      </td>
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
            marginBottom: 12, fontSize: 13, flexWrap: 'wrap' }}>
            <span>発注日</span>
            <input type="date" value={orderDate}
              onChange={e => setOrderDate(e.target.value)} />
            <button className="btn btn-primary" disabled={busy || !ready.length}
              onClick={submitPicked}>
              選んだ{ready.length}件を発注
            </button>
            <span style={{ color: C.sub, fontSize: 12 }}>
              レ点を付けて数を入れ、まとめて記録します。しばらく頼んでいないものが上に出ます
            </span>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={th}>
                    <input type="checkbox" onChange={toggleAll}
                      checked={shown.length > 0 && shown.every(i => picked[i.sku])} />
                  </th>
                  {['', '品名 / 仕入れ仕様', '発注済', '前回の発注', '発注数'].map((h, i) =>
                    <th key={i} style={th}>{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {shown.map(it => (
                  <tr key={it.sku} style={picked[it.sku] ? { background: '#eff6ff' } : undefined}>
                    <td style={td}>
                      <input type="checkbox" checked={!!picked[it.sku]}
                        onChange={e => setPicked(p => ({ ...p, [it.sku]: e.target.checked }))} />
                    </td>
                    <td style={td}>
                      <Thumb sku={it.sku} has={!!it.photo_url} alt={it.name} />
                    </td>
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
                    <td style={{ ...td, textAlign: 'right',
                      color: it.pending_qty ? C.warn : '#cbd5e1' }}>
                      {it.pending_qty || '—'}
                    </td>
                    <td style={{ ...td, whiteSpace: 'nowrap', color: C.sub, fontSize: 12 }}>
                      {it.last_ordered_at
                        ? <>{it.last_ordered_at}<div>{it.last_qty} 個</div></>
                        : <span style={{ color: C.warn }}>発注なし</span>}
                    </td>
                    <td style={td}>
                      <input type="number" min="0" style={{ width: 80 }}
                        value={qty[it.sku] ?? ''}
                        onChange={e => {
                          const v = e.target.value
                          setQty(q => ({ ...q, [it.sku]: v }))
                          // 数を入れたらレ点も付ける（付け忘れて記録されないのを防ぐ）
                          if (Number(v) > 0) setPicked(p => ({ ...p, [it.sku]: true }))
                        }} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
