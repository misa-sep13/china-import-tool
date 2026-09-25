import { useCallback, useMemo, useState } from 'react'
import api from '../api/client'
import { matchesQuery } from '../searchUtil'

/**
 * 楽天の発送処理。
 *
 * RMSの画面は一度に299件しか発送完了メールを送れない（この店舗だけの不具合）。
 * 伝票番号のCSVはこれまでどおり上げて、そのあとの
 *   ・ちゃんと入ったかの確認
 *   ・発送完了報告（＝発送完了メール）
 * をここでやる。APIは画面を通らないので299件の制限を受けない。
 *
 * いまは確認まで。発送完了報告は、この画面で送付先IDと発送明細IDが
 * 取れていることを確かめてから付ける。指定せずに報告すると発送情報が
 * 「追加」になり、伝票番号が二重に並ぶため。
 */

const C = {
  line: '#e5e7eb', sub: '#64748b', text: '#0f172a',
  good: '#16a34a', warn: '#b45309', bad: '#dc2626', key: '#2563eb',
}

// 発送完了報告で使う配送会社コード。表示用
const CARRIER = {
  '1001': 'ヤマト', '1002': '佐川', '1003': '日本郵便', '1004': '西濃',
  '1028': 'Rakuten EXPRESS', '1030': 'クロネコゆうパケット', '1000': 'その他',
}

const th = {
  padding: '6px 8px', textAlign: 'left', fontSize: 11, color: C.sub,
  background: '#f8fafc', whiteSpace: 'nowrap',
}
const td = { padding: '6px 8px', fontSize: 12, borderTop: `1px solid ${C.line}` }

// 日本郵便（1003）は追跡を付けずに出すので、伝票番号が無くても普通のこと。
// ここを見ないと、日本郵便の注文が毎回まるごと要確認になってしまう
const NO_TRACKING_CARRIERS = new Set(['1003'])

/**
 * このまま発送完了報告に出すと困る注文を見分ける。
 * 番号抜けがいちばん多いが、配送会社や発送日が欠けていても報告は通らない。
 */
function badReason(o) {
  const ships = o.shipments || []
  if (!ships.length) return '発送情報がありません'
  // 配送会社が先。これが無いと「追跡が要るのかどうか」も決められない
  if (ships.some(s => !s.delivery_company)) return '配送会社が入っていません'
  // 追跡を付けない配送会社は、伝票番号が無くても問題にしない
  const needNumber = ships.filter(
    s => !NO_TRACKING_CARRIERS.has(String(s.delivery_company || '')))
  const miss = needNumber.filter(s => !s.shipping_number)
  if (needNumber.length && miss.length === needNumber.length) {
    return '伝票番号が入っていません'
  }
  if (miss.length) return '伝票番号が入っていない送付先があります'
  if (ships.some(s => !s.shipping_date)) return '発送日が入っていません'
  return ''
}

export default function RakutenShippingPage() {
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [days, setDays] = useState(45)
  const [group, setGroup] = useState('ALL')
  const [onlyBad, setOnlyBad] = useState(false)
  const [q, setQ] = useState('')
  // メールを送る対象。注文番号で持つ
  const [picked, setPicked] = useState(() => new Set())
  const [showPicked, setShowPicked] = useState(false)
  // サブステータスの名前。一覧を取るAPIが権限不足で401なので、自分で付ける
  const [naming, setNaming] = useState(false)
  const [names, setNames] = useState({})
  const [canReport, setCanReport] = useState(null)
  // メール送信。発送日は既定で今日。空欄にすると、いま入っている値のまま送る
  const [sendDate, setSendDate] = useState(() => new Date()
    .toLocaleDateString('sv-SE'))
  const [sendCarrier, setSendCarrier] = useState('')
  const [sending, setSending] = useState('')
  const [sendResult, setSendResult] = useState(null)
  // 送り終えた注文。一覧はすぐには変わらない（楽天側の処理が非同期）ので、
  // 選び直したときに二重で送ってしまわないよう、こちらで覚えておく
  const [sentShip, setSentShip] = useState(() => new Set())
  const [sentConfirm, setSentConfirm] = useState(() => new Set())

  const load = useCallback(async () => {
    setBusy(true)
    setErr('')
    try {
      const r = await api.get('/rakuten/shipping/targets', { params: { days } })
      setData(r.data)
      const init = {}
      for (const g of r.data.groups || []) if (g.id) init[g.id] = g.name || ''
      setNames(init)
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally {
      setBusy(false)
    }
  }, [days])

  const orders = data?.orders || []
  const shown = useMemo(() => orders.filter(o => {
    if (group !== 'ALL' && String(o.sub_status_id ?? '') !== group) return false
    if (onlyBad && !badReason(o)) return false
    if (q.trim() && !matchesQuery(q, [o.order_number, o.orderer,
      ...(o.shipments || []).map(s => s.shipping_number)])) return false
    return true
  }), [orders, group, onlyBad, q])

  const badCount = orders.filter(badReason).length
  const diag = data?.diagnostics
  const pickedOrders = useMemo(
    () => orders.filter(o => picked.has(o.order_number)), [orders, picked])

  const toggle = (num) => setPicked(prev => {
    const next = new Set(prev)
    if (next.has(num)) next.delete(num); else next.add(num)
    return next
  })
  // 表示中のものをまとめて選ぶ。絞り込んだ状態で押せば、その分だけ入る
  const pickShown = () => setPicked(prev => {
    const next = new Set(prev)
    shown.forEach(o => { if (!sentShip.has(o.order_number)) next.add(o.order_number) })
    return next
  })
  const selectable = shown.filter(o => !sentShip.has(o.order_number))
  const shownAllPicked = selectable.length > 0
    && selectable.every(o => picked.has(o.order_number))

  // 受注承諾メール。注文確認を出すと楽天からメールが出る
  const sendConfirm = async () => {
    const n = picked.size
    if (!n) return
    const ask = [
      `選んだ ${n}件に受注承諾メールを送ります。`,
      '',
      '楽天から実際にお客様へメールが届きます。よろしいですか？',
    ].join('\n')
    if (!window.confirm(ask)) return
    setSending('confirm'); setSendResult(null)
    try {
      const r = await api.post('/rakuten/shipping/confirm-orders',
        { order_numbers: [...picked] })
      setSendResult({ kind: '受注承諾メール', ...r.data })
      const done = new Set([...picked])
      setSentConfirm(prev => new Set([...prev, ...done]))
      setPicked(new Set())
    } catch (e) {
      alert('送れませんでした: ' + (e.response?.data?.detail || e.message))
    } finally { setSending('') }
  }

  // 発送メール。発送完了報告を出すと、注文が発送済になってメールが出る
  const sendShipping = async () => {
    const n = picked.size
    if (!n) return
    const bad = pickedOrders.filter(badReason).length
    const lines = [`選んだ ${n}件を発送完了にします。`]
    lines.push(sendDate ? `発送日：${sendDate}` : '発送日：いまの値のまま')
    if (sendCarrier) {
      lines.push(`配送会社：${CARRIER[sendCarrier]}（選んだ全件を上書き）`)
    }
    if (bad) {
      lines.push('', `※ 要確認が ${bad}件あります。弾かれる可能性があります。`)
    }
    lines.push('', '楽天から実際にお客様へ発送メールが届きます。よろしいですか？')
    if (!window.confirm(lines.join('\n'))) return
    setSending('ship'); setSendResult(null)
    try {
      const r = await api.post('/rakuten/shipping/report', {
        order_numbers: [...picked],
        shipping_date: sendDate || null,
        delivery_company: sendCarrier || null,
      })
      setSendResult({ kind: '発送メール', ...r.data })
      const done = new Set([...picked])
      setSentShip(prev => new Set([...prev, ...done]))
      setPicked(new Set())
    } catch (e) {
      alert('送れませんでした: ' + (e.response?.data?.detail || e.message))
    } finally { setSending('') }
  }

  const saveNames = async () => {
    try {
      await api.put('/rakuten/shipping/sub-status-names', { names })
      setNaming(false)
      await load()
    } catch (e) {
      alert('保存できませんでした: ' + (e.response?.data?.detail || e.message))
    }
  }

  // 発送完了報告のAPIが使えるか。中身が空のリクエストを1本投げるだけで、
  // 注文は何も変わらない
  const checkReport = async () => {
    try {
      const r = await api.get('/rakuten/shipping/can-report')
      setCanReport(r.data)
    } catch (e) {
      setCanReport({ error: { label: '確認できませんでした', ok: false,
        status: 0, body: e.response?.data?.detail || e.message } })
    }
  }

  return (
    <div style={{ padding: 2, minWidth: 0 }}>
      <h2 style={{ fontSize: 18, marginBottom: 4 }}>🚚 楽天 発送処理</h2>
      <div style={{ fontSize: 12, color: C.sub, marginBottom: 12 }}>
        伝票番号のCSVを上げたあと、ちゃんと入ったかをここで確認します。
        発送待ちの注文だけを出しています。
      </div>

      {err && (
        <div style={{
          background: '#fef2f2', border: '1px solid #fecaca', color: '#991b1b',
          padding: 10, borderRadius: 6, marginBottom: 10, fontSize: 13,
        }}>{err}</div>
      )}

      <div className="card" style={{
        marginBottom: 12, display: 'flex', gap: 12, alignItems: 'center',
        flexWrap: 'wrap',
      }}>
        <label style={{ fontSize: 12, color: C.sub }}>
          注文日から
          <input type="number" min={1} max={90} value={days}
            onChange={e => setDays(Number(e.target.value))}
            style={{ width: 60, margin: '0 4px' }} />
          日ぶん
        </label>
        <button className="btn btn-primary" onClick={load} disabled={busy}>
          {busy ? '読み込み中…（数十秒かかります）' : '読み込む'}
        </button>
        {data && (
          <>
            <span style={{ fontSize: 13 }}>
              発送待ち <b>{data.total}</b>件
              {badCount > 0 && (
                <span style={{ color: C.bad, fontWeight: 700 }}>
                  　要確認 {badCount}件
                </span>
              )}
            </span>
            <button className="btn btn-sm"
              onClick={() => setOnlyBad(v => !v)}
              style={{
                fontSize: 12,
                background: onlyBad ? '#fee2e2' : '#f1f5f9',
                color: onlyBad ? '#991b1b' : '#334155',
                border: `1px solid ${onlyBad ? '#fca5a5' : C.line}`,
              }}>
              ⚠ 要確認だけ出す（{badCount}）
            </button>
            <input value={q} onChange={e => setQ(e.target.value)}
              placeholder="注文番号・お名前・伝票番号で絞り込み"
              className="search-input-ja" style={{ width: 240 }} />
          </>
        )}
      </div>

      {/* サブステータス。本日発送分・あざみ分・在庫切れ1 など */}
      {data && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
          <Tab on={group === 'ALL'} onClick={() => setGroup('ALL')}
            label="すべて" count={orders.length} />
          {(data.groups || []).map(g => (
            <Tab key={g.id || 'none'} on={group === g.id}
              onClick={() => setGroup(g.id)}
              label={g.name || `サブステータス ${g.id}`} count={g.count} />
          ))}
        </div>
      )}

      {/* サブステータスの一覧を取るAPIは、この店舗の鍵では権限が無く401になる。
          番号のままだと見分けられないので、こちらで名前を付けられるようにした */}
      {data && (data.groups || []).some(g => g.id && !g.name) && !naming && (
        <div style={{ marginBottom: 12, fontSize: 12, color: '#92400e',
          background: '#fffbeb', border: '1px solid #fcd34d',
          borderRadius: 6, padding: '6px 10px', display: 'flex',
          alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <span>
            サブステータスの名前を楽天から取れません（このAPIだけ権限がありません）。
            ここで名前を付けると、次から表示されます。
          </span>
          <button className="btn btn-sm btn-secondary" style={{ fontSize: 12 }}
            onClick={() => setNaming(true)}>名前を付ける</button>
        </div>
      )}

      {naming && data && (
        <div className="card" style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 12, color: C.sub, marginBottom: 8 }}>
            番号に名前を付けます（本日発送分・あざみ分・在庫切れ1 など）。
            覚えておくので、付けるのは一度だけです。
          </div>
          {(data.groups || []).filter(g => g.id).map(g => (
            <div key={g.id} style={{ display: 'flex', gap: 8, alignItems: 'center',
              marginBottom: 6 }}>
              <span style={{ fontFamily: 'monospace', fontSize: 12, width: 90,
                color: C.sub }}>{g.id}</span>
              <span style={{ fontSize: 11, color: C.sub, width: 60 }}>
                {g.count}件
              </span>
              <input value={names[g.id] ?? ''} placeholder="例: 本日発送分"
                onChange={e => setNames(v => ({ ...v, [g.id]: e.target.value }))}
                style={{ width: 240, fontSize: 12 }} />
            </div>
          ))}
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button className="btn btn-primary btn-sm" onClick={saveNames}>
              保存する
            </button>
            <button className="btn btn-secondary btn-sm"
              onClick={() => setNaming(false)}>やめる</button>
          </div>
        </div>
      )}

      {/* メールを送る対象を選ぶ。1件ずつ開かずに済むようにする */}
      {data && (
        <div className="card" style={{ marginBottom: 12, display: 'flex',
          gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <button className="btn btn-sm btn-secondary" style={{ fontSize: 12 }}
            onClick={pickShown} disabled={shown.length === 0}>
            表示中をすべて選ぶ（{selectable.length}）
          </button>
          <button className="btn btn-sm btn-secondary" style={{ fontSize: 12 }}
            onClick={() => setPicked(new Set())} disabled={picked.size === 0}>
            選択を解除
          </button>
          <span style={{ fontSize: 13 }}>
            選択中 <b style={{ color: picked.size ? C.key : C.sub }}>{picked.size}</b>件
          </span>
          {picked.size > 0 && (
            <button className="btn btn-sm" style={{ fontSize: 12 }}
              onClick={() => setShowPicked(v => !v)}>
              {showPicked ? '▲ 選んだものを閉じる' : '▼ 選んだものを一覧で見る'}
            </button>
          )}
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 8,
            alignItems: 'center' }}>
            {canReport && Object.values(canReport).map((r, i) => (
              <span key={i} style={{ fontSize: 11,
                color: r.ok ? C.good : C.bad }}>
                {r.ok ? `✓ ${r.label}` : `✕ ${r.label}（${r.status}）`}
              </span>
            ))}
            <button className="btn btn-sm btn-secondary" style={{ fontSize: 11 }}
              onClick={checkReport}
              title="中身が空のリクエストを1本ずつ投げて、権限があるかだけ見ます。注文は変わりません">
              メールのAPIが使えるか確かめる
            </button>
          </span>
        </div>
      )}

      {/* メールを送る。文面は楽天のテンプレートで、こちらは報告するだけ */}
      {data && picked.size > 0 && (
        <div className="card" style={{ marginBottom: 12, display: 'flex',
          gap: 12, alignItems: 'center', flexWrap: 'wrap',
          border: '1px solid #bfdbfe', background: '#eff6ff' }}>
          <b style={{ fontSize: 13 }}>選んだ {picked.size}件に</b>

          <button className="btn btn-primary btn-sm" style={{ fontSize: 12 }}
            onClick={sendConfirm} disabled={!!sending}>
            {sending === 'confirm' ? '送信中…' : '📧 受注承諾メールを送る'}
            {[...picked].some(n => sentConfirm.has(n)) ? '（送信済みを含みます）' : ''}
          </button>

          <span style={{ borderLeft: `1px solid ${C.line}`, height: 22 }} />

          <label style={{ fontSize: 12, color: C.sub }}>
            発送日
            <input type="date" value={sendDate}
              onChange={e => setSendDate(e.target.value)}
              style={{ width: 140, marginLeft: 4, fontSize: 12 }} />
          </label>
          <label style={{ fontSize: 12, color: C.sub }}>
            配送会社
            <select value={sendCarrier}
              onChange={e => setSendCarrier(e.target.value)}
              style={{ width: 150, marginLeft: 4, fontSize: 12 }}>
              <option value="">いまの値のまま</option>
              {Object.entries(CARRIER).map(([code, name]) => (
                <option key={code} value={code}>{name}</option>
              ))}
            </select>
          </label>
          <button className="btn btn-primary btn-sm"
            style={{ fontSize: 12, background: '#16a34a' }}
            onClick={sendShipping} disabled={!!sending}>
            {sending === 'ship' ? '送信中…' : '🚚 発送メールを送る（発送完了報告）'}
          </button>

          <span style={{ fontSize: 11, color: C.sub, width: '100%' }}>
            発送日を空欄にすると、いま入っている値のまま報告します。
            配送会社を選ぶと、選んだ注文すべてがその会社で上書きされます。
            文面は楽天のテンプレートで、こちらは報告するだけです。
          </span>
        </div>
      )}

      {/* 送った結果。弾かれた注文は注文番号つきで出す */}
      {sendResult && (
        <div style={{ marginBottom: 12, fontSize: 12, padding: '8px 10px',
          borderRadius: 6,
          background: (sendResult.errors || []).length ? '#fffbeb' : '#f0fdf4',
          border: `1px solid ${(sendResult.errors || []).length ? '#fcd34d' : '#bbf7d0'}`,
          color: (sendResult.errors || []).length ? '#92400e' : '#166534' }}>
          <b>{sendResult.kind}</b>：
          {sendResult.request_ids
            ? `${sendResult.target}件を受け付けました（処理は楽天側で順に行われます）`
            : `${sendResult.ok}件を送りました`}
          {(sendResult.skipped || []).length > 0 && (
            <div>発送情報が無いため送れなかった注文 {sendResult.skipped.length}件：
              {sendResult.skipped.slice(0, 5).join('、')}
              {sendResult.skipped.length > 5 ? ' ほか' : ''}
            </div>
          )}
          {(sendResult.errors || []).length > 0 && (
            <div style={{ marginTop: 4 }}>
              弾かれたもの {sendResult.errors.length}件：
              {sendResult.errors.slice(0, 8).map((e, i) => (
                <div key={i} style={{ fontSize: 11 }}>
                  {e.order_number || '（注文番号なし）'} — {e.message}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 選んだものだけの一覧。RMSの画面を1件ずつ開かずに確かめられる */}
      {showPicked && picked.size > 0 && (
        <div className="card" style={{ marginBottom: 12, padding: 0,
          overflow: 'auto', maxHeight: 320 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>{['注文番号', 'お名前', '配送会社', 'お荷物伝票番号', '発送日', '']
                .map(h => <th key={h} style={th}>{h}</th>)}</tr>
            </thead>
            <tbody>
              {pickedOrders.map(o => {
                const s0 = (o.shipments || [])[0] || {}
                const bad = badReason(o)
                return (
                  <tr key={o.order_number} style={{ background: bad ? '#fff7ed' : undefined }}>
                    <td style={{ ...td, fontFamily: 'monospace', fontSize: 11 }}>
                      {o.order_number}
                    </td>
                    <td style={td}>{o.orderer}</td>
                    <td style={td}>
                      {CARRIER[s0.delivery_company] || s0.delivery_company || '—'}
                    </td>
                    <td style={{ ...td, fontFamily: 'monospace', fontSize: 11 }}>
                      {s0.shipping_number || '—'}
                    </td>
                    <td style={{ ...td, color: C.sub }}>{s0.shipping_date || '—'}</td>
                    <td style={{ ...td, color: C.bad, fontSize: 11 }}>{bad}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* 項目名が仕様と違っていたら、ここで気づけるようにしておく。
          発送完了報告には送付先IDと発送明細IDが要る */}
      {diag && (
        <div style={{
          marginBottom: 12, fontSize: 12, padding: '6px 10px', borderRadius: 6,
          background: diag.with_shipping_detail_id > 0 ? '#f0fdf4' : '#fffbeb',
          border: `1px solid ${diag.with_shipping_detail_id > 0 ? '#bbf7d0' : '#fcd34d'}`,
          color: diag.with_shipping_detail_id > 0 ? '#166534' : '#92400e',
        }}>
          発送完了報告に要る値：{data.total}件のうち
          送付先IDが取れたもの {diag.with_basket_id}件、
          発送明細IDが取れたもの {diag.with_shipping_detail_id}件。
          {diag.with_shipping_detail_id === 0
            ? '発送明細IDが取れていません。このまま報告すると発送情報が二重に登録されるので、報告は付けられません。'
            : diag.with_shipping_detail_id < data.total
              ? `残り ${data.total - diag.with_shipping_detail_id}件はまだ発送情報がありません（伝票番号が未入力の注文です）。それ以外は発送完了報告に出せます。`
              : '全件そろっています。発送完了報告まで作れます。'}
        </div>
      )}

      {data && (
        <div className="card" style={{ padding: 0, overflow: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th style={{ ...th, width: 30 }}>
                  <input type="checkbox" checked={shownAllPicked}
                    onChange={e => e.target.checked
                      ? pickShown()
                      : setPicked(prev => {
                        const next = new Set(prev)
                        shown.forEach(o => next.delete(o.order_number))
                        return next
                      })}
                    style={{ width: 'auto' }}
                    title="表示中をすべて選ぶ" />
                </th>
                {['注文番号', '注文日', 'サブステータス', 'お名前', '配送会社',
                  'お荷物伝票番号', '発送日', '要確認'].map(h => (
                    <th key={h} style={th}>{h}</th>
                  ))}
              </tr>
            </thead>
            <tbody>
              {shown.length === 0 && (
                <tr><td style={{ ...td, color: C.sub, padding: 20 }} colSpan={9}>
                  出す注文がありません。
                </td></tr>
              )}
              {shown.map(o => {
                const ships = (o.shipments && o.shipments.length) ? o.shipments : [{}]
                const bad = badReason(o)
                const on = picked.has(o.order_number)
                const sent = sentShip.has(o.order_number)
                return ships.map((s, i) => (
                  <tr key={`${o.order_number}-${i}`}
                    style={{ background: sent ? '#f0fdf4'
                      : on ? '#eff6ff' : bad ? '#fff7ed' : undefined,
                      color: sent ? C.sub : undefined }}>
                    <td style={td}>
                      {i === 0 && (sent
                        ? <span title="この画面から送信済み。二重に送らないよう、選べないようにしています"
                          style={{ fontSize: 14 }}>✓</span>
                        : <input type="checkbox" checked={on} style={{ width: 'auto' }}
                          onChange={() => toggle(o.order_number)} />)}
                    </td>
                    <td style={{ ...td, fontFamily: 'monospace', fontSize: 11 }}>
                      {i === 0 ? o.order_number : ''}
                    </td>
                    <td style={{ ...td, whiteSpace: 'nowrap', color: C.sub }}>
                      {i === 0 ? o.order_date : ''}
                    </td>
                    <td style={{ ...td, whiteSpace: 'nowrap' }}>
                      {i === 0
                        ? (o.sub_status_name
                          || (o.sub_status_id ? `サブステータス ${o.sub_status_id}` : '—'))
                        : ''}
                    </td>
                    <td style={{ ...td, whiteSpace: 'nowrap' }}>
                      {i === 0 ? o.orderer : ''}
                    </td>
                    <td style={{ ...td, whiteSpace: 'nowrap' }}>
                      {CARRIER[s.delivery_company] || s.delivery_company || '—'}
                    </td>
                    <td style={{
                      ...td, fontFamily: 'monospace', fontSize: 11,
                      color: s.shipping_number ? C.text : C.bad,
                      fontWeight: s.shipping_number ? 400 : 700,
                    }}>
                      {s.shipping_number || '未入力'}
                    </td>
                    <td style={{ ...td, whiteSpace: 'nowrap', color: C.sub }}>
                      {s.shipping_date || '—'}
                    </td>
                    <td style={{ ...td, fontSize: 11,
                      color: sent ? C.good : C.bad }}>
                      {i !== 0 ? '' : sent ? '発送メール送信済み' : bad}
                    </td>
                  </tr>
                ))
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function Tab({ on, onClick, label, count }) {
  return (
    <button onClick={onClick} className="btn btn-sm"
      style={{
        fontSize: 12, padding: '3px 10px',
        background: on ? '#2563eb' : '#f1f5f9',
        color: on ? '#fff' : '#334155',
        border: `1px solid ${on ? '#2563eb' : C.line}`,
      }}>
      {label}（{count}）
    </button>
  )
}
