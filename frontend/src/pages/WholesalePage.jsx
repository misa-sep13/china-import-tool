import { useEffect, useState } from 'react'
import api from '../api/client'

/** 今日の日付。toISOString はUTCになり、朝9時前は前日になってしまう */
function today() {
  const d = new Date()
  const p = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

/**
 * 卸発注（メーカー品）。
 *
 * 発注書のExcelを作って、内容を確認してからメールで送る。
 * 送信は取り消せないので、必ずプレビューを挟む作りにしている。
 */
export default function WholesalePage() {
  const [tab, setTab] = useState('order')
  const [suppliers, setSuppliers] = useState([])
  const [supplierId, setSupplierId] = useState(null)
  const [items, setItems] = useState([])
  const [qty, setQty] = useState({})            // item_id → 数量
  const [orders, setOrders] = useState([])
  const [preview, setPreview] = useState(null)  // 送信前の確認
  const [mailStatus, setMailStatus] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [receiving, setReceiving] = useState(null)   // 入荷ダイアログ
  const [message, setMessage] = useState(null)      // LINEに貼る文面
  const [orderDate, setOrderDate] = useState(today)
  // 手で日付を変えたかどうか。変えていなければ今日に追従させる
  const [dateTouched, setDateTouched] = useState(false)

  const load = async () => {
    setErr('')
    try {
      const [s, m] = await Promise.all([
        api.get('/wholesale/suppliers'),
        api.get('/wholesale/mail/status'),
      ])
      setSuppliers(s.data)
      setMailStatus(m.data)
      if (s.data.length && supplierId == null) setSupplierId(s.data[0].id)
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    }
  }
  useEffect(() => { load() }, [])

  // 画面を開いたまま日付をまたぐことがあるので、今日に合わせ続ける。
  // 手で変えていたらそのまま残す
  useEffect(() => {
    const id = setInterval(() => {
      if (!dateTouched) setOrderDate(d => (d === today() ? d : today()))
    }, 60000)
    return () => clearInterval(id)
  }, [dateTouched])

  useEffect(() => {
    if (!supplierId) return
    setErr('')
    api.get(`/wholesale/items?supplier_id=${supplierId}&active_only=true`)
      .then(r => { setItems(r.data); setQty({}) })
      .catch(e => setErr(e.response?.data?.detail || e.message))
    api.get(`/wholesale/orders?supplier_id=${supplierId}`)
      .then(r => setOrders(r.data))
      .catch(() => {})
  }, [supplierId])

  const chosen = items.filter(i => (qty[i.id] || 0) > 0)
  const subtotal = chosen.reduce((a, i) => a + (i.unit_price || 0) * (qty[i.id] || 0), 0)
  const tax = subtotal * 0.1
  const total = Math.floor(subtotal + tax)

  // 納品先は商品ごとに決まっている。違う送り先を混ぜると
  // 1枚の発注書に書けないので、選んだ時点で気づけるようにする
  const places = [...new Set(chosen.map(i => `${i.deliver_zip || ''}|${i.deliver_address || ''}|${i.deliver_note || ''}`))]
  const mixedPlace = places.length > 1

  const supplier = suppliers.find(s => s.id === supplierId)
  const yen = n => (n || 0).toLocaleString('ja-JP')

  // 取引先によって発注の出し方が違う。
  // エジソン等は発注書のExcel＋メール、マレフィオーレはLINEに貼る文面
  const isLine = supplier?.order_method === 'text_line'

  const createOrder = async () => {
    if (!chosen.length) return
    setBusy(true); setErr('')
    try {
      const first = chosen[0]
      const r = await api.post('/wholesale/orders', {
        supplier_id: supplierId,
        order_date: orderDate,
        deliver_zip: first.deliver_zip,
        deliver_address: first.deliver_address,
        deliver_note: first.deliver_note,
        items: chosen.map(i => ({
          item_id: i.id, item_code: i.item_code, jan_code: i.jan_code,
          name: i.name, unit_price: i.unit_price, qty: qty[i.id], note: i.note,
        })),
      })
      if (isLine) {
        const m = await api.get(`/wholesale/orders/${r.data.id}/message`)
        setMessage({ order: m.data.order, text: m.data.text })
      } else {
        const p = await api.get(`/wholesale/orders/${r.data.id}/preview`)
        setPreview({ ...p.data, editing: { ...p.data.mail } })
      }
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  const openPreview = async (id) => {
    setBusy(true); setErr('')
    try {
      const p = await api.get(`/wholesale/orders/${id}/preview`)
      setPreview({ ...p.data, editing: { ...p.data.mail } })
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  const download = () => {
    const b = atob(preview.file.content_base64)
    const arr = new Uint8Array(b.length)
    for (let i = 0; i < b.length; i++) arr[i] = b.charCodeAt(i)
    const url = URL.createObjectURL(new Blob([arr], {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    }))
    const a = document.createElement('a')
    a.href = url; a.download = preview.file.name; a.click()
    setTimeout(() => URL.revokeObjectURL(url), 3000)
  }

  const send = async () => {
    const m = preview.editing
    if (!window.confirm(`${m.to} へ発注書を送信します。よろしいですか？`)) return
    setBusy(true); setErr('')
    try {
      await api.post(`/wholesale/orders/${preview.order.id}/send`, m)
      alert('送信しました')
      setPreview(null); setQty({})
      const r = await api.get(`/wholesale/orders?supplier_id=${supplierId}`)
      setOrders(r.data)
      setTab('history')
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }


  const reloadOrders = async () => {
    const r = await api.get(`/wholesale/orders?supplier_id=${supplierId}`)
    setOrders(r.data)
  }

  const openMessage = async (id) => {
    setBusy(true); setErr('')
    try {
      const m = await api.get(`/wholesale/orders/${id}/message`)
      setMessage({ order: m.data.order, text: m.data.text })
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  const confirmSent = async () => {
    setBusy(true); setErr('')
    try {
      await api.post(`/wholesale/orders/${message.order.id}/confirm`,
                     { text: message.text })
      setMessage(null); setQty({})
      await reloadOrders()
      setTab('history')
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  const openReceive = async (id) => {
    setBusy(true); setErr('')
    try {
      const r = await api.get(`/wholesale/orders/${id}`)
      setReceiving({
        order: r.data,
        mode: 'add_stock',
        // 届いた数は「残り」から始める。分納の2回目以降は、まだ来ていない
        // 数が既定になるので、届いた分だけ減らせばよい
        qty: Object.fromEntries(r.data.items.map(
          i => [i.id, Math.max(0, (i.qty || 0) - (i.received_qty || 0))])),
      })
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  const doReceive = async () => {
    const r = receiving
    setBusy(true); setErr('')
    try {
      const res = await api.post(`/wholesale/orders/${r.order.id}/receive`, {
        mode: r.mode,
        items: r.order.items.map(i => ({ item_id: i.id, received_qty: r.qty[i.id] || 0 })),
      })
      setReceiving(null)
      await reloadOrders()
      const un = res.data.unlinked || []
      // 三項演算子の優先順位で、追記が else 側だけに付いていた。
      // 紐付いていない商品の注意は、どちらの場合も出す
      const base = r.mode === 'add_stock'
        ? '入荷しました。実在庫に反映しています'
        : '入荷しました。発注済のみ消しています'
      alert(base + (un.length
        ? `\n\n※ 楽天と紐付いていない商品: ${un.join('、')}`
        : ''))
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  const undoReceive = async (id) => {
    if (!window.confirm('入荷を取り消します。在庫と発注済が元に戻ります。よろしいですか？')) return
    setBusy(true); setErr('')
    try {
      await api.post(`/wholesale/orders/${id}/undo-receive`, {})
      await reloadOrders()
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }


  return (
    <div style={{ padding: 20 }}>
      <h2 style={{ marginTop: 0 }}>🏭 卸発注（メーカー品）</h2>

      {err && (
        <div style={{ background: '#fef2f2', border: '1px solid #fecaca', color: '#991b1b',
          padding: 12, borderRadius: 6, marginBottom: 12 }}>
          {err}
        </div>
      )}

      {mailStatus && !mailStatus.configured && (
        <div style={{ background: '#fffbeb', border: '1px solid #fde68a', color: '#92400e',
          padding: 12, borderRadius: 6, marginBottom: 12 }}>
          メールの送信設定が入っていません。発注書は作れますが、送信はできません
          （Excelをダウンロードして手で送ることはできます）。
        </div>
      )}

      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        {[['order', '📝 発注する'], ['pending', '📥 入荷待ち'], ['history', '📋 発注履歴'], ['master', '⚙️ 商品・取引先']].map(([k, l]) => (
          <button key={k} onClick={() => setTab(k)}
            className={`btn ${tab === k ? 'btn-primary' : 'btn-secondary'}`}>{l}</button>
        ))}
      </div>

      <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 16 }}>
        <label>取引先</label>
        <select value={supplierId || ''} onChange={e => setSupplierId(Number(e.target.value))}
          style={{ padding: '6px 10px', minWidth: 220 }}>
          {suppliers.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        {tab === 'order' && (
          <>
            <label>発注日</label>
            <input type="date" value={orderDate}
              onChange={e => { setOrderDate(e.target.value); setDateTouched(true) }}
              style={{ padding: '6px 10px' }} />
            {dateTouched && orderDate !== today() && (
              <button className="btn btn-secondary" style={{ fontSize: 12, padding: '4px 10px' }}
                onClick={() => { setOrderDate(today()); setDateTouched(false) }}>
                今日に戻す
              </button>
            )}
          </>
        )}
      </div>

      {tab === 'order' && (
        <>
          {/* 商品名のあとに空の列を置いて余白を吸わせる。こうしないと
              商品名が横いっぱいに広がり、在庫や発注数が右端まで離れる */}
          <table className="table" style={{ width: '100%', background: '#fff' }}>
            <thead>
              <tr style={{ background: '#f8fafc' }}>
                <th style={{ textAlign: 'left', whiteSpace: 'nowrap' }}>商品名</th>
                {!isLine && <th style={{ width: 130 }}>JAN</th>}
                <th style={{ width: 'auto' }} />
                <th style={{ textAlign: 'right', width: 90, color: '#64748b' }}>単価(税抜)</th>
                <th style={{ textAlign: 'right', width: 70, borderLeft: '1px solid #e2e8f0' }}>在庫</th>
                <th style={{ textAlign: 'right', width: 70, color: '#2563eb' }}>発注1</th>
                <th style={{ textAlign: 'right', width: 70, color: '#2563eb' }}>発注2</th>
                <th style={{ textAlign: 'right', width: 100 }}>発注数</th>
                <th style={{ textAlign: 'right', width: 100, color: '#0f766e' }}>金額</th>
                {!isLine && <th style={{ textAlign: 'left', width: 200 }}>納品先</th>}
              </tr>
            </thead>
            <tbody>
              {items.map(i => {
                const q = qty[i.id] || 0
                return (
                  <tr key={i.id} style={{ background: q > 0 ? '#eff6ff' : undefined }}>
                    <td style={{ whiteSpace: 'nowrap' }}>{i.name}</td>
                    {!isLine && <td style={{ fontSize: 12, color: '#64748b' }}>{i.jan_code || '—'}</td>}
                    <td />
                    {/* 数字が横に並ぶので、意味ごとに色を変えて見分けられるようにする。
                        お金＝灰、在庫＝黒（切れていたら赤）、これから来る数＝青 */}
                    <td style={{ textAlign: 'right', color: '#64748b' }}>
                      {i.unit_price ? yen(i.unit_price) : '—'}
                    </td>
                    <td style={{ textAlign: 'right', fontWeight: 600,
                      color: i.stock ? '#0f172a' : '#dc2626',
                      borderLeft: '1px solid #e2e8f0' }}>
                      {i.stock ?? '—'}
                    </td>
                    <td style={{ textAlign: 'right', color: '#2563eb' }}>{i.inbound || ''}</td>
                    <td style={{ textAlign: 'right', color: '#2563eb' }}>{i.standard_stock || ''}</td>
                    <td style={{ textAlign: 'right' }}>
                      <input type="number" min="0" value={q || ''}
                        onChange={e => setQty({ ...qty, [i.id]: Number(e.target.value) || 0 })}
                        style={{ width: '100%', padding: '4px 6px', textAlign: 'right' }} />
                    </td>
                    <td style={{ textAlign: 'right', fontWeight: 600, color: '#0f766e' }}>
                      {q > 0 && i.unit_price ? yen(i.unit_price * q) : ''}
                    </td>
                    {!isLine && (
                      <td style={{ fontSize: 12, color: '#64748b' }}>
                        {i.deliver_note || i.deliver_address || '—'}
                      </td>
                    )}
                  </tr>
                )
              })}
            </tbody>
          </table>

          {mixedPlace && !isLine && (
            <div style={{ background: '#fffbeb', border: '1px solid #fde68a', color: '#92400e',
              padding: 12, borderRadius: 6, marginTop: 12 }}>
              納品先が違う商品が混ざっています。1枚の発注書には1つの納品先しか書けないので、
              分けて発注してください。
            </div>
          )}

          <div style={{ marginTop: 16, display: 'flex', justifyContent: 'flex-end',
            alignItems: 'center', gap: 20 }}>
            <div style={{ color: '#64748b', fontSize: 13 }}>
              {chosen.length} 品目 / {chosen.reduce((a, i) => a + (qty[i.id] || 0), 0)} 個
            </div>
            {/* 金額はどの取引先でも出す。届いた請求書と突き合わせるため */}
            <div style={{ textAlign: 'right', fontSize: 14 }}>
              <div>小計 <b>{yen(subtotal)}</b> 円</div>
              <div style={{ color: '#64748b' }}>消費税 {yen(Math.floor(tax))} 円</div>
              <div style={{ fontSize: 18 }}>合計 <b>{yen(total)}</b> 円（税込）</div>
            </div>
            <button className="btn btn-primary"
              disabled={!chosen.length || (!isLine && mixedPlace) || busy}
              onClick={createOrder} style={{ padding: '10px 24px' }}>
              {isLine ? '発注の文面を作る' : '発注書を作る'}
            </button>
          </div>
        </>
      )}

      {tab === 'pending' && (
        <PendingReceive supplierId={supplierId} onDone={() => { load(); setTab('pending') }} />
      )}

      {tab === 'history' && (
        <table className="table" style={{ width: '100%', background: '#fff' }}>
          <thead>
            <tr style={{ background: '#f8fafc' }}>
              <th>発注日</th><th style={{ textAlign: 'right' }}>合計</th>
              <th>状態</th><th>入荷</th><th>送信先</th><th></th>
            </tr>
          </thead>
          <tbody>
            {orders.map(o => (
              <tr key={o.id}>
                <td>{o.order_date}</td>
                <td style={{ textAlign: 'right' }}>{yen(o.total)} 円</td>
                <td>
                  {o.status === 'sent' && <span style={{ color: '#16a34a' }}>送信済</span>}
                  {o.status === 'draft' && <span style={{ color: '#64748b' }}>未送信</span>}
                  {o.status === 'failed' && <span style={{ color: '#dc2626' }}>失敗</span>}
                </td>
                <td style={{ fontSize: 12 }}>
                  {o.received_at
                    ? <span style={{ color: '#16a34a' }}>
                        入荷済{o.received_mode === 'clear_only' ? '（発注済のみ）' : ''}
                      </span>
                    : o.receive_status === 'partial'
                      ? <span style={{ color: '#b45309', fontWeight: 700 }}>
                          一部入荷（残り{o.remaining_qty}個）
                        </span>
                      : <span style={{ color: '#94a3b8' }}>—</span>}
                </td>
                <td style={{ fontSize: 12 }}>{o.sent_to || '—'}</td>
                <td style={{ whiteSpace: 'nowrap' }}>
                  <button className="btn btn-secondary"
                    onClick={() => (isLine ? openMessage(o.id) : openPreview(o.id))}>
                    {o.status === 'sent' ? '中身を見る' : (isLine ? '文面を見る' : '確認して送る')}
                  </button>
                  {!o.received_at && (
                    <button className="btn btn-primary" style={{ marginLeft: 6 }}
                      onClick={() => openReceive(o.id)}>
                      {o.receive_status === 'partial' ? '続けて入荷' : '入荷'}
                    </button>
                  )}
                  {(o.received_at || o.receive_status === 'partial') && (
                    <button className="btn btn-secondary" style={{ marginLeft: 6 }}
                      onClick={() => undoReceive(o.id)}>入荷を取消</button>
                  )}
                </td>
              </tr>
            ))}
            {!orders.length && (
              <tr><td colSpan="6" style={{ textAlign: 'center', color: '#94a3b8', padding: 24 }}>
                まだ発注がありません
              </td></tr>
            )}
          </tbody>
        </table>
      )}

      {tab === 'master' && (
        <WholesaleMaster suppliers={suppliers} supplierId={supplierId}
          items={items} onChanged={() => { load(); setSupplierId(supplierId) }} />
      )}

      {message && (
        <MessageDialog m={message} busy={busy}
          onChange={t => setMessage({ ...message, text: t })}
          onConfirm={confirmSent} onClose={() => setMessage(null)} />
      )}

      {receiving && (
        <ReceiveDialog r={receiving} busy={busy}
          onChange={setReceiving} onReceive={doReceive}
          onClose={() => setReceiving(null)} />
      )}

      {preview && (
        <PreviewDialog p={preview} supplier={supplier} busy={busy}
          onChange={m => setPreview({ ...preview, editing: m })}
          onDownload={download} onSend={send} onClose={() => setPreview(null)} />
      )}
    </div>
  )
}

/** 送信前の確認。ここで見た内容がそのまま送られる。 */
function PreviewDialog({ p, supplier, busy, onChange, onDownload, onSend, onClose }) {
  const m = p.editing
  const sent = p.order.status === 'sent'
  const yen = n => (n || 0).toLocaleString('ja-JP')

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.5)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}
      onClick={onClose}>
      <div onClick={e => e.stopPropagation()} style={{ background: '#fff', borderRadius: 10,
        width: 'min(860px, 94vw)', maxHeight: '92vh', overflow: 'auto', padding: 24 }}>
        <h3 style={{ marginTop: 0 }}>
          {sent ? '送信済みの発注書' : 'この内容で送信します'}
        </h3>

        <div style={{ background: '#f8fafc', padding: 14, borderRadius: 6, marginBottom: 16 }}>
          <div style={{ fontSize: 13, color: '#64748b', marginBottom: 6 }}>発注書</div>
          <div><b>{supplier?.name}　{supplier?.honorific}</b>　/　{p.order.order_date}</div>
          <table style={{ width: '100%', marginTop: 10, fontSize: 13 }}>
            <tbody>
              {p.order.items?.map(i => (
                <tr key={i.id}>
                  <td>{i.name}</td>
                  <td style={{ textAlign: 'right', width: 90 }}>{yen(i.unit_price)} 円</td>
                  <td style={{ textAlign: 'right', width: 70 }}>{i.qty} 個</td>
                  <td style={{ textAlign: 'right', width: 100 }}>{yen(i.amount)} 円</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ textAlign: 'right', marginTop: 8, fontSize: 15 }}>
            合計 <b>{yen(p.order.total)}</b> 円（税込）
          </div>
          {p.order.deliver_note && (
            <div style={{ marginTop: 8, fontSize: 13, color: '#92400e' }}>
              納品先: {p.order.deliver_note}
            </div>
          )}
        </div>

        <div style={{ display: 'grid', gap: 10 }}>
          <label style={{ fontSize: 13 }}>宛先
            <input value={m.to || ''} disabled={sent}
              onChange={e => onChange({ ...m, to: e.target.value })}
              style={{ width: '100%', padding: 8, marginTop: 4 }} />
          </label>
          <label style={{ fontSize: 13 }}>Cc
            <input value={m.cc || ''} disabled={sent}
              onChange={e => onChange({ ...m, cc: e.target.value })}
              style={{ width: '100%', padding: 8, marginTop: 4 }} />
          </label>
          <label style={{ fontSize: 13 }}>件名
            <input value={m.subject || ''} disabled={sent}
              onChange={e => onChange({ ...m, subject: e.target.value })}
              style={{ width: '100%', padding: 8, marginTop: 4 }} />
          </label>
          <label style={{ fontSize: 13 }}>本文
            <textarea value={m.body || ''} disabled={sent} rows={12}
              onChange={e => onChange({ ...m, body: e.target.value })}
              style={{ width: '100%', padding: 8, marginTop: 4, fontFamily: 'inherit' }} />
          </label>
        </div>

        <div style={{ marginTop: 12, fontSize: 13, color: '#64748b' }}>
          添付: {p.file.name}（{Math.round(p.file.size / 1024)} KB）
        </div>

        <div style={{ display: 'flex', gap: 10, marginTop: 20, justifyContent: 'flex-end' }}>
          <button className="btn btn-secondary" onClick={onClose}>閉じる</button>
          <button className="btn btn-secondary" onClick={onDownload}>Excelを保存</button>
          {!sent && (
            <button className="btn btn-primary" onClick={onSend}
              disabled={busy || !p.mail_configured}
              style={{ padding: '10px 28px' }}>
              {busy ? '送信中…' : '送信する'}
            </button>
          )}
        </div>
        {!sent && !p.mail_configured && (
          <div style={{ textAlign: 'right', fontSize: 12, color: '#92400e', marginTop: 6 }}>
            メール設定が未登録のため送信できません。Excelを保存して手で送ってください。
          </div>
        )}
      </div>
    </div>
  )
}

/** 商品と取引先の登録。 */
function WholesaleMaster({ suppliers, supplierId, items, onChanged }) {
  const [edit, setEdit] = useState(null)
  const yen = n => (n || 0).toLocaleString('ja-JP')

  const save = async (it) => {
    try {
      if (it.id) await api.put(`/wholesale/items/${it.id}`, it)
      else await api.post('/wholesale/items', { ...it, supplier_id: supplierId })
      setEdit(null); onChanged()
    } catch (e) {
      alert(e.response?.data?.detail || e.message)
    }
  }

  return (
    <div>
      <div style={{ marginBottom: 12 }}>
        <button className="btn btn-primary"
          onClick={() => setEdit({ name: '', unit_price: 0, supplier_id: supplierId, is_active: true })}>
          ＋ 商品を追加
        </button>
      </div>
      <table className="table" style={{ width: '100%', background: '#fff' }}>
        <thead>
          <tr style={{ background: '#f8fafc' }}>
            <th style={{ textAlign: 'left' }}>商品名</th><th>JAN</th>
            <th style={{ textAlign: 'right' }}>単価(税抜)</th>
            <th style={{ textAlign: 'left' }}>納品先</th><th></th>
          </tr>
        </thead>
        <tbody>
          {items.map(i => (
            <tr key={i.id}>
              <td>{i.name}</td>
              <td style={{ fontSize: 12, color: '#64748b' }}>{i.jan_code || '—'}</td>
              <td style={{ textAlign: 'right' }}>{yen(i.unit_price)}</td>
              <td style={{ fontSize: 12 }}>{i.deliver_note || i.deliver_address || '—'}</td>
              <td><button className="btn btn-secondary" onClick={() => setEdit(i)}>編集</button></td>
            </tr>
          ))}
        </tbody>
      </table>

      {edit && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.5)', zIndex: 1000,
          display: 'flex', alignItems: 'center', justifyContent: 'center' }}
          onClick={() => setEdit(null)}>
          <div onClick={e => e.stopPropagation()} style={{ background: '#fff', padding: 24,
            borderRadius: 10, width: 'min(560px, 94vw)' }}>
            <h3 style={{ marginTop: 0 }}>{edit.id ? '商品を編集' : '商品を追加'}</h3>
            <div style={{ display: 'grid', gap: 10 }}>
              {[
                ['name', '商品名（発注書に出る名前）'],
                ['jan_code', 'JANコード'],
                ['item_code', '商品番号'],
                ['deliver_zip', '納品先の郵便番号'],
                ['deliver_address', '納品先の住所'],
                ['deliver_note', '納品先の宛名（C9欄）'],
                ['note', '備考'],
              ].map(([k, label]) => (
                <label key={k} style={{ fontSize: 13 }}>{label}
                  <input value={edit[k] || ''} onChange={e => setEdit({ ...edit, [k]: e.target.value })}
                    style={{ width: '100%', padding: 8, marginTop: 4 }} />
                </label>
              ))}
              <label style={{ fontSize: 13 }}>単価（税抜）
                <input type="number" value={edit.unit_price || 0}
                  onChange={e => setEdit({ ...edit, unit_price: Number(e.target.value) })}
                  style={{ width: '100%', padding: 8, marginTop: 4 }} />
              </label>
            </div>
            <div style={{ display: 'flex', gap: 10, marginTop: 18, justifyContent: 'flex-end' }}>
              <button className="btn btn-secondary" onClick={() => setEdit(null)}>やめる</button>
              <button className="btn btn-primary" onClick={() => save(edit)}>保存</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

/**
 * 入荷待ち一覧。
 *
 * 分納が続くと発注を1件ずつ開くのが手間なので、まだ届いていない明細を
 * 発注をまたいで並べ、届いた分だけ入力してまとめて処理する。
 */
function PendingReceive({ supplierId, onDone }) {
  const [rows, setRows] = useState([])
  const [qty, setQty] = useState({})
  const [mode, setMode] = useState('add_stock')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')

  const load = async () => {
    setBusy(true); setErr('')
    try {
      const q = supplierId ? `?supplier_id=${supplierId}` : ''
      const r = await api.get(`/wholesale/pending-items${q}`)
      setRows(r.data || [])
      setQty({})
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }
  useEffect(() => { load() }, [supplierId])

  const keyOf = (r) => (r.source === 'manual' ? `p${r.product_id}` : `r${r.row_id}`)
  const entered = rows.reduce((a, r) => a + (qty[keyOf(r)] || 0), 0)

  const receive = async () => {
    const items = rows
      .filter(r => (qty[keyOf(r)] || 0) > 0)
      .map(r => (r.source === 'manual'
        ? { product_id: r.product_id, received_qty: qty[keyOf(r)] }
        : { row_id: r.row_id, received_qty: qty[keyOf(r)] }))
    if (!items.length) return
    const lines = rows.filter(r => (qty[keyOf(r)] || 0) > 0)
      .map(r => `・${r.name} ${qty[keyOf(r)]}個`).join('\n')
    const body = '\n' + lines + '\n';
    if (!window.confirm('次の内容で入荷します。' + body + 'よろしいですか？')) return
    setBusy(true); setErr(''); setMsg('')
    try {
      const r = await api.post('/wholesale/receive-items', { mode, items })
      const n = (r.data.changed || []).length
      const done = (r.data.completed_orders || []).length
      const pro = r.data.promoted || []
      const proText = pro.length
        ? `／発注済1が空になった${pro.length}件は発注済2を繰り上げました（${pro.map(x => x.sku).join(', ')}）`
        : ''
      setMsg(`${n}件を入荷しました${done ? `（${done}件の発注が完了）` : ''}${proText}`)
      await load()
      onDone?.()
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  const fillAll = () => setQty(Object.fromEntries(rows.map(r => [keyOf(r), r.remaining_qty])))

  return (
    <div>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 12, flexWrap: 'wrap' }}>
        <button className="btn btn-secondary" onClick={load} disabled={busy}>更新</button>
        <button className="btn btn-secondary" onClick={fillAll} disabled={busy || !rows.length}>
          全部「残り」を入れる
        </button>
        <button className="btn btn-secondary" onClick={() => setQty({})} disabled={busy}>入力をクリア</button>
        <span style={{ fontSize: 13, color: '#64748b' }}>未入荷 {rows.length} 明細</span>
      </div>

      {err && <div style={{ color: '#dc2626', fontSize: 13, marginBottom: 10 }}>{err}</div>}
      {msg && <div style={{ color: '#16a34a', fontSize: 13, marginBottom: 10 }}>{msg}</div>}

      {!rows.length && !busy && (
        <div style={{ padding: 20, background: '#f8fafc', borderRadius: 8, color: '#64748b', fontSize: 13 }}>
          入荷待ちの明細はありません。
        </div>
      )}

      {!!rows.length && (
        <>
          <table style={{ width: '100%', fontSize: 14, marginBottom: 16 }}>
            <thead>
              <tr style={{ background: '#f8fafc' }}>
                <th style={{ textAlign: 'left', padding: 8 }}>発注日</th>
                <th style={{ textAlign: 'left', padding: 8 }}>商品名</th>
                <th style={{ textAlign: 'right', padding: 8 }}>発注数</th>
                <th style={{ textAlign: 'right', padding: 8 }}>入荷済</th>
                <th style={{ textAlign: 'right', padding: 8 }}>残り</th>
                <th style={{ textAlign: 'right', padding: 8, width: 130 }}>今回届いた数</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(r => (
                <tr key={keyOf(r)} style={{ borderTop: '1px solid #f1f5f9' }}>
                  <td style={{ padding: 8, whiteSpace: 'nowrap', color: '#64748b', fontSize: 12 }}>
                    {r.source === 'manual'
                      ? <span style={{ padding: '1px 6px', borderRadius: 3, background: '#f1f5f9', color: '#475569' }}>手動発注</span>
                      : r.order_date}
                  </td>
                  <td style={{ padding: 8 }}>{r.name}</td>
                  <td style={{ padding: 8, textAlign: 'right', color: '#64748b' }}>{r.source === 'manual' ? '—' : r.qty}</td>
                  <td style={{ padding: 8, textAlign: 'right', color: '#64748b' }}>{r.source === 'manual' ? '—' : r.received_qty}</td>
                  <td style={{ padding: 8, textAlign: 'right', fontWeight: 700, color: '#b45309' }}>{r.remaining_qty}</td>
                  <td style={{ padding: 8, textAlign: 'right' }}>
                    <input type="number" min="0" max={r.remaining_qty}
                      value={qty[keyOf(r)] ?? ''} placeholder="0"
                      onChange={e => {
                        const v = Math.max(0, Math.min(r.remaining_qty, Number(e.target.value) || 0))
                        setQty(q => ({ ...q, [keyOf(r)]: v }))
                      }}
                      style={{ width: 110, padding: '5px 6px', textAlign: 'right' }} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <div style={{ display: 'grid', gap: 10, marginBottom: 16 }}>
            {[
              ['add_stock', '実在庫に足す', 'ふつうの入荷。届いた数を在庫へ加算し、発注済から減らします'],
              ['clear_only', '発注済を消すだけ', 'すでに在庫へ入れてある場合。在庫は動かさず、発注済だけ減らします'],
            ].map(([k, label, desc]) => (
              <label key={k} style={{ display: 'flex', gap: 10, alignItems: 'flex-start',
                padding: 12, borderRadius: 6, cursor: 'pointer',
                border: mode === k ? '2px solid #2563eb' : '1px solid #e5e7eb',
                background: mode === k ? '#eff6ff' : '#fff' }}>
                <input type="radio" checked={mode === k} style={{ marginTop: 3 }}
                  onChange={() => setMode(k)} />
                <div>
                  <div style={{ fontWeight: 600 }}>{label}</div>
                  <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>{desc}</div>
                </div>
              </label>
            ))}
          </div>

          <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
            <button className="btn btn-primary" disabled={busy || !entered}
              onClick={receive} style={{ padding: '10px 28px' }}>
              {busy ? '処理中…' : `入荷する（計 ${entered} 個）`}
            </button>
            <span style={{ fontSize: 12, color: '#64748b' }}>
              入力した明細だけを処理します。全部届いた発注は自動で「入荷済」になります。
            </span>
          </div>
        </>
      )}
    </div>
  )
}

/**
 * 入荷。
 *
 * 在庫に足すか、発注済を消すだけかを選べる。届く前に在庫へ
 * 入れてしまっていることがあり、そのまま足すと二重になるため。
 */
function ReceiveDialog({ r, busy, onChange, onReceive, onClose }) {
  const o = r.order
  const yen = n => (n || 0).toLocaleString('ja-JP')
  const totalQty = o.items.reduce((a, i) => a + (r.qty[i.id] || 0), 0)

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.5)', zIndex: 1000,
      display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={onClose}>
      <div onClick={e => e.stopPropagation()} style={{ background: '#fff', borderRadius: 10,
        width: 'min(680px, 94vw)', maxHeight: '92vh', overflow: 'auto', padding: 24 }}>
        <h3 style={{ marginTop: 0 }}>入荷処理</h3>
        <div style={{ color: '#64748b', fontSize: 13, marginBottom: 16 }}>
          {o.supplier_name}　/　{o.order_date} の発注（{yen(o.total)} 円）
        </div>

        <table style={{ width: '100%', fontSize: 14, marginBottom: 16 }}>
          <thead>
            <tr style={{ background: '#f8fafc' }}>
              <th style={{ textAlign: 'left', padding: 6 }}>商品名</th>
              <th style={{ textAlign: 'right', padding: 6 }}>発注数</th>
              <th style={{ textAlign: 'right', padding: 6 }}>入荷済</th>
              <th style={{ textAlign: 'right', padding: 6 }}>残り</th>
              <th style={{ textAlign: 'right', padding: 6, width: 120 }}>今回届いた数</th>
            </tr>
          </thead>
          <tbody>
            {o.items.map(i => (
              <tr key={i.id}>
                <td style={{ padding: 6 }}>{i.name}</td>
                <td style={{ textAlign: 'right', padding: 6, color: '#64748b' }}>{i.qty}</td>
                <td style={{ textAlign: 'right', padding: 6, color: '#64748b' }}>{i.received_qty || 0}</td>
                <td style={{ textAlign: 'right', padding: 6, fontWeight: 600,
                  color: (i.qty || 0) - (i.received_qty || 0) > 0 ? '#b45309' : '#16a34a' }}>
                  {Math.max(0, (i.qty || 0) - (i.received_qty || 0))}
                </td>
                <td style={{ textAlign: 'right', padding: 6 }}>
                  <input type="number" min="0" value={r.qty[i.id] ?? 0}
                    onChange={e => onChange({ ...r,
                      qty: { ...r.qty, [i.id]: Number(e.target.value) || 0 } })}
                    style={{ width: 100, padding: '4px 6px', textAlign: 'right' }} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <div style={{ display: 'grid', gap: 10, marginBottom: 16 }}>
          {[
            ['add_stock', '実在庫に足す',
             'ふつうの入荷。届いた数を在庫へ加算し、発注済から減らします'],
            ['clear_only', '発注済を消すだけ',
             'すでに在庫へ入れてある場合。在庫は動かさず、発注済だけ減らします'],
          ].map(([k, label, desc]) => (
            <label key={k} style={{ display: 'flex', gap: 10, alignItems: 'flex-start',
              padding: 12, borderRadius: 6, cursor: 'pointer',
              border: r.mode === k ? '2px solid #2563eb' : '1px solid #e5e7eb',
              background: r.mode === k ? '#eff6ff' : '#fff' }}>
              <input type="radio" checked={r.mode === k} style={{ marginTop: 3 }}
                onChange={() => onChange({ ...r, mode: k })} />
              <div>
                <div style={{ fontWeight: 600 }}>{label}</div>
                <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>{desc}</div>
              </div>
            </label>
          ))}
        </div>

        <div style={{ fontSize: 13, color: '#64748b' }}>
          合計 {totalQty} 個を入荷します
        </div>
        <div style={{ fontSize: 12, color: '#64748b', marginTop: 6 }}>
          分納のときは、今回届いた数だけ入れてください。残りがある間は
          「一部入荷」として残るので、次に届いたらまた入荷できます。
        </div>

        <div style={{ display: 'flex', gap: 10, marginTop: 20, justifyContent: 'flex-end' }}>
          <button className="btn btn-secondary" onClick={onClose}>やめる</button>
          <button className="btn btn-primary" onClick={onReceive} disabled={busy || !totalQty}
            style={{ padding: '10px 28px' }}>
            {busy ? '処理中…' : '入荷する'}
          </button>
        </div>
      </div>
    </div>
  )
}

/**
 * LINEに貼る発注の文面。
 *
 * 送るのは人なので、コピーして貼ってもらい、送ったら「送信済にする」を
 * 押してもらう。押した時点で発注済に反映する。
 */
function MessageDialog({ m, busy, onChange, onConfirm, onClose }) {
  const [copied, setCopied] = useState(false)
  const sent = m.order.status === 'sent'

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(m.text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // クリップボードが使えない環境では、選択してもらう
      const ta = document.getElementById('ws-msg')
      if (ta) { ta.select() }
    }
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.5)', zIndex: 1000,
      display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={onClose}>
      <div onClick={e => e.stopPropagation()} style={{ background: '#fff', borderRadius: 10,
        width: 'min(620px, 94vw)', maxHeight: '92vh', overflow: 'auto', padding: 24 }}>
        <h3 style={{ marginTop: 0 }}>
          {sent ? '送信済みの発注' : 'LINEで送る文面'}
        </h3>
        <div style={{ color: '#64748b', fontSize: 13, marginBottom: 14 }}>
          {sent
            ? `${m.order.order_date} に送信しました`
            : 'コピーしてLINEに貼り付けてください。送ったら下のボタンを押します'}
        </div>

        <textarea id="ws-msg" value={m.text} readOnly={sent} rows={Math.min(16, m.text.split('\n').length + 2)}
          onChange={e => onChange(e.target.value)}
          style={{ width: '100%', padding: 12, fontFamily: 'inherit', fontSize: 14,
            lineHeight: 1.7, border: '1px solid #e5e7eb', borderRadius: 6 }} />

        <div style={{ fontSize: 12, color: '#64748b', marginTop: 8 }}>
          発注済がある商品は「追加◯◯（計◯◯）」と書いています。文面はここで直せます。
        </div>

        {/* 金額は文面には入れない。あとで届く請求書と突き合わせるための控え */}
        {m.order.total > 0 && (
          <div style={{ marginTop: 14, padding: 12, background: '#f8fafc',
            borderRadius: 6, fontSize: 13 }}>
            <div style={{ color: '#64748b', marginBottom: 6 }}>
              金額の控え（LINEには入りません）
            </div>
            <table style={{ width: '100%', fontSize: 13 }}>
              <tbody>
                {m.order.items?.filter(i => i.unit_price).map(i => (
                  <tr key={i.id}>
                    <td>{i.name}</td>
                    <td style={{ textAlign: 'right', width: 80 }}>
                      {(i.unit_price || 0).toLocaleString('ja-JP')} 円
                    </td>
                    <td style={{ textAlign: 'right', width: 60 }}>{i.qty} 個</td>
                    <td style={{ textAlign: 'right', width: 90 }}>
                      {(i.amount || 0).toLocaleString('ja-JP')} 円
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div style={{ textAlign: 'right', marginTop: 8,
              borderTop: '1px solid #e5e7eb', paddingTop: 8 }}>
              <div>小計 {(m.order.subtotal || 0).toLocaleString('ja-JP')} 円</div>
              <div style={{ color: '#64748b' }}>
                消費税 {Math.floor(m.order.tax || 0).toLocaleString('ja-JP')} 円
              </div>
              <div style={{ fontSize: 15 }}>
                合計 <b>{(m.order.total || 0).toLocaleString('ja-JP')}</b> 円（税込）
              </div>
            </div>
          </div>
        )}

        <div style={{ display: 'flex', gap: 10, marginTop: 20, justifyContent: 'flex-end' }}>
          <button className="btn btn-secondary" onClick={onClose}>閉じる</button>
          <button className="btn btn-secondary" onClick={copy}>
            {copied ? '✓ コピーしました' : '文面をコピー'}
          </button>
          {!sent && (
            <button className="btn btn-primary" onClick={onConfirm} disabled={busy}
              style={{ padding: '10px 24px' }}>
              {busy ? '処理中…' : '送信済にする'}
            </button>
          )}
        </div>
        {!sent && (
          <div style={{ textAlign: 'right', fontSize: 12, color: '#64748b', marginTop: 6 }}>
            押すと発注済に反映されます
          </div>
        )}
      </div>
    </div>
  )
}
