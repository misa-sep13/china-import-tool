import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import api from '../api/client'
import ListingEditor from './ListingEditor'

/**
 * Amazon 商品登録（リサーチの3つ目のタブ）。
 *
 * これまでの登録画面は楽天用のドラフトを流用していて、リサーチで調べた
 * 情報が何ひとつ出ていなかった。ここでは競合リサーチシートを直接の元にし、
 * 判断根拠（販売個数・レビュー・粗利率）を見ながら出品内容を仕上げられる。
 *
 * シートの「🏷 出品原稿をつくる」がまだ使われていないため、タイトル・
 * 検索キーワード・要点はこの画面でも書けるようにしてある。
 */

const C = {
  line: '#e5e7eb', sub: '#64748b', text: '#0f172a',
  good: '#16a34a', warn: '#b45309', bad: '#dc2626',
  key: '#2563eb', soft: '#f8fafc',
}

const card = {
  background: '#fff', border: `1px solid ${C.line}`,
  borderRadius: 8, padding: 14,
}
const label = {
  display: 'block', fontSize: 12, color: C.sub, marginBottom: 4, fontWeight: 600,
}
const input = {
  width: '100%', padding: '7px 9px', border: `1px solid ${C.line}`,
  borderRadius: 6, fontSize: 13, boxSizing: 'border-box', color: C.text,
}

const bytes = s => new TextEncoder().encode(s || '').length

export default function ListingTab() {
  const [rows, setRows] = useState([])
  const [openId, setOpenId] = useState(null)      // listing_id
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [onlyReady, setOnlyReady] = useState(false)

  // 発番しただけではGS1に登録されない。溜まったら一括で届け出るので、
  // 未登録の件数をここに出しておく
  const [gs1, setGs1] = useState(null)

  const load = useCallback(async () => {
    setErr('')
    try {
      const [r, g] = await Promise.all([
        api.get('/amazon-listings'),
        api.get('/amazon-research/jan/gs1-pending').catch(() => null),
      ])
      setRows(r.data.rows || [])
      setGs1(g ? g.data : null)
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    }
  }, [])
  useEffect(() => { load() }, [load])

  const gs1Export = async () => {
    setBusy(true); setErr('')
    try {
      const r = await api.get('/amazon-research/jan/gs1-export',
        { responseType: 'blob' })
      const url = URL.createObjectURL(r.data)
      const a = document.createElement('a')
      a.href = url
      a.download = `gs1_${new Date().toISOString().slice(0, 10)}.xlsx`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  const gs1Done = async () => {
    if (!confirm(`未登録の${gs1.count}件に「GS1へ届け出済み」の印を付けます。`
      + 'よろしいですか？')) return
    setBusy(true); setErr('')
    try {
      await api.post('/amazon-research/jan/gs1-done', {})
      await load()
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  const start = async (researchId) => {
    setBusy(true); setErr('')
    try {
      const r = await api.post(`/amazon-listings/sync/${researchId}`)
      await load()
      setOpenId(r.data.id)
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  const shown = useMemo(
    () => onlyReady ? rows.filter(r => r.listing_id) : rows,
    [rows, onlyReady])

  if (openId) {
    return <ListingEditor listingId={openId}
      onBack={() => { setOpenId(null); load() }} />
  }

  return (
    <div style={{ overflow: 'auto', height: '100%', padding: 2, minWidth: 0 }}>
      {err && <Err text={err} />}

      <div style={{ ...card, marginBottom: 10, display: 'flex',
        alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 13 }}>
          採用したリサーチ <b>{rows.length}</b> 件 ／ 登録を始めたもの{' '}
          <b>{rows.filter(r => r.listing_id).length}</b> 件
        </div>
        <label style={{ fontSize: 12, color: C.sub, display: 'flex',
          alignItems: 'center', gap: 5 }}>
          <input type="checkbox" checked={onlyReady}
            onChange={e => setOnlyReady(e.target.checked)} />
          登録を始めたものだけ
        </label>
        <div style={{ marginLeft: 'auto', fontSize: 12, color: C.sub }}>
          粗利率は競合リサーチシートと同じ計算です
        </div>
      </div>

      {gs1 && gs1.count > 0 && (
        <div style={{ ...card, marginBottom: 10, background: '#fffbeb',
          borderColor: '#fde68a', display: 'flex', alignItems: 'center',
          gap: 10, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 13, color: '#92400e' }}>
            GS1へ未登録のJANが <b>{gs1.count}</b> 件あります
            （発番しただけでは登録されません）
          </span>
          <button className="btn btn-secondary" style={{ fontSize: 12 }}
            onClick={gs1Export} disabled={busy}>
            📄 一括登録フォームを書き出す
          </button>
          <button className="btn btn-secondary" style={{ fontSize: 12 }}
            onClick={gs1Done} disabled={busy}>
            ✅ 届け出済みにする
          </button>
          <span style={{ fontSize: 11, color: C.sub, width: '100%' }}>
            カナ・取扱品目コード・JICFS分類・GPC分類は商品ごとに違うので空のまま出ます。
            入れてからGS1の画面へ上げてください
          </span>
        </div>
      )}

      <div style={{ display: 'grid', gap: 8 }}>
        {shown.map(r => (
          <ListRow key={r.research_id} r={r} busy={busy}
            onStart={() => start(r.research_id)}
            onOpen={() => setOpenId(r.listing_id)} />
        ))}
        {!shown.length && (
          <div style={{ ...card, color: C.sub, fontSize: 13, lineHeight: 1.7 }}>
            出せるリサーチがありません。<br />
            リサーチシートで枠の状態を<b>「採用」</b>にすると、ここに出てきます
            （採用・発注済み・画像依頼済み・商品登録済みが対象です）。
          </div>
        )}
      </div>
    </div>
  )
}

function Err({ text }) {
  return (
    <div style={{ background: '#fef2f2', border: '1px solid #fecaca',
      color: '#991b1b', padding: 10, borderRadius: 6, marginBottom: 10,
      fontSize: 13, whiteSpace: 'pre-wrap' }}>{text}</div>
  )
}

/** 一覧の1行。リサーチの判断根拠と、原稿の仕上がり具合を出す */
function ListRow({ r, onStart, onOpen, busy }) {
  const done = !!r.listing_id
  const st = {
    draft: { l: '下書き', c: C.sub },
    prepared: { l: '準備済み', c: C.key },
    ready: { l: '出品待ち', c: C.key },
    submitted: { l: '送信済み', c: C.good },
    live: { l: '公開中', c: C.good },
    failed: { l: '失敗', c: C.bad },
  }[r.listing_status] || null

  return (
    <div style={{ ...card, display: 'flex', gap: 12, alignItems: 'flex-start' }}>
      {r.rival_image
        ? <img src={r.rival_image} alt="" style={{ width: 56, height: 56,
            objectFit: 'contain', border: `1px solid ${C.line}`, borderRadius: 6,
            flexShrink: 0, background: '#fff' }} />
        : <div style={{ width: 56, height: 56, border: `1px dashed ${C.line}`,
            borderRadius: 6, flexShrink: 0 }} />}

      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: C.text,
          whiteSpace: 'normal', display: '-webkit-box',
          WebkitLineClamp: 1, WebkitBoxOrient: 'vertical',
          overflow: 'hidden' }}>
          {r.research_title || '(名前なし)'}
        </div>

        <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap',
          fontSize: 12, color: C.sub, marginTop: 5 }}>
          <span>ASIN <b style={{ color: C.key }}>{r.rival_asin || '—'}</b></span>
          <span>月間 <b style={{ color: C.text }}>{r.monthly_sales ?? '—'}</b>個</span>
          <span>レビュー <b style={{ color: C.text }}>{r.review_count ?? '—'}</b>件
            {r.review_rate ? ` ★${r.review_rate}` : ''}</span>
          <span>売価 <b style={{ color: C.text }}>
            {r.price ? `¥${r.price.toLocaleString()}` : '—'}</b></span>
          <span>粗利率 <b style={{
            color: r.profit_rate == null ? C.sub
              : r.profit_rate >= 30 ? C.good
                : r.profit_rate >= 20 ? C.warn : C.bad,
          }}>{r.profit_rate == null ? '—' : `${r.profit_rate}%`}</b>
            {r.cost_missing?.length
              ? <span style={{ color: C.warn }}>（{r.cost_missing.join('・')}が未入力）</span>
              : null}
          </span>
        </div>

        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 6 }}>
          <Chip on={r.has_title} label="タイトル" />
          <Chip on={r.has_keywords} label="検索KW" />
          <Chip on={r.bullet_count > 0} label={`要点${r.bullet_count || 0}行`} />
          {r.child_count > 0 &&
            <Chip on label={`バリエーション${r.child_count}`} />}
          {r.status_label && (
            <span style={{ fontSize: 11, color: '#2563eb', fontWeight: 600,
              padding: '2px 8px', border: '1px solid #bfdbfe',
              background: '#eff6ff', borderRadius: 10 }}>
              {r.status_label}
            </span>
          )}
          {st && <span style={{ fontSize: 11, color: st.c, fontWeight: 600,
            padding: '2px 8px', border: `1px solid ${st.c}`, borderRadius: 10 }}>
            {st.l}</span>}
        </div>
      </div>

      <button className={`btn ${done ? 'btn-primary' : 'btn-secondary'}`}
        disabled={busy} onClick={done ? onOpen : onStart}
        style={{ flexShrink: 0, whiteSpace: 'nowrap' }}>
        {done ? '開く' : '登録を始める'}
      </button>
    </div>
  )
}

function Chip({ on, label }) {
  return (
    <span style={{
      fontSize: 11, padding: '2px 7px', borderRadius: 10,
      background: on ? '#ecfdf5' : C.soft,
      color: on ? C.good : C.sub,
      border: `1px solid ${on ? '#a7f3d0' : C.line}`,
    }}>{on ? '✓' : '—'} {label}</span>
  )
}

export { C, card, label, input, bytes, Err }
