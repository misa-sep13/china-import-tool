import { useCallback, useEffect, useMemo, useState } from 'react'
import api from '../api/client'

/**
 * 再梱包指示（リサーチの6つ目のタブ）。
 *
 * 採用した商品を、代行会社が日本向けにどう詰め直すか。
 * 指示はリサーチシートではなく専用の表に持つ。シートは1枚のJSONを
 * 丸ごと読み書きするため、指示を1文字直すだけで全体の保存が走るため。
 *
 * 代行会社にはこの画面を見せない（原価・競合・売価が見えてしまう）。
 * 読み取り専用のページを、合言葉つきのURLで渡す。
 */

const C = {
  line: '#e5e7eb', sub: '#64748b', text: '#0f172a',
  key: '#2563eb', soft: '#f8fafc', good: '#16a34a',
}

const card = {
  background: '#fff', border: `1px solid ${C.line}`,
  borderRadius: 8, padding: 14,
}

const PLACEHOLDER = [
  '例：',
  '・元の箱は捨てて、OPP袋に入れ替える',
  '・商品ラベル（FNSKU）を袋の表面に貼る。バーコードが読める向きで',
  '・2個セットにして1つのOPP袋にまとめる',
  '・取扱説明書を1枚ずつ同梱する',
].join('\n')

export default function RepackPage() {
  const [items, setItems] = useState([])
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(true)
  const [onlyWritten, setOnlyWritten] = useState(false)
  const [q, setQ] = useState('')
  const [linkMsg, setLinkMsg] = useState('')

  const load = useCallback(async () => {
    setLoading(true); setErr('')
    try {
      const r = await api.get('/repack/items')
      setItems(r.data.items || [])
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  const written = items.filter(i => i.note || i.box_note).length

  const shown = useMemo(() => {
    const word = q.trim().toLowerCase()
    return items.filter(it => {
      if (onlyWritten && !(it.note || it.box_note)) return false
      if (!word) return true
      const hay = [it.name, it.research_title]
        .concat((it.children || []).map(
          c => `${c.name} ${c.sku} ${c.jan} ${c.asin || ''} ${c.fnsku || ''}`))
        .join(' ').toLowerCase()
      return hay.includes(word)
    })
  }, [items, onlyWritten, q])

  // 代行会社が開くページ。アプリと同じ場所に置いてある静的HTML
  const pageUrl = (token) =>
    `${location.origin}${import.meta.env.BASE_URL}research/repack.html#t=${token}`

  const copyLink = async () => {
    setLinkMsg('URLを用意しています…')
    try {
      const r = await api.get('/repack/link')
      const url = pageUrl(r.data.token)
      await navigator.clipboard.writeText(url).catch(() => {})
      setLinkMsg(`コピーしました（いま ${r.data.count || 0} 件 出ます）`)
      window.alert('代行会社へ渡すURLです。\n\n' + url
        + '\n\nこのURLを知っている人は、指示書を読むだけできます。'
        + '\n原価・競合・売価は出ません。書き換えもできません。')
    } catch (e) {
      setLinkMsg('うまくいきませんでした：' + (e.response?.data?.detail || e.message))
    }
  }

  const resetLink = async () => {
    const ok = window.confirm(
      'URLを作り直します。\n\n'
      + 'いま代行会社に渡してあるURLは、その場で開けなくなります。\n'
      + '新しいURLを渡し直す必要があります。\n\n作り直しますか？')
    if (!ok) return
    setLinkMsg('作り直しています…')
    try {
      const r = await api.post('/repack/reset-link')
      await navigator.clipboard.writeText(pageUrl(r.data.token)).catch(() => {})
      setLinkMsg('作り直してコピーしました。前のURLは開けません')
    } catch (e) {
      setLinkMsg('うまくいきませんでした：' + (e.response?.data?.detail || e.message))
    }
  }

  return (
    <div style={{ overflow: 'auto', height: '100%', padding: 2, minWidth: 0 }}>
      {err && (
        <div style={{ background: '#fef2f2', border: '1px solid #fecaca',
          color: '#991b1b', padding: 10, borderRadius: 6, marginBottom: 10,
          fontSize: 13 }}>{err}</div>
      )}

      <div style={{ ...card, marginBottom: 10, display: 'flex',
        alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 13 }}>
          採用した商品 <b>{items.length}</b> 件 ／ 指示を書いたもの{' '}
          <b>{written}</b> 件
        </div>
        <label style={{ fontSize: 12, color: C.sub, display: 'flex',
          alignItems: 'center', gap: 5 }}>
          <input type="checkbox" checked={onlyWritten}
            onChange={e => setOnlyWritten(e.target.checked)} />
          指示を書いたものだけ
        </label>
        <input value={q} onChange={e => setQ(e.target.value)}
          placeholder="商品名・SKU・JAN・ASINで絞り込み"
          style={{ padding: '6px 9px', border: `1px solid ${C.line}`,
            borderRadius: 6, fontSize: 13, width: 220 }} />
      </div>

      <div style={{ ...card, marginBottom: 10, background: '#f0f9ff',
        borderColor: '#bae6fd', display: 'flex', alignItems: 'center',
        gap: 10, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: '#075985' }}>
          🔗 代行会社へ渡すURL
        </span>
        <button className="btn btn-secondary" style={{ fontSize: 12 }}
          onClick={copyLink}>URLをコピー</button>
        <button className="btn btn-secondary" style={{ fontSize: 12 }}
          onClick={resetLink}>URLを作り直す</button>
        {linkMsg && (
          <span style={{ fontSize: 12, color: C.sub }}>{linkMsg}</span>
        )}
        <span style={{ fontSize: 11, color: C.sub, width: '100%',
          lineHeight: 1.7 }}>
          指示を書いたものだけが出ます。原価・競合・売価は出ません。
          読むだけで、書き換えはできません。
        </span>
      </div>

      {loading ? (
        <div style={{ ...card, color: C.sub, fontSize: 13 }}>
          読み込んでいます…
        </div>
      ) : (
        <div style={{ display: 'grid', gap: 8 }}>
          {shown.map(it => (
            <Row key={it.research_id} it={it}
              onSaved={(patch) => setItems(prev => prev.map(
                p => p.research_id === it.research_id ? { ...p, ...patch } : p))} />
          ))}
          {!shown.length && (
            <div style={{ ...card, color: C.sub, fontSize: 13, lineHeight: 1.7 }}>
              {items.length
                ? '条件に合うものがありません。'
                : <>出せる商品がありません。<br />
                  リサーチシートで枠の状態を<b>「採用」</b>にすると、ここに出てきます
                  （採用・発注済み・画像依頼済み・商品登録済みが対象です）。</>}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function Row({ it, onSaved }) {
  const [note, setNote] = useState(it.note || '')
  const [box, setBox] = useState(it.box_note || '')
  const [msg, setMsg] = useState('')
  const [open, setOpen] = useState(!!(it.note || it.box_note))

  const dirty = note !== (it.note || '') || box !== (it.box_note || '')

  const save = async () => {
    setMsg('保存しています…')
    try {
      await api.put(`/repack/items/${encodeURIComponent(it.research_id)}`,
        { note, box_note: box })
      onSaved({ note, box_note: box })
      setMsg('保存しました')
    } catch (e) {
      setMsg('うまくいきませんでした：' + (e.response?.data?.detail || e.message))
    }
  }

  const kids = (it.children || []).filter(c => c.name || c.sku)

  return (
    <div style={card}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
        {it.image && (
          <img src={it.image} alt="" loading="lazy"
            style={{ width: 60, height: 60, objectFit: 'contain',
              border: `1px solid ${C.line}`, borderRadius: 6,
              background: C.soft, flexShrink: 0 }} />
        )}
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: C.text,
            overflow: 'hidden', textOverflow: 'ellipsis',
            whiteSpace: 'nowrap' }}>
            {it.name || it.research_title || '(名称未入力)'}
          </div>
          <div style={{ fontSize: 11.5, color: C.sub, marginTop: 2 }}>
            {[it.status_label,
              kids.length ? `${kids.length}色` : '',
              it.updated_at ? `指示の更新 ${it.updated_at}` : '']
              .filter(Boolean).join('　/　')}
          </div>
        </div>
        {(it.note || it.box_note) && (
          <span style={{ fontSize: 11, color: C.good, fontWeight: 700,
            flexShrink: 0 }}>指示あり</span>
        )}
        <button className="btn btn-secondary" style={{ fontSize: 12,
          flexShrink: 0 }} onClick={() => setOpen(v => !v)}>
          {open ? '閉じる' : '指示を書く'}
        </button>
      </div>

      {open && (
        <div style={{ marginTop: 12 }}>
          {!!kids.length && (
            <table style={{ borderCollapse: 'collapse', fontSize: 12,
              marginBottom: 10 }}>
              <tbody>
                <tr>
                  {['色・種類', 'SKU', 'JAN', 'ASIN', 'FNSKU'].map(h => (
                    <th key={h} style={{ border: `1px solid ${C.line}`,
                      padding: '4px 8px', background: C.soft, color: C.sub,
                      textAlign: 'left', whiteSpace: 'nowrap' }}>{h}</th>
                  ))}
                </tr>
                {kids.map((c, i) => (
                  <tr key={i}>
                    <td style={{ border: `1px solid ${C.line}`,
                      padding: '4px 8px' }}>{c.name}</td>
                    <td style={{ border: `1px solid ${C.line}`,
                      padding: '4px 8px', fontFamily: 'monospace' }}>{c.sku}</td>
                    <td style={{ border: `1px solid ${C.line}`,
                      padding: '4px 8px', fontFamily: 'monospace' }}>{c.jan}</td>
                    {/* ASINは出品が通ってから、FNSKUはFBAに在庫が入ってから
                        付く。まだ無いうちは「—」で、空欄との違いを出す */}
                    <td style={{ border: `1px solid ${C.line}`,
                      padding: '4px 8px', fontFamily: 'monospace' }}>
                      {c.asin || <span style={{ color: C.line }}>—</span>}</td>
                    <td style={{ border: `1px solid ${C.line}`,
                      padding: '4px 8px', fontFamily: 'monospace' }}>
                      {c.fnsku || <span style={{ color: C.line }}>—</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <label style={{ display: 'block', fontSize: 12, color: C.sub,
            marginBottom: 4, fontWeight: 600 }}>
            詰め直しの指示（代行会社に出ます）
          </label>
          <textarea value={note} onChange={e => setNote(e.target.value)}
            rows={6} placeholder={PLACEHOLDER}
            style={{ width: '100%', padding: '7px 9px',
              border: `1px solid ${C.line}`, borderRadius: 6, fontSize: 13,
              boxSizing: 'border-box', lineHeight: 1.7 }} />

          <label style={{ display: 'block', fontSize: 12, color: C.sub,
            margin: '10px 0 4px', fontWeight: 600 }}>
            外箱・入数の指示（任意）
          </label>
          <textarea value={box} onChange={e => setBox(e.target.value)}
            rows={3} placeholder={'例：1箱に20個。外箱に色名と入数を書く'}
            style={{ width: '100%', padding: '7px 9px',
              border: `1px solid ${C.line}`, borderRadius: 6, fontSize: 13,
              boxSizing: 'border-box', lineHeight: 1.7 }} />

          <div style={{ display: 'flex', alignItems: 'center', gap: 10,
            marginTop: 8 }}>
            <button className="btn btn-primary" style={{ fontSize: 12 }}
              onClick={save} disabled={!dirty}>保存</button>
            {msg && <span style={{ fontSize: 12, color: C.sub }}>{msg}</span>}
          </div>
        </div>
      )}
    </div>
  )
}
