import { useState } from 'react'
import api from '../api/client'

/**
 * 仕入れ試算（タオタロウ）。
 *
 * 2026-09-24 に提供が始まった3本を使う。上流（1688）に行かないので速く、
 * リサーチ権限も要らない。
 *   ・工場に払える上限   … 日本での売価から逆算
 *   ・認証が要るか       … 電安法・電波法・食衛法・PSC・薬機法
 *   ・ルート別の国際送料 … 船便・航空便などの比較
 *
 * 応答の形は実物を見て決めたものではないので、分かる項目を上に出しつつ、
 * 返ってきたものは全部そのまま見られるようにしてある。
 * 項目を落として「出ていない」と誤解するほうが困るため。
 */

const C = {
  line: '#e5e7eb', sub: '#64748b', text: '#0f172a',
  good: '#16a34a', warn: '#b45309', bad: '#dc2626', key: '#2563eb',
}

const POWER = [
  ['', '（選ばない）'], ['none', '電源なし'], ['usb', 'USB'],
  ['battery', '電池・バッテリー'], ['ac', 'コンセント'],
]
const WIRELESS = [
  ['', '（選ばない）'], ['none', '無線なし'], ['bt', 'Bluetooth'],
  ['wifi', 'Wi-Fi'], ['other', 'その他の無線'],
]

const box = {
  border: `1px solid ${C.line}`, borderRadius: 8, padding: 12,
  background: '#fff', marginBottom: 12,
}
const lab = { fontSize: 11, color: C.sub, marginBottom: 2 }

export default function TaotaroToolsPage() {
  const [f, setF] = useState({
    product_name: '', price_jpy: '', length_cm: '', width_cm: '',
    height_cm: '', weight_g: '', qty: '', cost_cny: '', duty_rate_pct: '',
    power: '', wireless: '', food_contact: false, for_children: false,
    lookalike: false, health_claim: false,
  })
  const [quote, setQuote] = useState(null)
  const [screening, setScreening] = useState(null)
  const [freight, setFreight] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const set = (k, v) => setF(p => ({ ...p, [k]: v }))
  const num = (v) => (v === '' || v == null ? undefined : Number(v))

  const run = async () => {
    setBusy(true); setErr('')
    setQuote(null); setScreening(null); setFreight(null)
    const dims = {
      length_cm: num(f.length_cm), width_cm: num(f.width_cm),
      height_cm: num(f.height_cm), weight_g: num(f.weight_g),
    }
    const jobs = []
    if (f.price_jpy) {
      jobs.push(api.post('/taotaro/tools/quote', {
        price_jpy: num(f.price_jpy), ...dims, qty: num(f.qty),
        cost_cny: num(f.cost_cny), duty_rate_pct: num(f.duty_rate_pct),
      }).then(r => setQuote(r.data)))
    }
    if (f.product_name.trim()) {
      jobs.push(api.post('/taotaro/tools/screening', {
        product_name: f.product_name,
        power: f.power || undefined, wireless: f.wireless || undefined,
        food_contact: f.food_contact || undefined,
        for_children: f.for_children || undefined,
        lookalike: f.lookalike || undefined,
        health_claim: f.health_claim || undefined,
      }).then(r => setScreening(r.data)))
    }
    if (f.length_cm && f.width_cm && f.height_cm) {
      jobs.push(api.post('/taotaro/tools/freight', {
        ...dims, product_name: f.product_name || undefined,
        has_battery: f.power === 'battery' ? true : undefined,
      }).then(r => setFreight(r.data)))
    }
    if (!jobs.length) {
      setErr('売価か商品名のどちらかは入れてください')
      setBusy(false)
      return
    }
    const res = await Promise.allSettled(jobs)
    const bad = res.filter(r => r.status === 'rejected')
    if (bad.length) {
      setErr(bad.map(b => b.reason?.response?.data?.detail
        || b.reason?.message).join(' ／ '))
    }
    setBusy(false)
  }

  return (
    <div style={{ padding: 2, minWidth: 0, maxWidth: 1100 }}>
      <h2 style={{ fontSize: 18, marginBottom: 4 }}>🧮 仕入れ試算（タオタロウ）</h2>
      <div style={{ fontSize: 12, color: C.sub, marginBottom: 12 }}>
        売価から工場に払える上限を逆算し、日本に入れるのに認証が要るかを見ます。
        1688のページは見に行かないので、商品が決まる前でも使えます。
      </div>

      {err && (
        <div style={{
          background: '#fef2f2', border: '1px solid #fecaca', color: '#991b1b',
          padding: 10, borderRadius: 6, marginBottom: 10, fontSize: 13,
        }}>{err}</div>
      )}

      <div style={box}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)',
          gap: 10 }}>
          <div style={{ gridColumn: 'span 2' }}>
            <div style={lab}>商品名（認証の判定に使います）</div>
            <input value={f.product_name} placeholder="例: ワイヤレスイヤホン"
              onChange={e => set('product_name', e.target.value)} />
          </div>
          <div>
            <div style={lab}>日本での売価（円）</div>
            <input type="number" value={f.price_jpy} placeholder="2980"
              onChange={e => set('price_jpy', e.target.value)} />
          </div>
          <div>
            <div style={lab}>想定仕入値（元・任意）</div>
            <input type="number" step="0.01" value={f.cost_cny} placeholder="8.5"
              onChange={e => set('cost_cny', e.target.value)} />
          </div>

          <div>
            <div style={lab}>長さ(cm)</div>
            <input type="number" value={f.length_cm}
              onChange={e => set('length_cm', e.target.value)} />
          </div>
          <div>
            <div style={lab}>幅(cm)</div>
            <input type="number" value={f.width_cm}
              onChange={e => set('width_cm', e.target.value)} />
          </div>
          <div>
            <div style={lab}>高さ(cm)</div>
            <input type="number" value={f.height_cm}
              onChange={e => set('height_cm', e.target.value)} />
          </div>
          <div>
            <div style={lab}>重さ(g)</div>
            <input type="number" value={f.weight_g}
              onChange={e => set('weight_g', e.target.value)} />
          </div>

          <div>
            <div style={lab}>数量（既定500）</div>
            <input type="number" value={f.qty} placeholder="500"
              onChange={e => set('qty', e.target.value)} />
          </div>
          <div>
            <div style={lab}>関税率(%・任意)</div>
            <input type="number" step="0.1" value={f.duty_rate_pct}
              placeholder="省略すると0%で計算されます"
              onChange={e => set('duty_rate_pct', e.target.value)} />
          </div>
          <div>
            <div style={lab}>電源</div>
            <select value={f.power} onChange={e => set('power', e.target.value)}>
              {POWER.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          <div>
            <div style={lab}>無線</div>
            <select value={f.wireless}
              onChange={e => set('wireless', e.target.value)}>
              {WIRELESS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 16, marginTop: 10, flexWrap: 'wrap' }}>
          {[['food_contact', '食品に触れる'], ['for_children', '子ども向け'],
            ['lookalike', '既存商品に似ている'],
            ['health_claim', '効能をうたう予定（薬機法の判定が変わります）'],
          ].map(([k, l]) => (
            <label key={k} style={{ fontSize: 12, display: 'flex',
              alignItems: 'center', gap: 4 }}>
              <input type="checkbox" checked={f[k]} style={{ width: 'auto' }}
                onChange={e => set(k, e.target.checked)} />
              {l}
            </label>
          ))}
        </div>

        <button className="btn btn-primary" onClick={run} disabled={busy}
          style={{ marginTop: 12 }}>
          {busy ? '試算中…' : '試算する'}
        </button>
      </div>

      {quote && <Result title="💰 工場に払える上限" data={quote}
        pick={['allowance_cny', 'chargeable_weight', 'units_per_carton',
          'fba_size', 'freight_jpy', 'reason', 'next_actions']} />}
      {screening && <Result title="⚖️ 日本に入れるのに認証が要るか" data={screening}
        pick={['verdict', 'summary', 'applicable', 'not_applicable',
          'transport', 'ip_checks']} />}
      {freight && <Result title="🚢 ルート別の1個あたり国際送料" data={freight}
        pick={['routes', 'blocked_routes', 'chargeable_weight',
          'units_per_carton']} />}

      {(quote || screening) && (
        <div style={{ fontSize: 11, color: C.sub, lineHeight: 1.8 }}>
          いずれも参考試算です。関税・輸入消費税は含まれません。
          採算が取れない場合、払える上限は「0元」ではなく空で返ります
          （仕入値が0でも赤字、という意味です）。
        </div>
      )}
    </div>
  )
}

/**
 * 返ってきたものを出す。分かる項目を上に、残りはそのまま下に。
 * こちらで項目を選ぶと、知らない項目が出たときに落としてしまう。
 */
function Result({ title, data, pick }) {
  const d = data?.data ?? data
  const known = pick.filter(k => d && d[k] !== undefined && d[k] !== null)
  const rest = d && typeof d === 'object'
    ? Object.keys(d).filter(k => !pick.includes(k))
    : []
  return (
    <div style={box}>
      <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 8 }}>{title}</div>
      {known.length === 0 && (
        <div style={{ fontSize: 12, color: C.sub, marginBottom: 6 }}>
          想定していた項目名では返ってきませんでした。下の内容をご覧ください。
        </div>
      )}
      {known.map(k => (
        <div key={k} style={{ display: 'flex', gap: 10, fontSize: 13,
          padding: '3px 0', borderTop: `1px solid ${C.line}` }}>
          <span style={{ color: C.sub, width: 190, flexShrink: 0 }}>{k}</span>
          <span style={{ fontWeight: 600, whiteSpace: 'pre-wrap' }}>
            {typeof d[k] === 'object' ? JSON.stringify(d[k], null, 1) : String(d[k])}
          </span>
        </div>
      ))}
      {rest.length > 0 && (
        <details style={{ marginTop: 8 }}>
          <summary style={{ fontSize: 12, color: C.key, cursor: 'pointer' }}>
            返ってきた内容をすべて見る
          </summary>
          <pre style={{ fontSize: 11, background: '#f8fafc', padding: 8,
            borderRadius: 4, overflow: 'auto', maxHeight: 320,
            whiteSpace: 'pre-wrap' }}>
            {JSON.stringify(d, null, 1)}
          </pre>
        </details>
      )}
    </div>
  )
}
