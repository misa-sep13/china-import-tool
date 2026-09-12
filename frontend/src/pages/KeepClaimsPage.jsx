import { useCallback, useEffect, useMemo, useState } from 'react'
import api from '../api/client'

/**
 * 商品キープ（被り防止）。
 *
 * 2人で同じ商品を見ているので、先に登録したほうが独占権を取る。
 * スプレッドシートでやっていたものを移した。ルールは相手と決めたもの:
 *
 *   1. 早い者勝ち
 *   2. 親ASIN単位で独占（色違い・サイズ違いも丸ごと。相乗りNG）
 *   3. キープ枠は1人7個まで。代行会社から発送された時点で枠が空く
 *   4. 60日以内に発送できなければ独占権は消滅
 *
 * URLを貼るだけで登録でき、被っていればその場で止める。
 * ASINで見分けるので、色違いのページを貼っても同じ商品として当たる。
 */

const C = {
  line: '#e5e7eb', sub: '#64748b', text: '#0f172a',
  good: '#16a34a', warn: '#b45309', bad: '#dc2626', key: '#2563eb',
}

const card = {
  background: '#fff', border: `1px solid ${C.line}`,
  borderRadius: 8, padding: 14,
}

const STATUS = {
  keep: { label: '⏳ キープ中', color: C.key, bg: '#eff6ff' },
  shipped: { label: '✅ 発送済（枠解放）', color: C.good, bg: '#f0fdf4' },
  expired: { label: '❌ 期限切れ（消滅）', color: C.bad, bg: '#fef2f2' },
  released: { label: '🔓 取り下げ', color: C.sub, bg: '#f8fafc' },
}

/** 残り日数の色。近いほど強く出す */
function leftColor(d) {
  if (d <= 7) return C.bad
  if (d <= 14) return C.warn
  return C.sub
}

export default function KeepClaimsPage({ share = '' }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [filter, setFilter] = useState('keep')

  // 誰として登録するか。毎回選ぶのは面倒なので覚えておく
  // 自分はY。共有ページで相手が開いたときは、選び直してもらう
  const [owner, setOwner] = useState(
    () => localStorage.getItem('keep_owner') || (share ? '' : 'Y'))
  const [url, setUrl] = useState('')
  const [title, setTitle] = useState('')
  const [supplierUrl, setSupplierUrl] = useState('')
  const [memo, setMemo] = useState('')
  const [checked, setChecked] = useState(null)

  // 共有ページはログインしていないので、合言葉を付けて呼ぶ
  const q = useCallback(
    (path) => (share ? path + (path.includes('?') ? '&' : '?')
      + 'share=' + encodeURIComponent(share) : path), [share])

  const load = useCallback(async () => {
    setErr('')
    try {
      const r = await api.get(q('/keep-claims'))
      setData(r.data)
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    }
  }, [q])
  useEffect(() => { load() }, [load])

  useEffect(() => {
    if (owner) localStorage.setItem('keep_owner', owner)
  }, [owner])

  // URLを貼った時点で、被っていないか先に見る。
  // 登録してから怒られるより、貼った瞬間に分かるほうがよい
  useEffect(() => {
    const u = url.trim()
    if (!u) { setChecked(null); return }
    let alive = true
    const t = setTimeout(async () => {
      try {
        const r = await api.post(q('/keep-claims/check'), { owner: owner || '-', url: u })
        if (alive) setChecked(r.data)
      } catch { /* 判定できなくても登録はできる */ }
    }, 600)
    return () => { alive = false; clearTimeout(t) }
  }, [url, owner])

  const add = async () => {
    if (!owner.trim()) { setErr('担当者を選んでください'); return }
    if (!url.trim()) { setErr('URLを入れてください'); return }
    setBusy(true); setErr('')
    try {
      await api.post(q('/keep-claims'), {
        owner: owner.trim(), url: url.trim(), title: title.trim(),
        supplier_url: supplierUrl.trim(), memo: memo.trim(),
      })
      setUrl(''); setTitle(''); setSupplierUrl(''); setMemo(''); setChecked(null)
      await load()
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  const act = async (id, path, confirmText) => {
    if (confirmText && !confirm(confirmText)) return
    setBusy(true); setErr('')
    try {
      await api.post(q(`/keep-claims/${id}/${path}`))
      await load()
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  // リサーチシートで採用にしたものを取り込む。自分が採用した商品は、
  // 相手にも押さえたと伝わっている必要がある
  const syncAdopted = async () => {
    setBusy(true); setErr('')
    try {
      const r = await api.post(q(`/keep-claims/sync-adopted?owner=${encodeURIComponent(owner || 'Y')}`))
      const n = r.data.added || 0
      if (n) await load()
      alert(n ? `${n}件をリサーチシートから取り込みました`
        : '新しく取り込むものはありませんでした')
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  const remove = async (id) => {
    if (!confirm('この記録を消しますか？（誰が何を見ていたか分からなくなります）')) return
    setBusy(true)
    try {
      await api.delete(q(`/keep-claims/${id}`))
      await load()
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  // 期限が2週間を切ったキープ。並びは新しい順なので、これだけ別に数える
  const soon = useMemo(
    () => (data?.items || []).filter(
      x => x.status === 'keep' && x.days_left <= 14),
    [data])

  const items = useMemo(() => {
    const all = data?.items || []
    if (filter === 'all') return all
    if (filter === 'soon') {
      return [...soon].sort((a, b) => a.days_left - b.days_left)
    }
    return all.filter(x => x.status === filter)
  }, [data, filter, soon])

  const owners = useMemo(() => {
    const s = new Set(['C', 'Y'])
    ;(data?.items || []).forEach(x => x.owner && s.add(x.owner))
    return [...s]
  }, [data])

  return (
    <div style={{ overflow: 'auto', height: '100%', padding: 2, minWidth: 0 }}>
      {err && (
        <div style={{ background: '#fef2f2', border: '1px solid #fecaca',
          color: '#991b1b', padding: 10, borderRadius: 6, marginBottom: 10,
          fontSize: 13, whiteSpace: 'pre-wrap' }}>{err}</div>
      )}

      {/* 登録。URLを貼るだけで済むようにする */}
      <div style={{ ...card, marginBottom: 10 }}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap',
          alignItems: 'center' }}>
          <select value={owner} onChange={e => setOwner(e.target.value)}
            style={{ width: 'auto', fontSize: 13, padding: '7px 9px',
              border: `1px solid ${owner ? C.line : C.bad}`, borderRadius: 6 }}>
            <option value="">担当</option>
            {owners.map(o => <option key={o} value={o}>{o}</option>)}
          </select>
          <input type="text" value={url} onChange={e => setUrl(e.target.value)}
            placeholder="AmazonのURL（短縮URLでもOK）"
            onKeyDown={e => { if (e.key === 'Enter' && !checked?.taken) add() }}
            style={{ flex: 1, minWidth: 260, fontSize: 13, padding: '7px 9px',
              border: `1px solid ${C.line}`, borderRadius: 6 }} />
          <button className="btn btn-primary" onClick={add}
            disabled={busy || !url.trim() || !owner}>
            キープする
          </button>
        </div>

        {/* 貼った瞬間に被りを知らせる */}
        {checked && (
          <div style={{ marginTop: 8, fontSize: 12,
            color: checked.taken ? C.bad : C.good }}>
            {checked.warning ? (
              <span style={{ color: C.warn }}>{checked.warning}</span>
            ) : checked.taken ? (
              <>❌ すでに <b>{checked.by.owner}</b> さんがキープしています
                （{new Date(checked.by.claimed_at).toLocaleString('ja-JP')}／
                {STATUS[checked.by.status]?.label}）</>
            ) : (
              <>✅ まだ誰も取っていません（{checked.asin}）</>
            )}
          </div>
        )}

        <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
          <input type="text" value={title} onChange={e => setTitle(e.target.value)}
            placeholder="商品名（任意）"
            style={{ flex: 1, minWidth: 180, fontSize: 12, padding: '6px 8px',
              border: `1px solid ${C.line}`, borderRadius: 6 }} />
          <input type="text" value={supplierUrl}
            onChange={e => setSupplierUrl(e.target.value)}
            placeholder="1688のURL（任意）"
            style={{ flex: 1, minWidth: 180, fontSize: 12, padding: '6px 8px',
              border: `1px solid ${C.line}`, borderRadius: 6 }} />
          <input type="text" value={memo} onChange={e => setMemo(e.target.value)}
            placeholder="メモ（任意）"
            style={{ flex: 1, minWidth: 140, fontSize: 12, padding: '6px 8px',
              border: `1px solid ${C.line}`, borderRadius: 6 }} />
        </div>
      </div>

      {/* 枠の使用状況と絞り込み */}
      <div style={{ ...card, marginBottom: 10, display: 'flex', gap: 14,
        alignItems: 'center', flexWrap: 'wrap' }}>
        <div style={{ fontSize: 13 }}>
          キープ枠{' '}
          {owners.map(o => {
            const used = data?.used?.[o] || 0
            const over = used > (data?.limit || 7)
            return (
              <span key={o} style={{ marginRight: 12 }}>
                <b>{o}</b>{' '}
                <b style={{ color: over ? C.bad : C.text }}>{used}</b>
                <span style={{ color: C.sub }}> / {data?.limit || 7}</span>
              </span>
            )
          })}
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          {[['keep', 'キープ中'], ['shipped', '発送済'],
            ['expired', '期限切れ'], ['all', 'すべて']].map(([k, l]) => (
            <button key={k} onClick={() => setFilter(k)}
              className={`btn ${filter === k ? 'btn-primary' : 'btn-secondary'}`}
              style={{ fontSize: 12, padding: '4px 10px' }}>
              {l}{k !== 'all' && ` ${data?.counts?.[k] ?? 0}`}
            </button>
          ))}
        </div>
        {/* 新しい順に並べているので、期限が近いものは下に埋もれる。
            件数だけ先に知らせて、見落とさないようにする */}
        {soon.length > 0 && (
          <button onClick={() => setFilter('soon')}
            className={`btn ${filter === 'soon' ? 'btn-primary' : 'btn-secondary'}`}
            style={{ fontSize: 12, padding: '4px 10px',
              color: filter === 'soon' ? '#fff' : C.bad, fontWeight: 700 }}>
            期限が近い {soon.length}
          </button>
        )}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6,
          alignItems: 'center' }}>
          {/* 共有ページからは触らせない。自分のシートの話なので */}
          {!share && (
            <button className="btn btn-secondary" disabled={busy}
              onClick={syncAdopted}
              style={{ fontSize: 11, padding: '3px 8px' }}
              title="競合リサーチシートで採用にしたものを、ここに取り込む">
              採用したものを取り込む
            </button>
          )}
          <span style={{ fontSize: 11, color: C.sub }}>
            親ASIN単位で独占／{data?.limit_days || 60}日以内に発送しないと消滅
          </span>
        </div>
      </div>

      <div style={{ display: 'grid', gap: 8 }}>
        {items.map(r => (
          <Row key={r.id} r={r} busy={busy}
            onShip={() => act(r.id, 'ship')}
            onRelease={() => act(r.id, 'release',
              '独占を手放します。相手が仕入れられるようになります。よろしいですか？')}
            onDelete={() => remove(r.id)} />
        ))}
        {!items.length && (
          <div style={{ ...card, color: C.sub, fontSize: 13, lineHeight: 1.7 }}>
            {filter === 'keep'
              ? 'キープ中の商品はありません。上のURL欄に貼って登録してください。'
              : filter === 'soon'
                ? '期限が近いものはありません。'
                : 'この状態の商品はありません。'}
          </div>
        )}
      </div>
    </div>
  )
}

function Row({ r, busy, onShip, onRelease, onDelete }) {
  const st = STATUS[r.status] || STATUS.keep
  const keeping = r.status === 'keep'
  return (
    <div style={{ ...card, background: st.bg, display: 'flex', gap: 12,
      alignItems: 'flex-start' }}>
      {/* 商品写真。URLとASINだけでは何の商品か分からない */}
      {r.image_url ? (
        <a href={r.url} target="_blank" rel="noreferrer" style={{ flexShrink: 0 }}>
          <img src={r.image_url} alt="" loading="lazy"
            onError={e => { e.currentTarget.style.visibility = 'hidden' }}
            style={{ width: 64, height: 64, objectFit: 'contain',
              background: '#fff', border: `1px solid ${C.line}`,
              borderRadius: 6, display: 'block' }} />
        </a>
      ) : (
        <div style={{ width: 64, height: 64, flexShrink: 0,
          border: `1px dashed ${C.line}`, borderRadius: 6 }} />
      )}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center',
          flexWrap: 'wrap' }}>
          <b style={{ fontSize: 13, color: st.color }}>{st.label}</b>
          <span style={{ fontSize: 13, fontWeight: 700 }}>{r.owner}</span>
          {keeping && (
            <span style={{ fontSize: 12, color: leftColor(r.days_left),
              fontWeight: r.days_left <= 14 ? 700 : 400 }}>
              あと {r.days_left}日（{r.days_elapsed}日経過）
            </span>
          )}
          {r.status === 'shipped' && r.shipped_at && (
            <span style={{ fontSize: 12, color: C.sub }}>
              {r.shipped_at} 発送（{r.days_elapsed}日）
            </span>
          )}
          {r.research_id && (
            <span style={{ fontSize: 11, color: C.good }}>
              リサーチ採用ぶん
            </span>
          )}
        </div>

        {/* URLは長いと3行占領して読めなくなる。商品名が無ければ
            ASINを見出しにし、リンクは1行に収める */}
        <div style={{ fontSize: 13, marginTop: 4, display: 'flex', gap: 8,
          alignItems: 'baseline', flexWrap: 'wrap' }}>
          <a href={r.url} target="_blank" rel="noreferrer"
            style={{ color: C.key, maxWidth: '100%', overflow: 'hidden',
              textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
            title={r.url}>
            {r.title || r.asin || r.url}
          </a>
          {r.title && r.asin && (
            <span style={{ fontSize: 11, color: C.sub }}>{r.asin}</span>
          )}
        </div>

        {r.supplier_url && (
          <div style={{ fontSize: 11, marginTop: 3, overflow: 'hidden',
            textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            <a href={r.supplier_url} target="_blank" rel="noreferrer"
              style={{ color: C.sub }} title={r.supplier_url}>
              仕入先を開く
            </a>
          </div>
        )}
        {r.memo && (
          <div style={{ fontSize: 12, color: C.sub, marginTop: 3 }}>{r.memo}</div>
        )}
        <div style={{ fontSize: 11, color: C.sub, marginTop: 3 }}>
          {r.claimed_at && new Date(r.claimed_at).toLocaleString('ja-JP')} 登録
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 5,
        flexShrink: 0 }}>
        {keeping && (
          <>
            <button className="btn btn-secondary" disabled={busy} onClick={onShip}
              style={{ fontSize: 12, padding: '4px 10px', whiteSpace: 'nowrap' }}
              title="代行会社から発送された。ここで枠が空く">
              発送済にする
            </button>
            <button className="btn btn-secondary" disabled={busy} onClick={onRelease}
              style={{ fontSize: 12, padding: '4px 10px', whiteSpace: 'nowrap' }}
              title="独占を手放す。相手が仕入れられるようになる">
              取り下げ
            </button>
          </>
        )}
        <button className="btn btn-secondary" disabled={busy} onClick={onDelete}
          style={{ fontSize: 12, padding: '4px 10px', color: C.bad }}>
          削除
        </button>
      </div>
    </div>
  )
}
