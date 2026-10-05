import { useCallback, useEffect, useState } from 'react'
import api from '../api/client'
import { normalizeSearch } from '../searchUtil'

/**
 * 楽天RPPの広告管理。
 *
 * 楽天ウェブサービスに広告のAPIが無いので、RMSのパフォーマンスレポートから
 * 落としたCSVを入れる。日ごとに出せるのは「すべての広告」単位までで、
 * 商品別は月ごとでしか出せない（RMSの画面にそう書かれている）。
 */

const C = {
  line: '#e5e7eb', sub: '#64748b', text: '#0f172a',
  good: '#16a34a', warn: '#b45309', bad: '#dc2626', key: '#2563eb',
}

const yen = (v) => `¥${Math.round(Number(v) || 0).toLocaleString()}`
const th = { padding: '6px 8px', fontSize: 11, color: C.sub,
  background: '#f8fafc', whiteSpace: 'nowrap' }
const td = { padding: '5px 8px', fontSize: 12, borderTop: `1px solid ${C.line}` }
const num = { ...td, textAlign: 'right', whiteSpace: 'nowrap' }

export default function RakutenAdsPage() {
  const [tab, setTab] = useState('watch')
  const [daily, setDaily] = useState(null)
  const [products, setProducts] = useState(null)
  const [period, setPeriod] = useState('')
  const [search, setSearch] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [result, setResult] = useState(null)
  const [watch, setWatch] = useState(null)

  const load = useCallback(async () => {
    setErr('')
    try {
      const [d, p, w] = await Promise.all([
        api.get('/rakuten/ads/daily'),
        api.get('/rakuten/ads/products', { params: period ? { period } : {} }),
        api.get('/rakuten/ads/watch'),
      ])
      setDaily(d.data)
      setProducts(p.data)
      setWatch(w.data)
      if (!period && (p.data.periods || []).length) setPeriod(p.data.periods[0])
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    }
  }, [period])

  useEffect(() => { load() }, [load])

  const upload = async (file) => {
    if (!file) return
    setBusy(true); setErr(''); setResult(null)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const r = await api.post('/rakuten/ads/import', fd,
        { params: period ? { period } : {} })
      setResult(r.data)
      await load()
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  const shown = (products?.items || []).filter(i => !search.trim()
    || normalizeSearch(`${i.manage_number} ${i.item_name}`)
      .includes(normalizeSearch(search)))

  return (
    <div style={{ padding: 2, minWidth: 0 }}>
      <h2 style={{ fontSize: 18, marginBottom: 4 }}>📣 楽天 広告管理（RPP）</h2>
      <div style={{ fontSize: 12, color: C.sub, marginBottom: 12 }}>
        RMSの広告画面を開くと、Chrome拡張が実績をここに入れます（操作は不要）。
      </div>

      {err && (
        <div style={{ background: '#fef2f2', border: '1px solid #fecaca',
          color: '#991b1b', padding: 10, borderRadius: 6, marginBottom: 10,
          fontSize: 13 }}>{err}</div>
      )}

      {/* 普段は拡張が入れるので、CSVの手入れは畳んでおく */}
      <details className="card" style={{ marginBottom: 12 }}>
        <summary style={{ cursor: 'pointer', fontSize: 12, color: C.sub }}>
          CSVを手で取り込む（拡張を使わないとき）
        </summary>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center',
          flexWrap: 'wrap', marginTop: 10 }}>
          <input type="file" accept=".csv,.xlsx,text/csv" disabled={busy}
            onChange={e => { upload(e.target.files?.[0]); e.target.value = '' }}
            style={{ fontSize: 12 }} />
          {busy && <span style={{ fontSize: 12, color: C.sub }}>取り込み中…</span>}
        </div>
        <div style={{ fontSize: 11, color: C.sub, marginTop: 8, lineHeight: 1.9 }}>
          <b>毎日の消化額</b>：集計単位「すべての広告」＋集計期間「日ごとに表示」
          →「この条件でダウンロード」（期間は3か月以内）<br />
          <b>商品ごと</b>：「全商品レポートダウンロード」（ZIPのままで入ります）<br />
          どちらのCSVかは中身を見て判断します。同じ日・同じ商品は入れ替わるので、
          何度入れても二重になりません。
        </div>
        {result && (
          <div style={{ marginTop: 8, fontSize: 12, padding: '8px 10px',
            borderRadius: 6,
            background: result.missing?.length ? '#fffbeb' : '#f0fdf4',
            border: `1px solid ${result.missing?.length ? '#fcd34d' : '#bbf7d0'}`,
            color: result.missing?.length ? '#92400e' : '#166534' }}>
            {result.kind === 'product' ? '商品ごと' : '毎日の消化'}のCSVとして
            <b> {result.saved}行</b>を取り込みました
            {result.skipped > 0 && `（${result.skipped}行は飛ばしました）`}。
            {result.missing?.length > 0 && (
              <b>　見つからなかった列：{result.missing.join('、')}</b>
            )}
            <details style={{ marginTop: 4 }}>
              <summary style={{ cursor: 'pointer' }}>どの列を使ったか</summary>
              <div style={{ fontSize: 11, marginTop: 4 }}>
                {Object.entries(result.used_columns || {})
                  .map(([k, v]) => `${k} ← ${v}`).join(' ／ ')}
              </div>
            </details>
          </div>
        )}
      </details>

      <div style={{ display: 'flex', gap: 6, marginBottom: 12 }}>
        {[['watch', `👀 見張り${(watch?.alerts || []).length
          ? `（${watch.alerts.length}）` : ''}`],
          ['daily', '毎日の消化'], ['product', '商品ごと']].map(([v, l]) => (
          <button key={v} className="btn btn-sm" onClick={() => setTab(v)}
            style={{ fontSize: 12,
              background: tab === v ? '#2563eb' : '#f1f5f9',
              color: tab === v ? '#fff' : '#334155',
              border: `1px solid ${tab === v ? '#2563eb' : C.line}` }}>
            {l}
          </button>
        ))}
      </div>

      {tab === 'watch' && watch && <WatchPanel w={watch} />}

      {tab === 'daily' && daily && (
        <>
          {(daily.months || []).length > 0 && (
            <div className="card" style={{ padding: 0, marginBottom: 12,
              overflow: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead><tr>
                  {['月', 'クリック', '広告費', '広告経由の売上', '件数', 'ROAS']
                    .map((h, i) => (
                      <th key={h} style={{ ...th, textAlign: i ? 'right' : 'left' }}>
                        {h}
                      </th>
                    ))}
                </tr></thead>
                <tbody>
                  {daily.months.map(m => (
                    <tr key={m.month}>
                      <td style={td}>{m.month}</td>
                      <td style={num}>{m.clicks.toLocaleString()}</td>
                      <td style={{ ...num, fontWeight: 700 }}>{yen(m.cost)}</td>
                      <td style={num}>{yen(m.sales)}</td>
                      <td style={num}>{m.orders}</td>
                      <td style={{ ...num, color: m.roas >= 300 ? C.good : C.warn,
                        fontWeight: 600 }}>{m.roas}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="card" style={{ padding: 0, overflow: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead><tr>
                {['日', 'キャンペーン', 'クリック', '広告費', '広告経由の売上',
                  '件数', 'CPC', 'ROAS'].map((h, i) => (
                    <th key={h} style={{ ...th, textAlign: i < 2 ? 'left' : 'right' }}>
                      {h}
                    </th>
                  ))}
              </tr></thead>
              <tbody>
                {(daily.days || []).length === 0 && (
                  <tr><td style={{ ...td, color: C.sub, padding: 20 }} colSpan={8}>
                    まだ取り込んでいません。
                  </td></tr>
                )}
                {(daily.days || []).map((d, i) => (
                  <tr key={i}>
                    <td style={td}>{d.day}</td>
                    <td style={{ ...td, color: C.sub }}>{d.campaign || '—'}</td>
                    <td style={num}>{d.clicks.toLocaleString()}</td>
                    <td style={{ ...num, fontWeight: 600 }}>{yen(d.cost)}</td>
                    <td style={num}>{yen(d.sales)}</td>
                    <td style={num}>{d.orders}</td>
                    <td style={num}>¥{d.cpc}</td>
                    <td style={num}>{d.roas}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {tab === 'product' && products && (
        <>
          <div className="card" style={{ marginBottom: 12, display: 'flex',
            gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <label style={{ fontSize: 12, color: C.sub }}>
              対象月
              <select value={period} onChange={e => setPeriod(e.target.value)}
                style={{ marginLeft: 4, fontSize: 12, width: 130 }}>
                {(products.periods || []).map(p => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
            </label>
            <input value={search} onChange={e => setSearch(e.target.value)}
              placeholder="商品管理番号・商品名で絞り込み"
              className="search-input-ja" style={{ width: 240 }} />
            <span style={{ fontSize: 12, color: C.sub }}>
              {shown.length}件　広告費 {yen(products.total?.cost)}
              クリック {(products.total?.clicks || 0).toLocaleString()}
            </span>
          </div>
          <div className="card" style={{ padding: 0, overflow: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead><tr>
                <th style={{ ...th, textAlign: 'left' }}>商品管理番号</th>
                <th style={{ ...th, textAlign: 'left' }}>商品名</th>
                {['クリック', 'CTR', '広告費', 'CPC', '広告経由の売上', '件数',
                  'CVR', 'ROAS', '入札'].map(h => (
                    <th key={h} style={{ ...th, textAlign: 'right' }}>{h}</th>
                  ))}
              </tr></thead>
              <tbody>
                {shown.length === 0 && (
                  <tr><td style={{ ...td, color: C.sub, padding: 20 }} colSpan={11}>
                    まだ取り込んでいません。「全商品レポートダウンロード」のCSVを入れてください。
                  </td></tr>
                )}
                {shown.map(i => (
                  <tr key={i.manage_number}>
                    <td style={{ ...td, fontFamily: 'monospace', fontSize: 11 }}>
                      {i.manage_number}
                    </td>
                    <td style={{ ...td, maxWidth: 280, overflow: 'hidden',
                      textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                      title={i.item_name}>{i.item_name}</td>
                    <td style={num}>{i.clicks.toLocaleString()}</td>
                    <td style={num}>{i.ctr}%</td>
                    <td style={{ ...num, fontWeight: 600 }}>{yen(i.cost)}</td>
                    <td style={num}>¥{i.cpc}</td>
                    <td style={num}>{yen(i.sales)}</td>
                    <td style={num}>{i.orders}</td>
                    {/* 転換率と費用対効果は、悪いものが目に入るように色を付ける */}
                    <td style={{ ...num, fontWeight: 600,
                      color: i.cvr >= 1 ? C.good : i.clicks > 100 ? C.bad : C.sub }}>
                      {i.cvr}%
                    </td>
                    <td style={{ ...num, fontWeight: 600,
                      color: i.roas >= 300 ? C.good : i.cost > 5000 ? C.bad : C.sub }}>
                      {i.roas}%
                    </td>
                    <td style={{ ...num, color: C.sub }}>¥{i.bid}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}

/**
 * 見張り。
 *
 * 楽天RPPは、ある日いきなり特定の商品でクリックが跳ねて、気づかないうちに
 * 広告費だけ出ていることがある。「いつもの何倍か」で見つける。
 * 採算ラインは商品マスタ（売価・原価・手数料・送料）から出している。
 */
function WatchPanel({ w }) {
  const o = w.overall
  const moveColor = { '止める': C.bad, '下げる': C.warn, '上げる': C.good }

  return (
    <>
      {o && (
        <div className="card" style={{ marginBottom: 12,
          background: o.spike ? '#fef2f2' : '#fff',
          border: `1px solid ${o.spike ? '#fecaca' : C.line}` }}>
          <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 4,
            color: o.spike ? C.bad : C.text }}>
            {o.spike ? '⚠️ 全体でクリックが跳ねています' : '✅ 全体の動きはいつもどおり'}
          </div>
          <div style={{ fontSize: 12, color: C.sub }}>
            {o.day}：{o.clicks.toLocaleString()}クリック・{yen(o.cost)}
            （いつもは {o.usual_clicks.toLocaleString()}クリック・{yen(o.usual_cost)}）
            ／ ROAS {o.roas}%
          </div>
        </div>
      )}

      <div className="card" style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8 }}>
          気になるもの（{w.alerts.length}件）
        </div>
        {w.alerts.length === 0 && (
          <div style={{ fontSize: 12, color: C.sub }}>
            いまのところ、暴走も無駄打ちも見当たりません。
            {(w.item_days || []).length < 4 && (
              <b style={{ color: C.warn }}>
                　※商品ごとの日別がまだ{(w.item_days || []).length}日分しかないので、
                「いつも」が出せていません。数日ぶん溜まると見張りが効きます。
              </b>
            )}
          </div>
        )}
        {w.alerts.map((a, i) => (
          <div key={i} style={{ padding: '8px 10px', marginBottom: 6,
            borderRadius: 6,
            background: a.level === 'danger' ? '#fef2f2'
              : a.level === 'info' ? '#eff6ff' : '#fffbeb',
            border: `1px solid ${a.level === 'danger' ? '#fecaca'
              : a.level === 'info' ? '#bfdbfe' : '#fcd34d'}` }}>
            <div style={{ fontSize: 13, fontWeight: 700,
              color: a.level === 'danger' ? '#991b1b'
                : a.level === 'info' ? '#1d4ed8' : '#92400e' }}>
              {a.headline}
              <span style={{ fontFamily: 'monospace', fontSize: 11,
                marginLeft: 8, color: C.sub }}>{a.manage_number}</span>
            </div>
            <div style={{ fontSize: 12, color: C.text, marginTop: 2 }}>
              {(a.item_name || '').slice(0, 50)}
            </div>
            <div style={{ fontSize: 12, color: C.sub, marginTop: 2 }}>
              {a.detail}
            </div>
            <div style={{ fontSize: 12, marginTop: 4, fontWeight: 600 }}>
              → {a.action}
            </div>
          </div>
        ))}
      </div>

      {(w.stopped || []).length > 0 && (
        <div className="card" style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 6 }}>
            広告を止めている商品（{w.stopped.length}件
            {w.resume_count > 0 && <span style={{ color: C.key }}>
              ／再開できるもの {w.resume_count}件</span>}）
          </div>
          <div style={{ fontSize: 11, color: C.sub, marginBottom: 8 }}>
            RMSの「除外商品」をそのまま出しています。在庫が戻ったものは
            青くなるので、RMSの除外から外してください。
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {w.stopped.map(x => {
              const back = x.stock !== null && x.stock > 0
              return (
                <a key={x.manage_number} href={x.item_url || undefined}
                  target="_blank" rel="noreferrer" title={x.item_name}
                  style={{ fontSize: 11, padding: '3px 8px', borderRadius: 4,
                    textDecoration: 'none',
                    background: back ? '#eff6ff' : '#f8fafc',
                    border: `1px solid ${back ? '#bfdbfe' : C.line}`,
                    color: back ? C.key : C.sub,
                    fontWeight: back ? 700 : 400 }}>
                  {x.manage_number}
                  <span style={{ marginLeft: 4 }}>
                    {x.stock === null ? '（マスタに無し）' : `在庫${x.stock}`}
                  </span>
                </a>
              )
            })}
          </div>
        </div>
      )}

      <div className="card" style={{ padding: 0 }}>
        <div style={{ padding: 10 }}>
          <b style={{ fontSize: 13 }}>入札の上げ下げ（{w.period}）</b>
          <div style={{ fontSize: 11, color: C.sub, marginTop: 4, lineHeight: 1.8 }}>
            採算ラインは、売価から原価・楽天手数料
            {Math.round((w.commission_rate || 0.09) * 100)}%・送料を引いた粗利から出しています。
            推奨入札は「1クリックで見込める粗利 × 0.7」。
            原価か売価が入っていない商品は出てきません。
          </div>
        </div>
        <div style={{ overflow: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr>
              <th style={{ ...th, textAlign: 'left' }}>どうする</th>
              <th style={{ ...th, textAlign: 'left' }}>商品管理番号</th>
              <th style={{ ...th, textAlign: 'left' }}>理由</th>
              {['広告費', 'クリック', '件数', 'ROAS', '採算', '粗利/件',
                'いまの入札', '推奨'].map(h => (
                  <th key={h} style={{ ...th, textAlign: 'right' }}>{h}</th>
                ))}
            </tr></thead>
            <tbody>
              {w.suggestions.length === 0 && (
                <tr><td style={{ ...td, color: C.sub, padding: 20 }} colSpan={11}>
                  今月、上げ下げを言えるほど広告費を使っている商品はありません。
                </td></tr>
              )}
              {w.suggestions.map(s => (
                <tr key={s.manage_number}>
                  <td style={{ ...td, fontWeight: 700,
                    color: moveColor[s.move] || C.text }}>{s.move}</td>
                  <td style={{ ...td, fontFamily: 'monospace', fontSize: 11 }}
                    title={s.item_name}>{s.manage_number}</td>
                  <td style={{ ...td, fontSize: 11, color: C.sub }}>{s.why}</td>
                  <td style={{ ...num, fontWeight: 600 }}>{yen(s.cost)}</td>
                  <td style={num}>{s.clicks.toLocaleString()}</td>
                  <td style={num}>{s.orders}</td>
                  <td style={{ ...num, color: s.roas >= s.breakeven ? C.good : C.bad,
                    fontWeight: 600 }}>{s.roas}%</td>
                  <td style={{ ...num, color: C.sub }}>{s.breakeven}%</td>
                  <td style={num}>{yen(s.profit_per_order)}</td>
                  <td style={num}>¥{s.now_bid}</td>
                  <td style={{ ...num, fontWeight: 700,
                    color: moveColor[s.move] || C.text }}>¥{s.suggest_bid}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}
