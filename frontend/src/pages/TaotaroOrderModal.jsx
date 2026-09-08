import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import api from '../api/client'

/**
 * タオタロウへ直接発注する確認画面。
 *
 * これまではExcelを作って管理画面へ手で上げていた。APIで直接発注できる
 * ようになったが、「どの色・どのサイズを買うか」を機械が決めることになる。
 * 違う色が届いても取り返しがつかないので、送る前に必ずここで目視する。
 *
 * ・一度確かめた組み合わせは商品マスタに覚え、次から自動で入る
 * ・決められなかったものはプルダウンで選ぶまで送らない
 * ・検品オプションは注文作成時にしか指定できないため、ここで確定させる
 */

const C = {
  line: '#e5e7eb', sub: '#64748b', text: '#0f172a',
  good: '#16a34a', warn: '#b45309', bad: '#dc2626', key: '#2563eb',
}

// アプリ共通のCSSが input, select, textarea に width:100% を当てている。
// チェックボックスがそのままだと行いっぱいに広がって本文を潰すので、
// この画面のチェックボックスだけ幅を戻す
const check = { width: 'auto', flex: '0 0 auto', margin: 0 }

// 仕様書「検品オプション」より。var8/9/11/12 は使わない
const INSPECT = [
  ['var1', 'アパレル検品'],
  ['var10', '全量開封検品'],
  ['var2', 'OPP袋交換'],
  ['var3', '織ネーム取り外し'],
  ['var4', '織ネーム縫い付け'],
  ['var5', '下げ札取り付け'],
  ['var6', '下げ札取り外し'],
]

export default function TaotaroOrderModal({
  items, onClose, onDone,
  // 叩く先。楽天とAmazonで置き場所が違うだけで、中身も画面も同じ
  previewUrl = '/taotaro/order-preview',
  submitUrl = '/taotaro/order-submit',
}) {
  const [rows, setRows] = useState(null)
  const [busy, setBusy] = useState(true)
  const [err, setErr] = useState('')
  const [sending, setSending] = useState(false)
  const [result, setResult] = useState(null)

  // 開いたらすぐ下調べ。価格と在庫はキャッシュされるので、
  // 発注の直前に取り直すよう仕様書で勧められている
  useEffect(() => {
    let alive = true
    const run = async () => {
      try {
        const r = await api.post(previewUrl, {
          items: items.map(it => ({
            sku: it.sku, qty: it.qty, buy_url: it.buy_url || '',
            name: it.name || '', color: it.color || '',
            size: it.size || '', spec: it.spec || '',
          })),
        })
        if (!alive) return
        setRows(r.data.items.map(x => ({
          ...x,
          skuId: (x.chosen && x.chosen.sku_id) || '',
          remark: '',
          inspect: x.inspect || {},
          rememberInspect: false,
          send: x.ok,
        })))
      } catch (e) {
        if (alive) setErr(e.response?.data?.detail || e.message)
      } finally {
        if (alive) setBusy(false)
      }
    }
    run()
    return () => { alive = false }
  }, [items, previewUrl])

  const patch = (i, v) => setRows(rs => rs.map((r, n) => n === i ? { ...r, ...v } : r))

  // SKUを選び直したら、在庫と最小発注数をその場で見直す
  const pickSku = (i, skuId) => {
    setRows(rs => rs.map((r, n) => {
      if (n !== i) return r
      const s = (r.skus || []).find(x => x.sku_id === skuId)
      let bad = ''
      if (!s) bad = '選んでください'
      else if (r.qty < (r.min_order_quantity || 1)) bad = `最小発注数 ${r.min_order_quantity} を下回っています`
      else if (s.stock != null && r.qty > s.stock) bad = `在庫 ${s.stock} 個を超えています`
      return { ...r, skuId, chosen: s || null, error: bad, ok: !bad, send: !bad }
    }))
  }

  const targets = (rows || []).filter(r => r.send && r.ok && r.skuId)

  const submit = async () => {
    if (!targets.length) return
    const names = targets.map(r => `${r.sku} ×${r.qty}`).join('\n')
    if (!confirm(`タオタロウへ発注します。取り消しは買付開始前しかできません。\n\n${names}\n\nよろしいですか？`)) return
    setSending(true); setErr('')
    try {
      const r = await api.post(submitUrl, {
        items: targets.map(t => ({
          sku: t.sku, qty: t.qty, buy_url: t.buy_url,
          title: t.title || t.name, platform: t.platform,
          product_id: t.product_id, sku_id: t.skuId,
          remark: t.remark || '',
          asin: t.asin || '', fnsku: t.fnsku || '',
          fba: t.asin ? 1 : 0,
          inspect: t.inspect || {},
          remember_sku: true,
          remember_inspect: !!t.rememberInspect,
        })),
      })
      setResult(r.data)
      if (onDone) onDone(targets.map(t => ({ sku: t.sku, qty: t.qty })))
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally {
      setSending(false)
    }
  }

  return createPortal((
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(15,23,42,.45)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: 20, zIndex: 50,
    }} onClick={e => { if (e.target === e.currentTarget && !sending) onClose() }}>
      <div style={{
        background: '#fff', borderRadius: 10, width: 'min(1000px, 100%)',
        maxHeight: '90vh', display: 'flex', flexDirection: 'column',
      }}>
        <div style={{ padding: '14px 18px', borderBottom: `1px solid ${C.line}` }}>
          <b style={{ fontSize: 15, color: C.text }}>🛒 タオタロウへ発注</b>
          <span style={{ fontSize: 12, color: C.sub, marginLeft: 10 }}>
            送る前に、色・サイズが合っているか確かめてください
          </span>
        </div>

        <div style={{ padding: 16, overflow: 'auto', flex: 1 }}>
          {err && <Err text={err} />}
          {busy && <div style={{ color: C.sub, fontSize: 13 }}>
            商品情報を取り直しています…（価格と在庫は発注直前に確認します）
          </div>}

          {result && (
            <div style={{
              background: '#f0fdf4', border: '1px solid #bbf7d0', color: '#166534',
              padding: 12, borderRadius: 6, fontSize: 13, lineHeight: 1.7,
            }}>
              <b>{result.ordered}件を発注しました。</b><br />
              {result.oids && result.oids.length
                ? <>注文ID: {result.oids.join(', ')}</>
                : <>注文IDは応答に含まれませんでした。タオタロウの管理画面か、
                    管理番号（自社SKU）での検索で確認できます。</>}
              <br />発注済みリストにも記録しました。
            </div>
          )}

          {!busy && !result && rows && rows.map((r, i) => (
            <Row key={r.sku} r={r} i={i} patch={patch} pickSku={pickSku} />
          ))}
        </div>

        <div style={{
          padding: '12px 18px', borderTop: `1px solid ${C.line}`,
          display: 'flex', alignItems: 'center', gap: 12,
        }}>
          {!result && (
            <span style={{ fontSize: 12, color: C.sub }}>
              発注する {targets.length} 件
              {rows && rows.length - targets.length > 0 &&
                ` ／ 送らない ${rows.length - targets.length} 件`}
            </span>
          )}
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
            <button className="btn btn-secondary" onClick={onClose} disabled={sending}>
              {result ? '閉じる' : 'やめる'}
            </button>
            {!result && (
              <button className="btn btn-primary" onClick={submit}
                disabled={sending || busy || !targets.length}>
                {sending ? '送っています…' : `この ${targets.length} 件を発注する`}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  ), document.body)
}

function Err({ text }) {
  return (
    <div style={{
      background: '#fef2f2', border: '1px solid #fecaca', color: '#991b1b',
      padding: 10, borderRadius: 6, marginBottom: 10, fontSize: 13,
      whiteSpace: 'pre-wrap',
    }}>{text}</div>
  )
}

function Row({ r, i, patch, pickSku }) {
  const [open, setOpen] = useState(false)
  const ng = !r.ok
  return (
    <div style={{
      border: `1px solid ${ng ? '#fecaca' : C.line}`, borderRadius: 8,
      padding: 12, marginBottom: 8, background: ng ? '#fff7f7' : '#fff',
    }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
        <input type="checkbox" checked={!!r.send} disabled={ng}
          onChange={e => patch(i, { send: e.target.checked })}
          style={{ ...check, marginTop: 3 }} />
        {r.chosen && r.chosen.image
          ? <img src={r.chosen.image} alt="" style={{
              width: 44, height: 44, objectFit: 'contain',
              border: `1px solid ${C.line}`, borderRadius: 4 }} />
          : null}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: C.text }}>
            {r.sku} <span style={{ fontWeight: 400, color: C.sub }}>×{r.qty}</span>
            {r.remembered && <span style={{
              fontSize: 11, color: C.good, marginLeft: 8,
            }}>前回と同じ組み合わせ</span>}
          </div>
          <div style={{ fontSize: 12, color: C.sub, marginTop: 2 }}>
            {r.title || r.name}
          </div>

          {/* 色・サイズ。自動で決まったものも、ここで選び直せる */}
          {r.skus && r.skus.length > 0 && (
            <div style={{ marginTop: 6, display: 'flex', gap: 8,
              alignItems: 'center', flexWrap: 'wrap' }}>
              <select value={r.skuId} onChange={e => pickSku(i, e.target.value)}
                style={{ fontSize: 12, padding: '5px 7px', width: 'auto', maxWidth: 420,
                  border: `1px solid ${r.skuId ? C.line : C.bad}`, borderRadius: 5 }}>
                <option value="">（色・サイズを選ぶ）</option>
                {r.skus.map(s => (
                  <option key={s.sku_id} value={s.sku_id}>
                    {s.label}　{s.price != null ? `${s.price}元` : ''}
                    {s.stock != null ? `　在庫${s.stock}` : ''}
                  </option>
                ))}
              </select>
              <span style={{ fontSize: 12, color: C.sub }}>
                マスタ: {r.color || '—'} / {r.size || '—'}
              </span>
            </div>
          )}

          {r.error && (
            <div style={{ fontSize: 12, color: ng ? C.bad : C.warn, marginTop: 5 }}>
              {r.error}
            </div>
          )}

          <button onClick={() => setOpen(o => !o)} style={{
            marginTop: 6, fontSize: 11, color: C.key, background: 'none',
            border: 'none', padding: 0, cursor: 'pointer',
          }}>
            {open ? '▲ 検品オプション・備考を閉じる' : '▼ 検品オプション・備考'}
            {Object.keys(r.inspect || {}).length > 0 && ' （指定あり）'}
          </button>

          {open && (
            <div style={{ marginTop: 8, padding: 10, background: '#f8fafc',
              borderRadius: 6 }}>
              <div style={{ fontSize: 11, color: C.warn, marginBottom: 6 }}>
                検品オプションは発注時にしか指定できません。買付が始まると変更できません
              </div>
              <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                {INSPECT.map(([k, labelText]) => (
                  <label key={k} style={{ fontSize: 12, display: 'flex',
                    alignItems: 'center', gap: 4 }}>
                    <input type="checkbox" checked={!!r.inspect[k]} style={check}
                      onChange={e => patch(i, {
                        inspect: { ...r.inspect, [k]: e.target.checked ? 1 : 0 },
                      })} />
                    {labelText}
                  </label>
                ))}
              </div>
              <input type="text" placeholder="その他のご要望（現場スタッフが見ます）"
                value={r.inspect.var7 || ''}
                onChange={e => patch(i, { inspect: { ...r.inspect, var7: e.target.value } })}
                style={{ width: '100%', marginTop: 8, fontSize: 12, padding: '6px 8px',
                  border: `1px solid ${C.line}`, borderRadius: 5, boxSizing: 'border-box' }} />
              <input type="text" placeholder="この発注だけの備考"
                value={r.remark}
                onChange={e => patch(i, { remark: e.target.value })}
                style={{ width: '100%', marginTop: 6, fontSize: 12, padding: '6px 8px',
                  border: `1px solid ${C.line}`, borderRadius: 5, boxSizing: 'border-box' }} />
              <label style={{ fontSize: 12, display: 'flex', alignItems: 'center',
                gap: 5, marginTop: 8 }}>
                <input type="checkbox" checked={!!r.rememberInspect} style={check}
                  onChange={e => patch(i, { rememberInspect: e.target.checked })} />
                この検品オプションを商品マスタに覚えさせる（次回から自動で入る）
              </label>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
