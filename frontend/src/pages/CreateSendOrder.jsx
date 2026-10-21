import { useCallback, useEffect, useState } from 'react'
import api from '../api/client'
import { matchesQuery } from '../searchUtil'

/**
 * 配送依頼をタオタロウへ出す画面。
 *
 * これまでは向こうのサイトで手作業していた。APIで出せるように
 * なったので、入庫済みの注文を選んで、便と届け先を決めるだけにする。
 *
 * 便は船便・航空便の2つだけ出す。向こうの一覧には16種類あるが、
 * 使うものは決まっていて、毎回選ぶと押し間違いが起きる。
 * 備考には毎回「急ぎです。」が入る（サーバー側で付ける）。
 *
 * 届け先は3つある（作業所・FBA・自社）ので、ここは必ず選んでもらう。
 * 間違えると別の場所へ届いてしまうため、既定を置かない。
 */

const C = {
  line: '#e5e7eb', sub: '#64748b', text: '#0f172a',
  good: '#16a34a', warn: '#b45309', bad: '#dc2626', key: '#2563eb',
}

const td = { padding: '6px 8px', borderTop: `1px solid ${C.line}`, fontSize: 12,
  verticalAlign: 'top' }
const th = { padding: '6px 8px', textAlign: 'left', whiteSpace: 'nowrap',
  fontSize: 12, color: C.sub, background: '#f8fafc' }

export default function CreateSendOrder() {
  const [opts, setOpts] = useState(null)
  const [rows, setRows] = useState([])
  const [picked, setPicked] = useState(() => new Set())
  const [way, setWay] = useState('')
  const [addrId, setAddrId] = useState('')
  const [flag, setFlag] = useState(3)
  const [note, setNote] = useState('')
  const [q, setQ] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)

  const load = useCallback(async () => {
    setErr('')
    try {
      const [o, list] = await Promise.all([
        api.get('/taotaro/ship-options'),
        api.get('/taotaro/orders', { params: { page: 1, limit: 100 } }),
      ])
      setOpts(o.data)
      // 入庫済み（state 4）だけが配送依頼に入れられる
      setRows((list.data.items || []).filter(x => x.state === 4))
    } catch (e) {
      setErr(e?.response?.data?.detail || '読み込めませんでした')
    }
  }, [])

  useEffect(() => { load() }, [load])

  const shown = rows.filter(r => !q.trim()
    || matchesQuery(q, [r.out_id, r.title, r.title_trans]))

  const toggle = (oid) => setPicked(s => {
    const n = new Set(s)
    if (n.has(oid)) n.delete(oid); else n.add(oid)
    return n
  })

  const allShownPicked = shown.length > 0 && shown.every(r => picked.has(r.oid))
  const toggleAll = () => setPicked(s => {
    const n = new Set(s)
    if (allShownPicked) shown.forEach(r => n.delete(r.oid))
    else shown.forEach(r => n.add(r.oid))
    return n
  })

  // 送る前に、何がどこへ行くのかを文章で見せる。
  // 押したあとに「違う便だった」では取り返しがつかない
  const wayDef = (opts?.ways || []).find(w => w.key === way)
  const addrDef = (opts?.addresses || []).find(a => String(a.address_id) === String(addrId))
  const remarkPreview = [opts?.always_remark, wayDef?.note, note.trim()]
    .filter(Boolean).join('　')

  const submit = async () => {
    if (!picked.size || !way || !addrId) return
    const msg = '配送依頼を出します。\n\n'
      + `便　　：${wayDef.delivery_name}\n`
      + `届け先：${addrDef.consignee}\n`
      + `注文　：${picked.size}件\n`
      + `備考　：${remarkPreview}\n\n`
      + 'よろしいですか？'
    if (!window.confirm(msg)) return
    setBusy(true); setErr(''); setResult(null)
    try {
      const r = await api.post('/taotaro/send-orders', {
        oids: [...picked], way, address_id: Number(addrId),
        made_in_china_flag: Number(flag), note,
      })
      setResult(r.data)
      setPicked(new Set())
      load()
    } catch (e) {
      setErr(e?.response?.data?.detail || '出せませんでした')
    } finally { setBusy(false) }
  }

  if (!opts) {
    return <div style={{ padding: 20, color: C.sub, fontSize: 13 }}>
      {err || '読み込み中...'}
    </div>
  }

  const dests = (opts.addresses || []).filter(a => a.type === 1)

  return (
    <div>
      {result && (
        <div style={{ marginBottom: 12, padding: 10, borderRadius: 6,
          background: '#f0fdf4', border: `1px solid ${C.good}`, fontSize: 13 }}>
          <b style={{ color: C.good }}>
            配送依頼ができました（No. {result.sid}）
          </b>
          {result.duplicate && (
            <span style={{ color: C.warn, marginLeft: 8 }}>
              ※ 同じ内容がすでに出ていたので、新しくは作られていません
            </span>
          )}
          <div style={{ color: C.sub, marginTop: 4 }}>
            {result.delivery_name}　／　{result.oids?.length}件　／　{result.remark}
          </div>
        </div>
      )}

      {err && <div style={{ color: C.bad, fontSize: 12, marginBottom: 8 }}>{err}</div>}

      <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end',
        flexWrap: 'wrap', marginBottom: 12, padding: 10,
        background: '#f8fafc', borderRadius: 6 }}>
        <label style={{ fontSize: 12, color: C.sub }}>
          <div style={{ marginBottom: 3 }}>便</div>
          <select value={way} onChange={e => setWay(e.target.value)}
            style={{ fontSize: 13, padding: '5px 8px', minWidth: 180 }}>
            <option value="">選んでください</option>
            {opts.ways.map(w => (
              <option key={w.key} value={w.key}>{w.label}</option>
            ))}
          </select>
        </label>
        <label style={{ fontSize: 12, color: C.sub }}>
          <div style={{ marginBottom: 3 }}>届け先</div>
          <select value={addrId} onChange={e => setAddrId(e.target.value)}
            style={{ fontSize: 13, padding: '5px 8px', minWidth: 220 }}>
            <option value="">選んでください</option>
            {dests.map(a => (
              <option key={a.address_id} value={a.address_id}>{a.consignee}</option>
            ))}
          </select>
        </label>
        <label style={{ fontSize: 12, color: C.sub }}>
          <div style={{ marginBottom: 3 }}>MADE IN CHINA シール</div>
          <select value={flag} onChange={e => setFlag(e.target.value)}
            style={{ fontSize: 13, padding: '5px 8px' }}>
            <option value={3}>貼らない</option>
            <option value={1}>記載のない商品すべてに貼る</option>
            <option value={2}>外国語表記のあるものだけ貼る</option>
          </select>
        </label>
        <label style={{ fontSize: 12, color: C.sub, flex: 1, minWidth: 200 }}>
          <div style={{ marginBottom: 3 }}>備考に足すこと（任意）</div>
          <input value={note} onChange={e => setNote(e.target.value)}
            placeholder="例：10/25までに出してください"
            style={{ fontSize: 13, padding: '5px 8px', width: '100%',
              border: `1px solid ${C.line}`, borderRadius: 4 }} />
        </label>
      </div>

      <div style={{ fontSize: 12, color: C.sub, marginBottom: 10 }}>
        備考はこう入ります：<b style={{ color: C.text }}>{remarkPreview || '—'}</b>
      </div>

      <div style={{ display: 'flex', gap: 10, alignItems: 'center',
        flexWrap: 'wrap', marginBottom: 8 }}>
        <input value={q} onChange={e => setQ(e.target.value)}
          placeholder="SKU・商品名で絞り込み"
          style={{ padding: '6px 10px', border: `1px solid ${C.line}`,
            borderRadius: 6, fontSize: 13, width: 220 }} />
        <span style={{ fontSize: 12, color: C.sub }}>
          入庫済み {rows.length}件　／　選択中 <b style={{ color: C.text }}>{picked.size}</b>件
        </span>
        <button onClick={submit}
          disabled={busy || !picked.size || !way || !addrId}
          style={{ marginLeft: 'auto', padding: '7px 16px', fontSize: 13,
            border: 'none', borderRadius: 6, fontWeight: 600,
            background: (busy || !picked.size || !way || !addrId) ? '#cbd5e1' : C.key,
            color: '#fff',
            cursor: (busy || !picked.size || !way || !addrId) ? 'default' : 'pointer' }}>
          {busy ? '出しています…' : '🚢 この内容で配送依頼を出す'}
        </button>
      </div>

      <table style={{ width: '100%', borderCollapse: 'collapse',
        background: '#fff', border: `1px solid ${C.line}` }}>
        <thead>
          <tr>
            <th style={th}>
              <input type="checkbox" checked={allShownPicked} onChange={toggleAll} />
            </th>
            <th style={th}>SKU</th>
            <th style={th}>商品</th>
            <th style={th}>色</th>
            <th style={th}>数</th>
            <th style={th}>発注日</th>
          </tr>
        </thead>
        <tbody>
          {shown.map(r => (
            <tr key={r.oid} style={{ background: picked.has(r.oid) ? '#eff6ff' : '#fff' }}>
              <td style={td}>
                <input type="checkbox" checked={picked.has(r.oid)}
                  onChange={() => toggle(r.oid)} />
              </td>
              <td style={{ ...td, fontWeight: 600, whiteSpace: 'nowrap' }}>
                {r.out_id || '—'}
              </td>
              <td style={td}>{(r.title_trans || r.title || '').slice(0, 40)}</td>
              <td style={{ ...td, color: C.sub }}>
                {(r.sku_props || []).map(p => p.value).join(' / ')}
              </td>
              <td style={{ ...td, textAlign: 'right' }}>{r.quantity}</td>
              <td style={{ ...td, color: C.sub, whiteSpace: 'nowrap' }}>
                {String(r.created_at || '').slice(0, 10)}
              </td>
            </tr>
          ))}
          {!shown.length && (
            <tr><td colSpan={6} style={{ ...td, color: C.sub, textAlign: 'center',
              padding: 24 }}>
              {rows.length ? '絞り込みに合うものがありません'
                : '配送依頼に入れられる注文（入庫済み）がありません'}
            </td></tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
