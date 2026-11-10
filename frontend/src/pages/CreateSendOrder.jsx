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

/**
 * タオタロウの注文に、ASIN・FNSKU・管理番号を後から入れる。
 *
 * 初回発注のときは、その商品をまだAmazonに出品していないので
 * FNSKUもASINも存在しない。発注画面では入れようがなく、空のまま
 * 注文が作られる。出品してFNSKUが出たあとに、ここで入れる。
 *
 * 空いている欄だけ埋める。すでに入っているものは触らない。
 * 出荷してしまったあとの注文は、もうラベルを貼り終わっているので対象外。
 */
function IdFiller() {
  const [plan, setPlan] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')
  const [failed, setFailed] = useState([])

  // keep=true のときは、直前に出した結果の文を消さない。
  // 書き込みのあと自動で下見し直すが、そこで「○件入れました」が
  // 消えてしまうと、何が起きたのか分からなくなる
  const preview = async (keep = false) => {
    setBusy(true); setPlan(null)
    if (!keep) { setErr(''); setMsg(''); setFailed([]) }
    try {
      const r = await api.get('/taotaro/ids/preview')
      setPlan(r.data)
      if (!keep && !(r.data.fill || []).length) {
        setMsg(`入れるものはありませんでした（${r.data.scanned}件みました）`)
      }
    } catch (e) {
      const d = e?.response?.data?.detail || '下見できませんでした'
      // 書き込みの結果を消さないよう、あとから足す
      setErr(p => (keep && p) ? p : d)
    } finally { setBusy(false) }
  }

  const apply = async () => {
    const n = (plan?.fill || []).length
    if (!n) return
    if (!confirm(`タオタロウの注文 ${n}件 に、ASIN・FNSKU・管理番号を入れます。
空いている欄だけ埋めます（入っているものは触りません）。

よろしいですか？`)) return
    setBusy(true); setErr(''); setMsg(''); setFailed([])
    try {
      const r = await api.post('/taotaro/ids/apply', {})
      setMsg(`${r.data.done_count}件に入れました`
        + (r.data.failed_count ? `／${r.data.failed_count}件は入りませんでした` : ''))
      setFailed(r.data.failed || [])
      // ログインが切れて止まったときは、理由をそのまま出す
      if (r.data.stopped) setErr(r.data.stopped)
      await preview(true)
    } catch (e) {
      setErr(e?.response?.data?.detail || '入れられませんでした')
    } finally { setBusy(false) }
  }

  const fill = plan?.fill || []
  const skip = plan?.skip || []
  const label = { asin: 'ASIN', fnsku: 'FNSKU', out_id: '管理番号' }

  return (
    <div style={{ marginBottom: 12, padding: 10, borderRadius: 6,
      background: '#f8fafc', border: `1px solid ${C.line}` }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center',
        flexWrap: 'wrap' }}>
        <b style={{ fontSize: 13 }}>ASIN・FNSKU・管理番号をタオタロウに入れる</b>
        <button onClick={preview} disabled={busy}
          style={{ fontSize: 12, padding: '4px 10px' }}>
          {busy ? '…' : '下見する'}
        </button>
        {!!fill.length && (
          <button onClick={apply} disabled={busy}
            style={{ fontSize: 12, padding: '4px 10px', fontWeight: 700,
              background: C.key, color: '#fff', border: 'none',
              borderRadius: 4, cursor: 'pointer' }}>
            {fill.length}件に入れる
          </button>
        )}
        <span style={{ fontSize: 11, color: C.sub }}>
          空いている欄だけ埋めます。出荷済みの注文は触りません
        </span>
      </div>

      {err && (
        <div style={{ marginTop: 8, padding: '8px 10px', borderRadius: 5,
          background: '#fef2f2', border: '1px solid #fca5a5',
          color: '#b91c1c', fontSize: 12, lineHeight: 1.8 }}>
          {err}
          {err.includes('ログイン') && (
            <div style={{ marginTop: 4 }}>
              <a href="#/settings" style={{ color: '#b91c1c', fontWeight: 700 }}>
                → Amazon設定でCookieを貼り直す
              </a>
            </div>
          )}
        </div>
      )}
      {msg && <div style={{ color: C.good, fontSize: 12, marginTop: 6 }}>{msg}</div>}

      {!!fill.length && (
        <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: 8 }}>
          <thead>
            <tr>
              <th style={th}>注文No.</th>
              <th style={th}>SKU</th>
              <th style={th}>入れるもの</th>
              <th style={th}>どう突き合わせたか</th>
              <th style={th}>足りないもの</th>
            </tr>
          </thead>
          <tbody>
            {fill.map(x => (
              <tr key={x.oid}>
                <td style={td}>{x.oid}</td>
                <td style={td}>{x.sku}</td>
                <td style={td}>
                  {Object.entries(x.put).map(([k, v]) => (
                    <div key={k}>{label[k] || k}: <b>{v}</b></div>
                  ))}
                </td>
                <td style={{ ...td, color: C.sub }}>{x.matched_by}</td>
                <td style={{ ...td, color: C.warn }}>{x.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {!!failed.length && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 12, color: C.bad, fontWeight: 700 }}>
            入らなかったもの {failed.length}件
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th style={th}>注文No.</th>
                <th style={th}>SKU</th>
                <th style={th}>入れようとしたもの</th>
                <th style={th}>理由</th>
              </tr>
            </thead>
            <tbody>
              {failed.map(x => (
                <tr key={x.oid}>
                  <td style={td}>{x.oid}</td>
                  <td style={td}>{x.sku}</td>
                  <td style={td}>
                    {Object.entries(x.put || {}).map(([k, v]) => (
                      <div key={k}>{label[k] || k}: <b>{v}</b></div>
                    ))}
                  </td>
                  <td style={{ ...td, color: C.bad }}>{x.error}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!!skip.length && (
        <details style={{ marginTop: 8 }}>
          <summary style={{ fontSize: 12, color: C.sub, cursor: 'pointer' }}>
            入れられなかったもの {skip.length}件
          </summary>
          <div style={{ fontSize: 11, color: C.sub, marginTop: 4 }}>
            {skip.map(x => (
              <div key={x.oid}>
                {x.oid}　{x.title?.slice(0, 28)}　— {x.reason}
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  )
}


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
  // 選んだ注文の確認結果。タオタロウの配送依頼は、セット組みの付属品が
  // 入っていなくても通ってしまうので、ここで止める
  const [check, setCheck] = useState({ kinds: {}, problems: [] })
  const [checking, setChecking] = useState(false)
  const [override, setOverride] = useState(false)

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

  // 選び直すたびに確かめる（少し待ってから。連続でチェックしたときに何度も呼ばない）
  useEffect(() => {
    if (!rows.length) return
    setChecking(true)
    const t = setTimeout(async () => {
      try {
        const r = await api.post('/taotaro/send-check', { oids: [...picked] })
        setCheck(r.data || { kinds: {}, problems: [] })
      } catch (e) {
        setCheck({ kinds: {}, problems: [{ level: 'warn', add_oids: [],
          text: '確認できませんでした：' + (e?.response?.data?.detail || e.message) }] })
      } finally { setChecking(false) }
    }, 400)
    setOverride(false)
    return () => clearTimeout(t)
  }, [picked, rows])

  const errors = (check.problems || []).filter(p => p.level === 'error')
  const blocked = errors.length > 0 && !override
  const addOids = (oids) => setPicked(s => {
    const n = new Set(s)
    oids.forEach(o => n.add(o))
    return n
  })

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
    if (!picked.size || !way || !addrId || blocked || checking) return
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
      <IdFiller />

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
        {(() => {
          const off = busy || checking || blocked || !picked.size || !way || !addrId
          const why = !picked.size ? '注文を選んでください'
            : !way ? '便を選んでください'
            : !addrId ? '届け先を選んでください'
            : checking ? '確かめています…'
            : blocked ? '下の赤い問題を直してください' : ''
          return (
            <span style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 8 }}>
              {why && <span style={{ fontSize: 12, color: blocked ? C.bad : C.sub }}>{why}</span>}
              <button onClick={submit} disabled={off}
                style={{ padding: '7px 16px', fontSize: 13,
                  border: 'none', borderRadius: 6, fontWeight: 600,
                  background: off ? '#cbd5e1' : C.key, color: '#fff',
                  cursor: off ? 'default' : 'pointer' }}>
                {busy ? '出しています…' : '🚢 この内容で配送依頼を出す'}
              </button>
            </span>
          )
        })()}
      </div>

      {(check.problems || []).length > 0 && (
        <div style={{ marginBottom: 10, padding: '10px 12px', borderRadius: 8, fontSize: 13,
          lineHeight: 1.7, border: `2px solid ${errors.length ? C.bad : '#f59e0b'}`,
          background: errors.length ? '#fef2f2' : '#fffbeb' }}>
          {check.problems.map((p, i) => (
            <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'flex-start',
              padding: '3px 0', borderTop: i ? '1px dashed #fecaca' : 'none' }}>
              <span style={{ fontWeight: 700, color: p.level === 'error' ? C.bad : C.warn,
                whiteSpace: 'nowrap' }}>{p.level === 'error' ? '⛔ 送れません' : '⚠ 確認'}</span>
              <span style={{ flex: 1 }}>{p.text}</span>
              {p.add_oids?.length > 0 && (
                <button onClick={() => addOids(p.add_oids)}
                  style={{ whiteSpace: 'nowrap', fontSize: 12, padding: '3px 10px',
                    border: `1px solid ${C.key}`, color: C.key, background: '#fff',
                    borderRadius: 5, cursor: 'pointer' }}>
                  ＋ 付属品の注文（{p.add_oids.length}件）を入れる
                </button>
              )}
            </div>
          ))}
          {errors.length > 0 && (
            <label style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 6,
              fontSize: 12, color: C.sub }}>
              <input type="checkbox" checked={override} onChange={e => setOverride(e.target.checked)} />
              承知のうえで送る（付属品は別の便で送る・セット組みしない など）
            </label>
          )}
        </div>
      )}

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
                {(() => {
                  // 本体か付属品か。付属品は管理番号が違っていても仕様で見分けた結果
                  const k = (check.kinds || {})[r.oid] || {}
                  const tag = { body: ['本体', '#dbeafe', '#1d4ed8'],
                    component: ['付属品', '#fef3c7', '#92400e'],
                    unknown: ['マスタに無い', '#fee2e2', '#b91c1c'] }[k.kind]
                  return (
                    <>
                      {tag && <span style={{ fontSize: 10, padding: '1px 5px', borderRadius: 4,
                        background: tag[1], color: tag[2], marginRight: 5 }}>{tag[0]}</span>}
                      {r.out_id || '—'}
                      {k.kind === 'component' && k.sku && k.sku !== r.out_id && (
                        <div style={{ fontSize: 10, color: C.warn, fontWeight: 400 }}>→ {k.sku} とみなしました</div>
                      )}
                      {k.name && <div style={{ fontSize: 10, color: C.sub, fontWeight: 400 }}>{k.name.slice(0, 24)}</div>}
                    </>
                  )
                })()}
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
