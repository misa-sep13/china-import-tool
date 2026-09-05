import { useCallback, useEffect, useRef, useState } from 'react'
import api from '../api/client'
import { C, card, label, input, bytes, Err } from './ListingTab'

/**
 * 1商品ぶんの出品内容を仕上げる画面。
 *
 * 上から順に「判断根拠 → 出品原稿 → 中身 → バリエーション → 画像 →
 * 商品タイプの必須項目 → 送信」の流れ。リサーチで調べたことを見ながら
 * 書けるように、根拠は常に上に置いてある。
 */
export default function ListingEditor({ listingId, onBack }) {
  const [d, setD] = useState(null)
  const [problems, setProblems] = useState([])
  const [fields, setFields] = useState(null)     // 商品タイプの必須項目
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const [nextSku, setNextSku] = useState('')   // 次に空いている番号。欄の下書きに出す
  const dirty = useRef(false)

  useEffect(() => {
    api.get('/amazon-listings/next-sku')
      .then(r => setNextSku((r.data.next || [])[0] || ''))
      .catch(() => {})
  }, [])

  const load = useCallback(async () => {
    setErr('')
    try {
      const [r, c] = await Promise.all([
        api.get(`/amazon-listings/${listingId}`),
        api.get(`/amazon-listings/${listingId}/check`),
      ])
      setD(r.data)
      setProblems(c.data.problems || [])
      dirty.current = false
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    }
  }, [listingId])
  useEffect(() => { load() }, [load])

  const set = (k, v) => { dirty.current = true; setD(x => ({ ...x, [k]: v })) }

  const save = async (extra = {}) => {
    setBusy(true); setErr(''); setMsg('')
    try {
      const body = {
        title: d.title, keywords: d.keywords, bullets: d.bullets,
        description: d.description, brand: d.brand, price: d.price,
        len_a: d.len_a, len_b: d.len_b, len_c: d.len_c, weight: d.weight,
        rival_asin: d.rival_asin, attrs: d.attrs,
        parent_sku: d.parent_sku,
        variation_theme: d.variation_theme,
        axis1_label: d.axis1_label, axis2_label: d.axis2_label,
        children: (d.children || []).map(c => ({
          id: c.id, sku: c.sku, title: c.title,
          axis1: c.axis1, axis2: c.axis2, price: c.price,
        })),
        ...extra,
      }
      const r = await api.put(`/amazon-listings/${listingId}`, body)
      setD(r.data)
      dirty.current = false
      const c = await api.get(`/amazon-listings/${listingId}/check`)
      setProblems(c.data.problems || [])
      setMsg('保存しました')
      return true
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
      return false
    } finally { setBusy(false) }
  }

  const prepare = async () => {
    if (dirty.current && !(await save())) return
    setBusy(true); setErr(''); setMsg('')
    try {
      const r = await api.post(`/amazon-listings/${listingId}/prepare`)
      setD(r.data)
      setFields(r.data.required_fields || [])
      const n = (r.data.issued_jan || []).length
      setMsg(`商品タイプ: ${r.data.product_type}`
        + (r.data.product_type_name ? `（${r.data.product_type_name}）` : '')
        + (n ? ` ／ JANを${n}件発番しました` : '')
        + (r.data.schema_error ? ` ／ 必須項目は取れませんでした: ${r.data.schema_error}` : ''))
      const c = await api.get(`/amazon-listings/${listingId}/check`)
      setProblems(c.data.problems || [])
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  // 命名ルールどおりの下書きを作る（ブランド名／メインキーワード／
  // 関連ワード／サイズ・数量・色 で65字程度）。作ったあと手で直す前提
  const [push, setPush] = useState('')
  const genTitle = async () => {
    setBusy(true); setErr(''); setMsg('')
    try {
      const r = await api.post(
        `/amazon-listings/${listingId}/title?push=${encodeURIComponent(push)}`)
      if (!r.data.ok) { setErr(r.data.error); return }
      if ((d.title || '').trim()
          && !confirm('いまの商品タイトルを下書きで置き換えますか？')) return
      set('title', r.data.title)
      setMsg(`${r.data.length}字で作りました。ここから手で直してください`)
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  const resync = async () => {
    if (!confirm('シートの内容で上書きします。この画面で直したところは消えます。よろしいですか？')) return
    setBusy(true); setErr('')
    try {
      const r = await api.post(
        `/amazon-listings/sync/${d.research_id}?overwrite=true`)
      setD(r.data); setMsg('シートから取り込み直しました')
      const c = await api.get(`/amazon-listings/${listingId}/check`)
      setProblems(c.data.problems || [])
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  const submit = async (dryRun) => {
    if (dirty.current && !(await save())) return
    setBusy(true); setErr(''); setResult(null)
    try {
      const r = await api.post('/amazon-listings/submit',
        { listing_ids: [listingId], dry_run: dryRun })
      setResult(r.data.results[0])
      if (!dryRun) await load()
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  if (!d) {
    return <div style={{ padding: 20, color: C.sub }}>
      {err ? <Err text={err} /> : '読み込んでいます…'}
    </div>
  }

  const kwBytes = bytes(d.keywords)
  const sent = d.status === 'submitted' || d.status === 'live'

  return (
    <div style={{ overflow: 'auto', height: '100%', padding: 2, minWidth: 0 }}>
      {/* ---- 上のバー ---- */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center',
        marginBottom: 10, flexWrap: 'wrap' }}>
        <button className="btn btn-secondary" onClick={onBack}>← 一覧へ</button>
        {/* 折り返さない長い文字は、min-width:0 を付けても「縮められない幅」が
            全長のまま親へ伝わり、画面ごと横に伸びてしまう。日本語はどこでも
            折り返せるので、折り返しは許したうえで1行で切る */}
        <div style={{ fontSize: 13, fontWeight: 600, flex: '1 1 0', minWidth: 0,
          whiteSpace: 'normal', display: '-webkit-box',
          WebkitLineClamp: 1, WebkitBoxOrient: 'vertical',
          overflow: 'hidden' }}>
          {d.research_title}
        </div>
        <button className="btn btn-secondary" onClick={resync} disabled={busy}>
          シートから取り込み直す
        </button>
        <button className="btn btn-primary" onClick={() => save()} disabled={busy}>
          保存
        </button>
      </div>

      {err && <Err text={err} />}
      {msg && <div style={{ background: '#f0fdf4', border: '1px solid #bbf7d0',
        color: '#166534', padding: 9, borderRadius: 6, marginBottom: 10,
        fontSize: 13 }}>{msg}</div>}

      {/* ---- 判断根拠 ---- */}
      <Basis d={d} />

      {/* ---- 送信前の指摘 ---- */}
      {problems.length > 0 && (
        <div style={{ ...card, marginBottom: 10, background: '#fffbeb',
          borderColor: '#fde68a' }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: C.warn,
            marginBottom: 5 }}>
            出品するまでに足りないもの（{problems.length}件）
          </div>
          {problems.map((p, i) => (
            <div key={i} style={{ fontSize: 12, color: '#92400e' }}>・{p}</div>
          ))}
        </div>
      )}

      {/* ---- リサーチで集めた材料 ---- */}
      <Notes notes={d.notes} />

      {/* ---- 出品原稿 ---- */}
      <section style={{ ...card, marginBottom: 10 }}>
        <H t="出品原稿" note="競合リサーチシートの「🏷 出品原稿をつくる」で作ったものが入ります。空なら、ここで直接書けます" />

        <div style={{ marginBottom: 10 }}>
          <span style={label}>
            商品タイトル（親）
            {/* 命名ルール。書くたびに思い出せるよう見出しの横に置く */}
            <span style={{ marginLeft: 8, fontWeight: 400, fontSize: 11 }}>
              <b style={{ color: C.text }}>ブランド名</b>
              <Sep /><b style={{ color: C.text }}>メインキーワード</b>
              <Sep /><b style={{ color: C.text }}>関連ワード</b>
              <span>（SEO高い＆コンバージョンあるキーワードから）</span>
              <Sep /><b style={{ color: C.text }}>サイズ・数量・色</b>
            </span>
            <Count n={(d.title || '').length} max={75} unit="字" />
          </span>
          <textarea style={{ ...input, minHeight: 46 }} value={d.title || ''}
            onChange={e => set('title', e.target.value)}
            placeholder="ブランド名 + 商品名 + 特徴 + サイズ など" />
          <div style={{ display: 'flex', gap: 6, alignItems: 'center',
            marginTop: 5, flexWrap: 'wrap' }}>
            <button className="btn btn-secondary" style={{ fontSize: 12 }}
              onClick={genTitle} disabled={busy}>
              ✨ 下書きを作る
            </button>
            <input style={{ ...input, fontSize: 12, maxWidth: 240 }}
              value={push} onChange={e => setPush(e.target.value)}
              placeholder="推したい点（例: 立てて入る）※任意" />
            <span style={{ fontSize: 11, color: C.sub }}>
              ブランド名／メインキーワード／関連ワード／サイズ・数量・色 の順で
              65字程度にまとめます（75字まではOK）
            </span>
          </div>
        </div>

        <div style={{ marginBottom: 10 }}>
          <span style={label}>
            検索キーワード（Amazonの検索キーワード欄にそのまま入ります）
            <Count n={kwBytes} max={500} unit="バイト" />
          </span>
          <textarea style={{
            ...input, minHeight: 56,
            borderColor: kwBytes >= 500 ? C.bad : C.line,
          }} value={d.keywords || ''}
            onChange={e => set('keywords', e.target.value)}
            placeholder="半角スペース区切り。タイトルにある語は入れなくて構いません" />
          <div style={{ fontSize: 11, color: C.sub, marginTop: 3 }}>
            上限はカテゴリーで違います（多くは500バイト未満、服・シューズ・
            ジュエリー・時計は250バイト未満）
          </div>
        </div>

        <Bullets value={d.bullets || []} onChange={v => set('bullets', v)} />

        <div>
          <span style={label}>商品説明</span>
          <textarea style={{ ...input, minHeight: 90 }}
            value={d.description || ''}
            onChange={e => set('description', e.target.value)}
            placeholder="HTMLタグは使えません" />
        </div>
      </section>

      {/* ---- 出品の中身 ---- */}
      <section style={{ ...card, marginBottom: 10 }}>
        <H t="出品の中身" />
        <div style={{ display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10 }}>
          <F l="ブランド名" v={d.brand} on={v => set('brand', v)}
            ph="Aqualiora" />
          <F l="価格（円）" v={d.price} on={v => set('price', v ? +v : null)}
            type="number" />
          <F l="参考にする競合ASIN" v={d.rival_asin}
            on={v => set('rival_asin', v)} ph="B0XXXXXXXX" />
          <F l="長辺 (cm)" v={d.len_a} on={v => set('len_a', v ? +v : null)}
            type="number" />
          <F l="中辺 (cm)" v={d.len_b} on={v => set('len_b', v ? +v : null)}
            type="number" />
          <F l="短辺 (cm)" v={d.len_c} on={v => set('len_c', v ? +v : null)}
            type="number" />
          <F l="実重量 (kg)" v={d.weight} on={v => set('weight', v ? +v : null)}
            type="number" />
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center',
          marginTop: 10, flexWrap: 'wrap' }}>
          <button className="btn btn-secondary" onClick={prepare} disabled={busy}>
            出品の準備（商品タイプを調べる・JANを発番）
          </button>
          {d.product_type && (
            <span style={{ fontSize: 12, color: C.sub }}>
              商品タイプ <b style={{ color: C.key }}>{d.product_type}</b>
            </span>
          )}
        </div>
      </section>

      {/* ---- バリエーションとSKU ---- */}
      <Variations d={d} set={set} nextSku={nextSku} />

      {/* ---- 画像 ---- */}
      <Images listingId={listingId} images={d.images || []}
        onChanged={load} />

      {/* ---- 商品タイプごとの必須項目 ---- */}
      {fields && fields.length > 0 && (
        <section style={{ ...card, marginBottom: 10 }}>
          <H t="この商品タイプで必要な項目" />
          <div style={{ display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 10 }}>
            {fields.map(f => (
              <div key={f.name}>
                <span style={label}>{f.label || f.name}</span>
                {f.type === 'select' && (f.choices || []).length ? (
                  <select style={input} value={(d.attrs || {})[f.name] || ''}
                    onChange={e => set('attrs',
                      { ...(d.attrs || {}), [f.name]: e.target.value })}>
                    <option value="">（選ぶ）</option>
                    {f.choices.map(c => <option key={c} value={c}>{c}</option>)}
                  </select>
                ) : (
                  <input style={input} value={(d.attrs || {})[f.name] || ''}
                    onChange={e => set('attrs',
                      { ...(d.attrs || {}), [f.name]: e.target.value })} />
                )}
              </div>
            ))}
          </div>
        </section>
      )}
      {fields && !fields.length && (
        <div style={{ ...card, marginBottom: 10, fontSize: 12, color: C.good }}>
          この商品タイプで追加の入力は要りません。
        </div>
      )}

      {/* ---- 送信 ---- */}
      <section style={{ ...card, marginBottom: 30, display: 'flex',
        gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <button className="btn btn-secondary" onClick={() => submit(true)}
          disabled={busy}>
          送る中身を見る（送信しません）
        </button>
        <button className="btn btn-primary" onClick={() => submit(false)}
          disabled={busy || problems.some(p => !p.includes('画像がありません'))}>
          Amazonへ出品する
        </button>
        {sent && <span style={{ fontSize: 12, color: C.good }}>
          送信済みです。もう一度送ると差し替えになります
        </span>}
        {problems.some(p => !p.includes('画像がありません')) && (
          <span style={{ fontSize: 12, color: C.warn }}>
            足りないところがあるので、まだ出品できません
          </span>
        )}
      </section>

      {result && <ResultPanel r={result} onClose={() => setResult(null)} />}
    </div>
  )
}

/* ---------- 部品 ---------- */

function H({ t, note }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ fontSize: 13, fontWeight: 700, color: C.text }}>{t}</div>
      {note && <div style={{ fontSize: 11, color: C.sub, marginTop: 2 }}>{note}</div>}
    </div>
  )
}

function Sep() {
  return <span style={{ margin: '0 5px', color: C.line }}>／</span>
}

function Count({ n, max, unit }) {
  const over = n > max || (unit === 'バイト' && n >= max)
  return (
    <span style={{ float: 'right', fontWeight: 400,
      color: over ? C.bad : n ? C.sub : C.line }}>
      {n} / {max}{unit}
    </span>
  )
}

function F({ l, v, on, type = 'text', ph }) {
  return (
    <div>
      <span style={label}>{l}</span>
      <input style={input} type={type} value={v ?? ''} placeholder={ph}
        onChange={e => on(e.target.value)} />
    </div>
  )
}

/** 要点（箇条書き）。1行ずつ字数を出す */
function Bullets({ value, onChange }) {
  const list = value.length ? value : ['']
  const put = (i, v) => {
    const a = [...list]; a[i] = v
    onChange(a.filter((x, n) => x.trim() || n < a.length - 1))
  }
  return (
    <div style={{ marginBottom: 10 }}>
      <span style={label}>商品の要点（Amazonの箇条書き。5個まで）</span>
      {list.slice(0, 5).map((b, i) => (
        <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'center',
          marginBottom: 4 }}>
          <span style={{ fontSize: 11, color: C.sub, width: 16 }}>{i + 1}</span>
          <input style={input} value={b}
            onChange={e => put(i, e.target.value)} />
          <span style={{ fontSize: 11, width: 34, textAlign: 'right',
            color: (b || '').length > 200 ? C.bad : C.sub }}>
            {(b || '').length}
          </span>
        </div>
      ))}
      {list.length < 5 && (
        <button className="btn btn-secondary" style={{ fontSize: 12 }}
          onClick={() => onChange([...value, ''])}>＋ 行を足す</button>
      )}
    </div>
  )
}

/** バリエーションと、出品するSKUの一覧 */
function Variations({ d, set, nextSku }) {
  const kids = d.children || []
  const many = kids.length > 1 || !!d.variation_theme

  const putKid = (i, k, v) => {
    const a = kids.map((c, n) => n === i ? { ...c, [k]: v } : c)
    set('children', a)
  }
  const add = () => set('children', [...kids,
    { id: null, sku: null, title: d.title || '', axis1: '', axis2: '' }])
  const del = i => set('children', kids.filter((c, n) => n !== i))

  // 軸は常に「色」。個数違いも「2個/ブラック」のように色の値として書く
  const two = false
  const a1 = '色'
  const a2 = ''

  return (
    <section style={{ ...card, marginBottom: 10 }}>
      <H t="バリエーションと出品するSKU"
        note="単品ならSKUは1つ。バリエーションは親を1つ作り、その下に子を並べます" />

      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap',
        marginBottom: 10 }}>
        <div style={{ maxWidth: 160 }}>
          <span style={label}>親SKU</span>
          <input style={input} value={d.parent_sku || ''}
            placeholder={nextSku || 'a05'}
            onChange={e => set('parent_sku', e.target.value.trim())} />
          <div style={{ fontSize: 11, color: C.sub, marginTop: 3 }}>
            単品でも親を作ります（Amazonの推奨）
          </div>
        </div>
      <div style={{ maxWidth: 380 }}>
        <span style={label}>バリエーションの軸</span>
        <div style={{ ...input, background: C.soft, color: C.sub,
          display: 'flex', alignItems: 'center' }}>
          色（固定）
        </div>
        <div style={{ fontSize: 11, color: C.sub, marginTop: 3 }}>
          色でないと選択肢ごとの画像が出ないため、個数違い・サイズ違いも
          色として登録します（例: 2個/ブラック）
        </div>
      </div>
      </div>

      {/* 表は幅を取るので、枠の中だけで横スクロールさせる。
          overflow-x だけでは枠の「縮められない幅」が表の最小幅のままになり、
          画面全体が横に伸びてしまう。grid の minmax(0,1fr) で包んで防ぐ */}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)' }}>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse',
          minWidth: 640 }}>
          <thead>
            <tr style={{ color: C.sub, textAlign: 'left' }}>
              <th style={th}>SKU</th>
              <th style={th}>JAN</th>
              <th style={th}>商品タイトル</th>
              {many && <th style={{ ...th, width: 110 }}>{a1}</th>}
              {many && two && <th style={{ ...th, width: 110 }}>{a2}</th>}
              <th style={{ ...th, width: 86 }}>価格</th>
              <th style={{ ...th, width: 74 }}>状態</th>
              <th style={{ ...th, width: 30 }}></th>
            </tr>
          </thead>
          <tbody>
            {kids.map((c, i) => (
              <tr key={c.id ?? `n${i}`} style={{ borderTop: `1px solid ${C.line}` }}>
                <td style={td}>
                  {/* 番号は「出品の準備」で自動採番するが、
                      振り直したいこともあるので直せるようにしてある */}
                  <input style={{ ...input, fontSize: 12,
                    color: c.sku ? C.text : C.sub }}
                    value={c.sku || ''} placeholder={nextSku || 'a05'}
                    onChange={e => putKid(i, 'sku', e.target.value.trim())} />
                </td>
                <td style={td}>
                  <span style={{ color: c.jan ? C.key : C.sub }}>
                    {c.jan || '（準備で発番）'}
                  </span>
                </td>
                <td style={td}>
                  <input style={{ ...input, fontSize: 12 }} value={c.title || ''}
                    onChange={e => putKid(i, 'title', e.target.value)} />
                </td>
                {many && (
                  <td style={td}>
                    <input style={{ ...input, fontSize: 12 }} value={c.axis1 || ''}
                      placeholder="ブラック ／ 2個/ブラック"
                      onChange={e => putKid(i, 'axis1', e.target.value)} />
                  </td>
                )}
                {many && two && (
                  <td style={td}>
                    <input style={{ ...input, fontSize: 12 }} value={c.axis2 || ''}
                      placeholder={a2}
                      onChange={e => putKid(i, 'axis2', e.target.value)} />
                  </td>
                )}
                <td style={td}>
                  <input style={{ ...input, fontSize: 12 }} type="number"
                    value={c.price ?? ''} placeholder={d.price ?? ''}
                    onChange={e => putKid(i, 'price',
                      e.target.value ? +e.target.value : null)} />
                </td>
                <td style={{ ...td, color: c.status === 'failed' ? C.bad
                  : c.status === 'submitted' ? C.good : C.sub }}>
                  {{ draft: '—', submitted: '送信済', failed: '失敗',
                    live: '公開中' }[c.status] || '—'}
                </td>
                <td style={td}>
                  {kids.length > 1 && !c.jan && (
                    <button className="btn btn-secondary" style={{ fontSize: 11,
                      padding: '2px 6px' }} onClick={() => del(i)}>×</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      </div>

      {kids.some(c => c.error) && (
        <div style={{ marginTop: 8 }}>
          {kids.filter(c => c.error).map(c => (
            <div key={c.id} style={{ fontSize: 11, color: C.bad }}>
              {c.sku}: {String(c.error).slice(0, 300)}
            </div>
          ))}
        </div>
      )}

      <button className="btn btn-secondary" style={{ fontSize: 12, marginTop: 8 }}
        onClick={add}>＋ バリエーションを足す</button>
    </section>
  )
}

const th = { padding: '4px 6px', fontWeight: 600 }
const td = { padding: '4px 6px', verticalAlign: 'middle' }

/** 商品画像。貼り付け・ドラッグ＆ドロップ・ファイル選択で入れる */
function Images({ listingId, images, onChanged }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const fileRef = useRef(null)

  const upload = useCallback(async (files) => {
    const list = [...files].filter(f => f.type.startsWith('image/'))
    if (!list.length) return
    setBusy(true); setErr('')
    try {
      for (const f of list) {
        const fd = new FormData()
        fd.append('file', f)
        await api.post(`/amazon-listings/${listingId}/images`, fd)
      }
      await onChanged()
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }, [listingId, onChanged])

  // 画面のどこで貼っても取り込む。1枚ずつ選ばせると手間なので
  useEffect(() => {
    const onPaste = e => {
      const fs = [...(e.clipboardData?.files || [])]
      if (fs.length) { e.preventDefault(); upload(fs) }
    }
    window.addEventListener('paste', onPaste)
    return () => window.removeEventListener('paste', onPaste)
  }, [upload])

  const remove = async (id) => {
    if (!confirm('この画像を消しますか？')) return
    setBusy(true)
    try {
      await api.delete(`/amazon-listings/images/${id}`)
      await onChanged()
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  const move = async (id, order) => {
    setBusy(true)
    try {
      await api.put(`/amazon-listings/images/${id}/order?sort_order=${order}`)
      await onChanged()
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  const base = (api.defaults.baseURL || '').replace(/\/api$/, '')

  return (
    <section style={{ ...card, marginBottom: 10 }}
      onDragOver={e => e.preventDefault()}
      onDrop={e => { e.preventDefault(); upload(e.dataTransfer.files) }}>
      <H t="商品画像"
        note="1枚目がメイン画像になります。Ctrl+V で貼り付け、ドラッグ＆ドロップ、ファイル選択のどれでも入ります" />
      {err && <Err text={err} />}

      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap',
        alignItems: 'flex-start' }}>
        {images.map((im, i) => (
          <div key={im.id} style={{ width: 96 }}>
            <div style={{ position: 'relative', width: 96, height: 96,
              border: `1px solid ${i === 0 ? C.key : C.line}`, borderRadius: 6,
              overflow: 'hidden', background: '#fff' }}>
              <img src={base + im.url} alt="" style={{ width: '100%',
                height: '100%', objectFit: 'contain' }} />
              {i === 0 && (
                <span style={{ position: 'absolute', top: 0, left: 0,
                  background: C.key, color: '#fff', fontSize: 10,
                  padding: '1px 5px', borderBottomRightRadius: 5 }}>メイン</span>
              )}
            </div>
            <div style={{ display: 'flex', gap: 3, marginTop: 3 }}>
              {i > 0 && (
                <button className="btn btn-secondary" disabled={busy}
                  style={mini} onClick={() => move(im.id, -1)}>← 先頭</button>
              )}
              <button className="btn btn-secondary" disabled={busy}
                style={{ ...mini, marginLeft: 'auto', color: C.bad }}
                onClick={() => remove(im.id)}>削除</button>
            </div>
          </div>
        ))}

        <div onClick={() => fileRef.current?.click()}
          style={{ width: 96, height: 96, border: `1px dashed ${C.line}`,
            borderRadius: 6, display: 'flex', alignItems: 'center',
            justifyContent: 'center', cursor: 'pointer', color: C.sub,
            fontSize: 12, textAlign: 'center', background: C.soft }}>
          {busy ? '入れています…' : '＋ 画像を\n追加'}
        </div>
        <input ref={fileRef} type="file" accept="image/*" multiple
          style={{ display: 'none' }}
          onChange={e => { upload(e.target.files); e.target.value = '' }} />
      </div>
    </section>
  )
}

const mini = { fontSize: 10, padding: '1px 5px' }

/** 判断根拠。リサーチで調べたことを、書きながら見られるように上に置く */
function Basis({ d }) {
  const cell = { flex: '1 1 110px', minWidth: 100 }
  const num = { fontSize: 15, fontWeight: 700, color: C.text }
  const cap = { fontSize: 11, color: C.sub }
  return (
    <section style={{ ...card, marginBottom: 10, display: 'flex', gap: 14,
      alignItems: 'center', flexWrap: 'wrap' }}>
      {d.rival_image && (
        <img src={d.rival_image} alt="" style={{ width: 64, height: 64,
          objectFit: 'contain', border: `1px solid ${C.line}`,
          borderRadius: 6, background: '#fff' }} />
      )}
      <div style={cell}>
        <div style={cap}>競合ASIN</div>
        <div style={{ ...num, fontSize: 13, color: C.key }}>
          {d.rival_asin
            ? <a href={`https://www.amazon.co.jp/dp/${d.rival_asin}`}
              target="_blank" rel="noreferrer"
              style={{ color: C.key }}>{d.rival_asin} ↗</a>
            : '—'}
        </div>
      </div>
      <div style={cell}>
        <div style={cap}>月間販売個数</div>
        <div style={num}>{d.monthly_sales ?? '—'}</div>
      </div>
      <div style={cell}>
        <div style={cap}>レビュー</div>
        <div style={num}>{d.review_count ?? '—'}
          <span style={{ fontSize: 12, color: C.sub }}>
            {d.review_rate ? ` ★${d.review_rate}` : ''}</span>
        </div>
      </div>
      <div style={cell}>
        <div style={cap}>粗利率</div>
        <div style={{ ...num,
          color: d.profit_rate == null ? C.sub
            : d.profit_rate >= 30 ? C.good
              : d.profit_rate >= 20 ? C.warn : C.bad }}>
          {d.profit_rate == null ? '—' : `${d.profit_rate}%`}
        </div>
      </div>
      <div style={{ ...cell, marginLeft: 'auto', textAlign: 'right' }}>
        <div style={cap}>シートから取り込み</div>
        <div style={{ fontSize: 12, color: C.sub }}>
          {d.synced_at ? new Date(d.synced_at).toLocaleString('ja-JP') : '—'}
        </div>
      </div>
    </section>
  )
}

/** 送信の結果。dry-run のときは送る中身をそのまま出す */
function ResultPanel({ r, onClose }) {
  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.5)',
      zIndex: 1000, display: 'flex', alignItems: 'center',
      justifyContent: 'center', padding: 20 }}
      onClick={onClose}>
      <div style={{ background: '#fff', borderRadius: 10, padding: 18,
        maxWidth: 940, width: '100%', maxHeight: '86vh', overflow: 'auto' }}
        onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 10 }}>
          <h3 style={{ margin: 0, fontSize: 15 }}>
            {r.sent?.[0]?.dry_run ? '送る中身（送信していません）' : '出品の結果'}
          </h3>
          <button className="btn btn-secondary" style={{ marginLeft: 'auto' }}
            onClick={onClose}>閉じる</button>
        </div>

        {r.error && <Err text={r.error} />}
        {(r.problems || []).length > 0 && (
          <div style={{ background: '#fffbeb', border: '1px solid #fde68a',
            padding: 9, borderRadius: 6, marginBottom: 10, fontSize: 12,
            color: '#92400e' }}>
            {r.problems.map((p, i) => <div key={i}>・{p}</div>)}
          </div>
        )}

        {(r.sent || []).map((s, i) => (
          <div key={i} style={{ border: `1px solid ${C.line}`, borderRadius: 6,
            padding: 10, marginBottom: 8 }}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 5 }}>
              {s.kind} ／ SKU {s.sku}
              {s.jan && <span style={{ color: C.sub, fontWeight: 400 }}>
                {' '}／ JAN {s.jan}</span>}
              {s.status && <span style={{ marginLeft: 8,
                color: s.ok ? C.good : C.bad }}>{s.status}</span>}
            </div>
            {(s.issues || []).map((is, n) => (
              <div key={n} style={{ fontSize: 12,
                color: is.severity === 'ERROR' ? C.bad : C.warn }}>
                ・{is.message}
              </div>
            ))}
            {s.error && <div style={{ fontSize: 12, color: C.bad }}>
              {String(s.error).slice(0, 500)}</div>}
            <details style={{ marginTop: 6 }}>
              <summary style={{ fontSize: 12, color: C.sub, cursor: 'pointer' }}>
                送る中身を見る
              </summary>
              <pre style={{ fontSize: 11, background: C.soft, padding: 8,
                borderRadius: 4, overflow: 'auto', maxHeight: 260, margin: '6px 0 0' }}>
                {JSON.stringify(s.attributes, null, 2)}
              </pre>
            </details>
          </div>
        ))}
      </div>
    </div>
  )
}

/** リサーチで集めた材料。競合の商品仕様・レビュー・分析の結果を、
 *  出品原稿を書きながら読めるように置いておく。
 *  長いので既定は畳んである。 */
function Notes({ notes }) {
  const [open, setOpen] = useState('')
  if (!notes) return null

  const items = []
  Object.entries(notes).forEach(([id, n]) => {
    ;[['spec', '競合の商品仕様'], ['reviews', 'レビュー'],
      ['keywords', '競合のキーワード'], ['imgtext', '商品画像の文字'],
      ['analysis', '分析の結果']].forEach(([k, label]) => {
      if ((n[k] || '').trim()) items.push({ key: id + k, label, text: n[k] })
    })
  })
  if (!items.length) {
    return (
      <section style={{ ...card, marginBottom: 10, fontSize: 12, color: C.sub }}>
        競合の商品仕様・レビュー・分析の結果は、まだありません。
        競合リサーチシートの「📋 商品仕様・レビュー・キーワード」で集めると、
        ここに出て出品原稿の材料に使えます。
      </section>
    )
  }

  return (
    <section style={{ ...card, marginBottom: 10 }}>
      <H t="リサーチで集めた材料"
        note="出品原稿を書くときの元ネタです。押すと中身が開きます" />
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {items.map(it => (
          <button key={it.key} className="btn btn-secondary"
            style={{ fontSize: 12 }}
            onClick={() => setOpen(open === it.key ? '' : it.key)}>
            {open === it.key ? '▲ ' : '▼ '}{it.label}
            <span style={{ color: C.sub }}>
              {' '}{it.text.length.toLocaleString('ja-JP')}字
            </span>
          </button>
        ))}
      </div>
      {items.filter(it => it.key === open).map(it => (
        <pre key={it.key} style={{ marginTop: 8, fontSize: 12, lineHeight: 1.6,
          background: C.soft, border: `1px solid ${C.line}`, borderRadius: 6,
          padding: 10, maxHeight: 320, overflow: 'auto',
          whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
          {it.text}
        </pre>
      ))}
    </section>
  )
}
