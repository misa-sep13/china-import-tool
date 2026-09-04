import { useEffect, useState, useCallback, Fragment } from 'react'
import api from '../api/client'

/**
 * Amazonへの商品登録。
 *
 * リサーチで採用したドラフトを材料にして、まとめてAmazonへ出品する。
 * 商品タイプ（Amazonの分類）ごとに必要な項目が変わるので、競合の商品から
 * 型を借りて、そのとき要るものだけ画面に出す。
 *
 * 送信は取り消せないので、必ず中身を見てから送る作りにしている。
 */
const card = { background: '#fff', borderRadius: 8, padding: 16, border: '1px solid #e5e7eb' }
const btn = { background: '#f1f5f9', border: '1px solid #cbd5e1', borderRadius: 6, padding: '6px 14px', cursor: 'pointer', fontSize: 13 }
const btnMain = { ...btn, background: '#2563eb', color: '#fff', border: 'none', fontWeight: 600 }
const input = { border: '1px solid #d1d5db', borderRadius: 6, padding: '6px 10px', fontSize: 13, width: '100%', boxSizing: 'border-box' }
const label = { fontSize: 11, color: '#64748b', fontWeight: 600, display: 'block', marginBottom: 2 }

const STATUS = {
  draft: { text: '未準備', color: '#94a3b8' },
  ready: { text: '出品待ち', color: '#2563eb' },
  submitted: { text: '送信済み', color: '#16a34a' },
  failed: { text: '失敗', color: '#dc2626' },
}

export default function AmazonListingPage() {
  const [rows, setRows] = useState([])
  const [jan, setJan] = useState(null)
  const [picked, setPicked] = useState({})
  const [openId, setOpenId] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)

  const load = useCallback(async () => {
    setErr('')
    try {
      const [d, j] = await Promise.all([
        api.get('/product-drafts'),
        api.get('/amazon-research/jan'),
      ])
      setRows(d.data || [])
      setJan(j.data)
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    }
  }, [])
  useEffect(() => { load() }, [load])

  const chosen = rows.filter(r => picked[r.id])
  const freeJan = (jan?.rows || []).filter(x => x.status === 'issued').length

  const submit = async (dryRun) => {
    if (!chosen.length) return
    setBusy(true); setErr(''); setResult(null)
    try {
      const r = await api.post('/product-drafts/amazon/submit', {
        draft_ids: chosen.map(x => x.id),
        dry_run: dryRun,
      })
      setResult(r.data)
      if (!dryRun) await load()
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  return (
    <div style={{ padding: 20 }}>
      <h2 style={{ marginTop: 0 }}>📦 Amazon 商品登録</h2>

      {err && (
        <div style={{ background: '#fef2f2', border: '1px solid #fecaca',
          color: '#991b1b', padding: 12, borderRadius: 6, marginBottom: 12 }}>
          {err}
        </div>
      )}

      <div style={{ ...card, marginBottom: 12, display: 'flex',
        alignItems: 'center', gap: 20, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 13 }}>
          <span style={{ color: '#64748b' }}>使えるJANコード</span>{' '}
          <b style={{ fontSize: 16, color: freeJan ? '#16a34a' : '#dc2626' }}>{freeJan}</b> 件
        </div>
        <div style={{ fontSize: 12, color: '#64748b' }}>
          GS1事業者コード {jan?.gs1_prefix || '（未設定）'}
        </div>
        <button style={btn} onClick={load}>更新</button>
        <button style={{ ...btn, marginLeft: 'auto' }} onClick={async () => {
          setBusy(true)
          try {
            await api.post('/amazon-research/jan/issue', {})
            await load()
          } catch (e) { setErr(e.response?.data?.detail || e.message) }
          finally { setBusy(false) }
        }} disabled={busy}>
          ＋ JANを1つ採番
        </button>
      </div>

      <div style={card}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
          <b style={{ fontSize: 14 }}>リサーチで採用した商品（{rows.length}件）</b>
          {chosen.length > 0 && (
            <>
              <span style={{ fontSize: 13, color: '#2563eb' }}>{chosen.length}件を選択中</span>
              <button style={{ ...btn, marginLeft: 'auto' }} disabled={busy}
                onClick={() => submit(true)}>
                送る中身を見る
              </button>
              <button style={btnMain} disabled={busy}
                onClick={() => {
                  if (!window.confirm(
                    `${chosen.length}件をAmazonへ出品します。\n` +
                    '送信すると取り消せません。よろしいですか？')) return
                  submit(false)
                }}>
                {busy ? '送信中…' : 'Amazonへ出品する'}
              </button>
            </>
          )}
        </div>

        <table style={{ width: '100%', fontSize: 13 }}>
          <thead>
            <tr style={{ background: '#f8fafc', color: '#64748b', fontSize: 11 }}>
              <th style={{ width: 34 }} />
              <th style={{ textAlign: 'left', padding: 6 }}>SKU</th>
              <th style={{ textAlign: 'left', padding: 6 }}>商品名</th>
              <th style={{ textAlign: 'left', padding: 6, width: 150 }}>商品タイプ</th>
              <th style={{ textAlign: 'left', padding: 6, width: 130 }}>JAN</th>
              <th style={{ textAlign: 'left', padding: 6, width: 90 }}>状態</th>
              <th style={{ width: 90 }} />
            </tr>
          </thead>
          <tbody>
            {rows.map(r => {
              const st = STATUS[r.amazon_status] || STATUS.draft
              return (
                <Fragment key={r.id}>
                  <tr style={{ borderTop: '1px solid #f1f5f9' }}>
                    <td style={{ textAlign: 'center' }}>
                      <input type="checkbox" checked={!!picked[r.id]}
                        onChange={e => setPicked({ ...picked, [r.id]: e.target.checked })} />
                    </td>
                    <td style={{ padding: 6, fontFamily: 'monospace' }}>{r.sku || '—'}</td>
                    <td style={{ padding: 6, maxWidth: 320, overflow: 'hidden',
                      textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                      title={r.rakuten_title}>
                      {r.rakuten_title || r.rival_title || '(商品名なし)'}
                    </td>
                    <td style={{ padding: 6, fontSize: 11 }}>
                      {r.amazon_product_type || <span style={{ color: '#94a3b8' }}>未判定</span>}
                    </td>
                    <td style={{ padding: 6, fontFamily: 'monospace', fontSize: 11 }}>
                      {r.amazon_jan || <span style={{ color: '#94a3b8' }}>—</span>}
                    </td>
                    <td style={{ padding: 6 }}>
                      <span style={{ color: st.color, fontWeight: 600 }}>{st.text}</span>
                    </td>
                    <td style={{ padding: 6 }}>
                      <button style={btn}
                        onClick={() => setOpenId(openId === r.id ? null : r.id)}>
                        {openId === r.id ? '閉じる' : '準備'}
                      </button>
                    </td>
                  </tr>
                  {openId === r.id && (
                    <tr>
                      <td colSpan="7" style={{ background: '#f8fafc', padding: 14 }}>
                        <ListingEditor draft={r} onChanged={load} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
            {!rows.length && (
              <tr><td colSpan="7" style={{ padding: 24, textAlign: 'center', color: '#94a3b8' }}>
                リサーチで「採用」した商品がここに出ます
              </td></tr>
            )}
          </tbody>
        </table>
      </div>

      {result && <ResultPanel result={result} onClose={() => setResult(null)} />}
    </div>
  )
}

/** 1商品ぶんの出品準備。商品タイプを決めて、要る項目を埋める。 */
function ListingEditor({ draft, onChanged }) {
  const [asin, setAsin] = useState(draft.rival_item_code || '')
  const [fields, setFields] = useState(null)
  const [form, setForm] = useState({
    amazon_bullets: draft.amazon_bullets || [],
    amazon_attrs: draft.amazon_attrs || {},
  })
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const prepare = async () => {
    setBusy(true); setMsg('')
    try {
      const r = await api.post(`/product-drafts/${draft.id}/amazon/prepare`,
        { rival_asin: asin, issue_jan: true })
      setFields(r.data.required_fields || [])
      setMsg(`商品タイプ: ${r.data.display_name || r.data.product_type}` +
             (r.data.jan ? ` / JAN: ${r.data.jan}` : '') +
             (r.data.jan_warning ? ` ／ ${r.data.jan_warning}` : ''))
      await onChanged()
    } catch (e) {
      setMsg(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  const save = async () => {
    setBusy(true); setMsg('')
    try {
      await api.put(`/product-drafts/${draft.id}`, {
        amazon_bullets: form.amazon_bullets.filter(b => (b || '').trim()),
        amazon_attrs: form.amazon_attrs,
        amazon_status: 'ready',
      })
      setMsg('保存しました')
      await onChanged()
    } catch (e) {
      setMsg(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  return (
    <div style={{ display: 'grid', gap: 12 }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end', flexWrap: 'wrap' }}>
        <div style={{ maxWidth: 220 }}>
          <span style={label}>参考にする競合のASIN</span>
          <input style={input} value={asin} onChange={e => setAsin(e.target.value)}
            placeholder="B0XXXXXXXX" />
        </div>
        <button style={btnMain} onClick={prepare} disabled={busy || !asin}>
          {busy ? '調べています…' : '出品の準備'}
        </button>
        <div style={{ fontSize: 12, color: '#64748b' }}>
          競合と同じ商品タイプを使います。JANも自動で割り当てます。
        </div>
      </div>

      {msg && <div style={{ fontSize: 12, color: '#334155' }}>{msg}</div>}

      <div>
        <span style={label}>商品の要点（5個まで・Amazonの箇条書きに出ます）</span>
        <textarea style={{ ...input, minHeight: 80 }}
          value={(form.amazon_bullets || []).join('\n')}
          placeholder={'4重ガーゼで肌にやさしい\n綿100%・12枚セット'}
          onChange={e => setForm(f => ({
            ...f, amazon_bullets: e.target.value.split('\n').slice(0, 5),
          }))} />
      </div>

      {fields && fields.length > 0 && (
        <div>
          <span style={label}>このタイプで必要な項目</span>
          <table style={{ width: '100%', fontSize: 13 }}>
            <tbody>
              {fields.map(f => (
                <tr key={f.name}>
                  <td style={{ width: 200, color: '#475569', paddingRight: 8 }}>
                    {f.label || f.name}
                  </td>
                  <td>
                    {f.type === 'select' && (f.choices || []).length ? (
                      <select style={input}
                        value={form.amazon_attrs[f.name] || ''}
                        onChange={e => setForm(x => ({
                          ...x, amazon_attrs: { ...x.amazon_attrs, [f.name]: e.target.value },
                        }))}>
                        <option value="">（選ぶ）</option>
                        {f.choices.map(c => <option key={c} value={c}>{c}</option>)}
                      </select>
                    ) : (
                      <input style={input} value={form.amazon_attrs[f.name] || ''}
                        onChange={e => setForm(x => ({
                          ...x, amazon_attrs: { ...x.amazon_attrs, [f.name]: e.target.value },
                        }))} />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {fields && !fields.length && (
        <div style={{ fontSize: 12, color: '#16a34a' }}>
          このタイプで追加の入力は要りません。
        </div>
      )}

      <div>
        <button style={btnMain} onClick={save} disabled={busy}>
          保存して出品待ちにする
        </button>
      </div>

      {draft.amazon_error && (
        <div style={{ background: '#fef2f2', border: '1px solid #fecaca',
          color: '#991b1b', padding: 10, borderRadius: 6, fontSize: 12 }}>
          前回の失敗: {draft.amazon_error.slice(0, 400)}
        </div>
      )}
    </div>
  )
}

/** 送信の結果。dry-run のときは送る中身を出す。 */
function ResultPanel({ result, onClose }) {
  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.5)', zIndex: 1000,
      display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={onClose}>
      <div onClick={e => e.stopPropagation()} style={{ background: '#fff', borderRadius: 10,
        width: 'min(820px, 94vw)', maxHeight: '90vh', overflow: 'auto', padding: 24 }}>
        <h3 style={{ marginTop: 0 }}>
          {result.dry_run ? '送る中身（まだ送っていません）' : '出品の結果'}
        </h3>

        {result['送っていません'] && (
          <div style={{ background: '#fffbeb', border: '1px solid #fde68a',
            color: '#92400e', padding: 12, borderRadius: 6, marginBottom: 12 }}>
            足りないものがあるので、1件も送っていません。
            <ul style={{ margin: '8px 0 0', paddingLeft: 20 }}>
              {(result['問題'] || []).map((p, i) => (
                <li key={i}>{p.sku}: {(p['足りないもの'] || []).join('・')}</li>
              ))}
            </ul>
          </div>
        )}

        {result['結果'] && (
          <>
            {!result.dry_run && (
              <div style={{ marginBottom: 10, fontSize: 14 }}>
                成功 <b style={{ color: '#16a34a' }}>{result['成功']}</b> 件 /
                失敗 <b style={{ color: '#dc2626' }}>{result['失敗']}</b> 件
              </div>
            )}
            {result['結果'].map((r, i) => (
              <div key={i} style={{ borderTop: '1px solid #e5e7eb', padding: '10px 0' }}>
                <div style={{ fontWeight: 600 }}>
                  {r.sku}{' '}
                  {r.dry_run
                    ? <span style={{ color: '#64748b', fontSize: 12 }}>（{r.product_type}）</span>
                    : <span style={{ color: r.ok ? '#16a34a' : '#dc2626' }}>
                        {r.ok ? 'OK' : '失敗'}
                      </span>}
                </div>
                {r.attributes && (
                  <pre style={{ fontSize: 11, background: '#f8fafc', padding: 10,
                    borderRadius: 4, overflow: 'auto', maxHeight: 220 }}>
                    {JSON.stringify(r.attributes, null, 2)}
                  </pre>
                )}
                {(r.issues || []).map((is, n) => (
                  <div key={n} style={{ fontSize: 12,
                    color: is.severity === 'ERROR' ? '#dc2626' : '#b45309' }}>
                    ・{is.message}
                  </div>
                ))}
                {r.error && (
                  <div style={{ fontSize: 12, color: '#dc2626' }}>{String(r.error).slice(0, 400)}</div>
                )}
              </div>
            ))}
          </>
        )}

        <div style={{ textAlign: 'right', marginTop: 16 }}>
          <button style={btn} onClick={onClose}>閉じる</button>
        </div>
      </div>
    </div>
  )
}
