import { useCallback, useEffect, useRef, useState } from 'react'
import api, { mediaUrl } from '../api/client'
import { matchesQuery } from '../searchUtil'

/**
 * 画像作成の依頼一覧。
 *
 * リサーチシートから指示書をチャットワークへ送ると1件できる。送ったあとは
 * 「誰に何を頼んでいて、いまどうなっているか」を追える場所が無く、
 * チャットの履歴をさかのぼるしかなかった。
 *
 * 外注さん用に、この一覧だけを見せる共有URLがある（readOnlyPublic）。
 * 向こうでは進み具合・納品先・連絡だけ触れる。
 */

const C = {
  line: '#e5e7eb', sub: '#64748b', text: '#0f172a',
  good: '#16a34a', warn: '#b45309', bad: '#dc2626', key: '#2563eb',
}

const STATUS_COLOR = {
  requested: { bg: '#fff7ed', fg: '#9a3412' },
  working:   { bg: '#eff6ff', fg: '#1d4ed8' },
  review:    { bg: '#fefce8', fg: '#854d0e' },
  done:      { bg: '#f0fdf4', fg: '#166534' },
}

const SOURCE_LABEL = { amazon: 'Amazon', rakuten: '楽天', manual: '手動' }

const td = { padding: '6px 8px', borderTop: `1px solid ${C.line}`, fontSize: 12 }
const th = { padding: '6px 8px', textAlign: 'left', whiteSpace: 'nowrap',
  fontSize: 12, color: C.sub, background: '#f8fafc' }

export default function ImageRequestsPage({ share = '' }) {
  const [rows, setRows] = useState([])
  const [statuses, setStatuses] = useState([])
  const [doneCount, setDoneCount] = useState(0)
  const [includeDone, setIncludeDone] = useState(false)
  const [q, setQ] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [big, setBig] = useState(null)   // 拡大して見ている画像
  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState({ sku: '', name: '', detail: '', ref_url: '',
    main_url: '', assignee: '', due_date: '', source: 'rakuten' })

  // 共有URLで開いているときは合言葉を毎回付ける。
  // ログインしていないので、これが唯一の通行証になる
  const cfg = useCallback((extra = {}) => (
    share ? { ...extra, params: { ...(extra.params || {}), share },
      headers: { ...(extra.headers || {}), 'x-image-share': share } } : extra
  ), [share])

  const load = useCallback(async () => {
    setErr('')
    try {
      const r = await api.get('/image-requests',
        cfg({ params: { include_done: includeDone ? 1 : 0 } }))
      setRows(r.data.items || [])
      setStatuses(r.data.statuses || [])
      setDoneCount(r.data.done_count || 0)
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    }
  }, [cfg, includeDone])
  useEffect(() => { load() }, [load])

  const patch = async (id, body) => {
    setBusy(true)
    try {
      await api.patch(`/image-requests/${id}`, body, cfg())
      await load()
    } catch (e) {
      alert(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  const add = async () => {
    setBusy(true)
    try {
      await api.post('/image-requests', form, cfg())
      setForm({ sku: '', name: '', detail: '', ref_url: '', main_url: '',
        assignee: '', due_date: '', source: 'rakuten' })
      setAdding(false)
      await load()
    } catch (e) {
      alert(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  // 並びを1つ上／下へ。外注さんの画面（share）では出さない
  const move = async (r, direction) => {
    setBusy(true)
    try {
      await api.post(`/image-requests/${r.id}/move`, null,
        cfg({ params: { direction } }))
      await load()
    } catch (e) {
      alert(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  const remove = async (r) => {
    if (!window.confirm(`${r.sku || r.name} の依頼を消します。よろしいですか？`)) return
    setBusy(true)
    try {
      await api.delete(`/image-requests/${r.id}`, cfg())
      await load()
    } catch (e) {
      alert(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  const shown = rows.filter(r => !q.trim()
    || matchesQuery(q, [r.sku, r.name, r.doc_name, r.detail]))

  return (
    <div style={{ height: '100%', overflow: 'auto', padding: 2, minWidth: 0 }}>
      {err && (
        <div style={{ background: '#fef2f2', border: '1px solid #fecaca',
          color: '#991b1b', padding: 10, borderRadius: 6, marginBottom: 10,
          fontSize: 13 }}>{err}</div>
      )}

      <div className="card" style={{ marginBottom: 10, display: 'flex',
        alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <b style={{ fontSize: 14 }}>🎨 画像作成の依頼</b>
        <span style={{ fontSize: 12, color: C.sub }}>
          作業中 {rows.filter(r => r.status !== 'done').length}件
          {doneCount > 0 && ` ／ 完了 ${doneCount}件`}
        </span>
        <input type="text" value={q} onChange={e => setQ(e.target.value)}
          placeholder="SKU・商品名・補足で絞り込み"
          className="search-input-ja" style={{ width: 220 }} />
        <label style={{ fontSize: 12, color: C.sub, display: 'flex',
          alignItems: 'center', gap: 5 }}>
          <input type="checkbox" checked={includeDone}
            onChange={e => setIncludeDone(e.target.checked)} />
          完了したものも出す
        </label>
        <button className="btn btn-sm btn-secondary" style={{ fontSize: 12 }}
          onClick={load} disabled={busy}>更新</button>
        {!share && (
          <button className="btn btn-sm btn-primary" style={{ fontSize: 12,
            marginLeft: 'auto' }} onClick={() => setAdding(v => !v)}>
            {adding ? '閉じる' : '＋ 手で足す'}
          </button>
        )}
      </div>

      {adding && !share && (
        <div className="card" style={{ marginBottom: 10 }}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap',
            alignItems: 'flex-end' }}>
            <Field label="どこの商品" w={110}>
              <select value={form.source}
                onChange={e => setForm(f => ({ ...f, source: e.target.value }))}>
                <option value="rakuten">楽天</option>
                <option value="amazon">Amazon</option>
                <option value="manual">その他</option>
              </select>
            </Field>
            <Field label="SKU" w={120}>
              <input value={form.sku}
                onChange={e => setForm(f => ({ ...f, sku: e.target.value }))} />
            </Field>
            <Field label="商品名" w={220}>
              <input value={form.name}
                onChange={e => setForm(f => ({ ...f, name: e.target.value }))} />
            </Field>
            <Field label="1688のURL" w={240}>
              <input value={form.main_url}
                onChange={e => setForm(f => ({ ...f, main_url: e.target.value }))} />
            </Field>
            <Field label="競合のAmazon URL" w={220}>
              <input value={form.ref_url}
                onChange={e => setForm(f => ({ ...f, ref_url: e.target.value }))} />
            </Field>
            <Field label="商品補足" w={320}>
              <input value={form.detail}
                onChange={e => setForm(f => ({ ...f, detail: e.target.value }))} />
            </Field>
            <button className="btn btn-primary" onClick={add} disabled={busy}>
              足す
            </button>
          </div>
        </div>
      )}

      <div className="card" style={{ padding: 0, overflow: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              {[...(share ? [] : ['並び']), '依頼日', '', '写真', 'SKU', '商品名',
                '参考画像', '納品データ', '商品補足', '進み具合', '連絡', ''].map((h, i) => (
                  <th key={i} style={th}>{h}</th>
                ))}
            </tr>
          </thead>
          <tbody>
            {shown.length === 0 && (
              <tr><td style={{ ...td, color: C.sub, padding: 20 }}
                colSpan={share ? 11 : 12}>
                {q ? `「${q}」に当てはまる依頼はありません。`
                  : '作業中の依頼はありません。'}
              </td></tr>
            )}
            {shown.map(r => {
              const c = STATUS_COLOR[r.status] || STATUS_COLOR.requested
              return (
                <tr key={r.id}>
                  {!share && (
                    <td style={{ ...td, whiteSpace: 'nowrap', padding: '2px 4px' }}>
                      <button className="btn btn-sm" title="ひとつ上へ"
                        style={{ fontSize: 10, padding: '0 5px' }}
                        onClick={() => move(r, 'up')} disabled={busy}>▲</button>
                      <button className="btn btn-sm" title="ひとつ下へ"
                        style={{ fontSize: 10, padding: '0 5px', marginLeft: 2 }}
                        onClick={() => move(r, 'down')} disabled={busy}>▼</button>
                    </td>
                  )}
                  {/* 一覧を作る前に出した依頼は、実際に出した日に直せるようにする */}
                  <td style={{ ...td, whiteSpace: 'nowrap', color: C.sub }}>
                    {share ? (
                      (r.sent_at || r.created_at || '').slice(5, 10).replace('-', '/')
                    ) : (
                      <input type="date"
                        defaultValue={(r.sent_at || r.created_at || '').slice(0, 10)}
                        onBlur={e => {
                          const v = e.target.value
                          if (v && v !== (r.sent_at || r.created_at || '').slice(0, 10))
                            patch(r.id, { sent_at: v })
                        }}
                        style={{ width: 128, fontSize: 11, padding: '2px 4px' }} />
                    )}
                  </td>
                  <td style={{ ...td, whiteSpace: 'nowrap', color: C.sub }}>
                    {SOURCE_LABEL[r.source] || r.source}
                  </td>
                  {/* 何の商品か。リサーチシートに貼ってあるライバルの画像 */}
                  <td style={{ ...td, padding: '4px 6px' }}>
                    {r.has_cover ? (
                      <img src={mediaUrl(`/api/image-requests/${r.id}/cover`)}
                        alt="" loading="lazy"
                        onClick={() => setBig(
                          mediaUrl(`/api/image-requests/${r.id}/cover`))}
                        style={{ width: 46, height: 46, objectFit: 'cover',
                          borderRadius: 4, border: `1px solid ${C.line}`,
                          cursor: 'zoom-in', display: 'block' }} />
                    ) : (
                      <div style={{ width: 46, height: 46, borderRadius: 4,
                        border: `1px dashed ${C.line}`, color: '#cbd5e1',
                        fontSize: 10, display: 'flex', alignItems: 'center',
                        justifyContent: 'center' }}>なし</div>
                    )}
                  </td>
                  <td style={{ ...td, fontFamily: 'monospace', fontWeight: 600 }}>
                    {r.sku}
                  </td>
                  <td style={td}>
                    {r.name}
                    {r.doc_name && (
                      <div style={{ fontSize: 10, color: C.sub }}>{r.doc_name}</div>
                    )}
                    {/* 名前が長いと折り返して読みにくいので短く出す */}
                    <div style={{ display: 'flex', gap: 8, whiteSpace: 'nowrap' }}>
                      {r.main_url && (
                        <a href={r.main_url} target="_blank" rel="noreferrer"
                          style={{ fontSize: 11 }}
                          title="仕入元のページ。画像素材と実物の作りはここで見られます">
                          1688URL
                        </a>
                      )}
                      {r.ref_url && (
                        <a href={r.ref_url} target="_blank" rel="noreferrer"
                          style={{ fontSize: 11 }}
                          title="競合のAmazon商品ページ">セラー</a>
                      )}
                    </div>
                  </td>
                  {/* デザイナーに伝えたいこと。シートの「商品補足」がそのまま入る */}
                  <td style={{ ...td, width: 150 }}>
                    <Photos r={r} share={share} cfg={cfg} reload={load}
                      setErr={setErr} onOpen={setBig} />
                  </td>
                  <td style={{ ...td, width: 160 }}>
                    <Deliveries r={r} cfg={cfg} reload={load} setErr={setErr} />
                  </td>
                  <td style={{ ...td, width: '34%' }}>
                    {share ? (
                      <span style={{ whiteSpace: 'pre-wrap' }}>{r.detail || '—'}</span>
                    ) : (
                      <textarea defaultValue={r.detail} rows={2}
                        placeholder="商品補足（デザイナーに伝えたいこと）"
                        onBlur={e => {
                          if (e.target.value !== r.detail)
                            patch(r.id, { detail: e.target.value })
                        }}
                        style={{ width: '100%', minWidth: 300, fontSize: 12 }} />
                    )}
                  </td>
                  <td style={td}>
                    <select value={r.status} disabled={busy}
                      onChange={e => patch(r.id, { status: e.target.value })}
                      style={{ background: c.bg, color: c.fg, fontWeight: 700,
                        fontSize: 12, padding: '3px 6px', width: 108 }}>
                      {statuses.map(s => (
                        <option key={s.value} value={s.value}>{s.label}</option>
                      ))}
                    </select>
                  </td>
                  <td style={{ ...td, width: '26%' }}>
                    <input defaultValue={r.reply} placeholder="連絡・質問"
                      onBlur={e => {
                        if (e.target.value !== r.reply)
                          patch(r.id, { reply: e.target.value })
                      }}
                      style={{ width: '100%', minWidth: 240, fontSize: 12 }} />
                  </td>
                  <td style={td}>
                    {!share && (
                      <button className="btn btn-sm"
                        style={{ background: '#fee2e2', color: '#991b1b',
                          fontSize: 11 }}
                        onClick={() => remove(r)} disabled={busy}>削除</button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* 拡大表示。どこを押しても閉じる */}
      {big && (
        <div onClick={() => setBig(null)}
          style={{ position: 'fixed', inset: 0, zIndex: 1000, cursor: 'zoom-out',
            background: 'rgba(15,23,42,.82)', display: 'flex',
            alignItems: 'center', justifyContent: 'center', padding: 24 }}>
          <img src={big} alt="参考画像"
            style={{ maxWidth: '96%', maxHeight: '96%', borderRadius: 6,
              boxShadow: '0 8px 40px rgba(0,0,0,.5)' }} />
        </div>
      )}

      <div style={{ fontSize: 11, color: C.sub, marginTop: 8, lineHeight: 1.8 }}>
        新しく足したものが上に並びます。▲▼ で順番を入れ替えられます。
        進み具合を「完了」にすると、この一覧から消えます（「完了したものも出す」で戻せます）。
        <br />
        「写真」はリサーチシートに貼ってあるライバルの画像です。
        参考画像ともどもクリックで拡大できます。
        <b>納品データ</b>は一時置きです。進み具合を<b>「完了」にすると消えます</b>
        （商品登録に使い終わったもので容量を食わないように）。
        {!share && <><br />
          参考画像は「＋」でファイルを選ぶ・枠へドラッグ＆ドロップ・
          <b>「📋」を押してから Ctrl+V</b>のどれでも入ります（まとめて可）。
          外注さんの画面にも出るので、色や向きを見せるのに使えます。<br />
          リサーチシートで「💬 Chatworkで送る」を押すと、ここに自動で1件増えます。
        </>}
      </div>
    </div>
  )
}

/**
 * 納品データ（外注さんから届いた画像のZIPなど）の一時置き場。
 *
 * 商品登録に使ったら要らないので、進み具合を「完了」にした時点で
 * サーバー側が中身を消す。ずっと置くとすぐ容量を食うため。
 */
function Deliveries({ r, cfg, reload, setErr }) {
  const [busy, setBusy] = useState(false)
  const files = r.files || []

  const mb = (n) => (n >= 1024 * 1024
    ? `${(n / 1024 / 1024).toFixed(1)}MB`
    : `${Math.max(1, Math.round(n / 1024))}KB`)

  // 中身が何かひと目で分かるように、種類で印を変える
  const kindOf = (name) => {
    const e = (name || '').toLowerCase().split('.').pop()
    if (['mp4', 'mov', 'm4v', 'avi', 'wmv', 'mkv', 'webm'].includes(e)) {
      return { icon: '🎬', label: '動画', color: '#7c3aed' }
    }
    if (['zip', 'rar', '7z'].includes(e)) {
      return { icon: '📦', label: 'まとめ', color: C.key }
    }
    if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'heic'].includes(e)) {
      return { icon: '🖼', label: '画像', color: '#0f766e' }
    }
    return { icon: '📄', label: '', color: C.sub }
  }

  const send = async (list) => {
    const picked = [...(list || [])]
    if (!picked.length) return
    setBusy(true); setErr('')
    try {
      const fd = new FormData()
      picked.forEach(f => fd.append('files', f))
      await api.post(`/image-requests/${r.id}/files`, fd, cfg())
      await reload()
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  // ログインの通行証を付けて落とす必要があるので、リンクではなく
  // こちらで読み込んでから保存する
  const download = async (f) => {
    setBusy(true)
    try {
      const res = await api.get(`/image-requests/file/${f.id}`,
        cfg({ responseType: 'blob' }))
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url; a.download = f.name || 'file'
      document.body.appendChild(a); a.click(); a.remove()
      URL.revokeObjectURL(url)
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  const remove = async (f) => {
    if (!confirm(`${f.name} を消しますか？`)) return
    setBusy(true)
    try {
      await api.delete(`/image-requests/file/${f.id}`, cfg())
      await reload()
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  return (
    <div
      onDragOver={e => e.preventDefault()}
      onDrop={e => { e.preventDefault(); send(e.dataTransfer.files) }}
      style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      {/* 動画が何本あるかは、並びを見なくても分かるようにする */}
      {files.filter(f => kindOf(f.name).label === '動画').length > 0 && (
        <div style={{ fontSize: 11, color: '#7c3aed', fontWeight: 700 }}>
          🎬 動画 {files.filter(f => kindOf(f.name).label === '動画').length}本
        </div>
      )}
      {files.map(f => (
        <div key={f.id} style={{ display: 'flex', alignItems: 'center',
          gap: 4, fontSize: 11 }}>
          <button onClick={() => download(f)} disabled={busy}
            title={`落とす（${kindOf(f.name).label || 'ファイル'}）`}
            style={{ border: 'none', background: 'none', padding: 0,
              color: kindOf(f.name).color, cursor: 'pointer',
              textAlign: 'left',
              maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis',
              whiteSpace: 'nowrap' }}>
            {kindOf(f.name).icon} {f.name}
          </button>
          <span style={{ color: C.sub }}>{mb(f.size)}</span>
          <button onClick={() => remove(f)} disabled={busy} title="消す"
            style={{ border: 'none', background: 'none', padding: 0,
              color: C.bad, cursor: 'pointer' }}>×</button>
        </div>
      ))}
      <label title="ZIPや画像を置く（ここへドラッグしても入ります）"
        style={{ fontSize: 11, color: busy ? C.sub : C.key, cursor: 'pointer' }}>
        {busy ? '…' : '＋ 納品データを置く'}
        <input type="file" multiple hidden disabled={busy}
          onChange={e => { send(e.target.files); e.target.value = '' }} />
      </label>
    </div>
  )
}

/**
 * 参考画像。
 *
 * 「この色で」を言葉で説明するより、現物を1枚見せたほうが早い。
 * 外注さんの画面（share）では見るだけ。
 *
 * 画像そのものはURLで読ませてブラウザに任せている（一覧のJSONに
 * 混ぜると、開くたびに数MBを送ることになる）。
 */
function Photos({ r, share, cfg, reload, setErr, onOpen }) {
  const [busy, setBusy] = useState(false)
  const [over, setOver] = useState(false)
  const [ready, setReady] = useState(false)   // 貼り付け待ち（枠を選んだ状態）
  const pasteBtn = useRef(null)

  const src = (id, thumb) => mediaUrl(
    `/api/image-requests/photo/${id}${thumb ? '?thumb=1' : ''}`)

  const send = async (files) => {
    const list = [...(files || [])].filter(f => f.type.startsWith('image/'))
    if (!list.length) return
    setBusy(true); setErr('')
    try {
      const fd = new FormData()
      list.forEach(f => fd.append('files', f))
      await api.post(`/image-requests/${r.id}/photos`, fd, cfg())
      await reload()
      // 続けて2枚目を貼れるように、待ち受けたまま戻す
      if (ready) setTimeout(() => pasteBtn.current?.focus(), 0)
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  const remove = async (id) => {
    if (!confirm('この参考画像を消しますか？')) return
    setBusy(true)
    try {
      await api.delete(`/image-requests/photo/${id}`, cfg())
      await reload()
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  // 右クリック→コピーした画像を、枠を選んでから Ctrl+V で入れる。
  // 1688やAmazonの画像を落とさずに持ってこられる。
  //
  // 貼り付けは入力欄にしか飛ばないことがあり、ボタンに焦点があっても
  // 届かない。待っている間だけ画面全体で受ける
  useEffect(() => {
    if (!ready || share) return
    const onPaste = (e) => {
      const items = [...(e.clipboardData?.items || [])]
        .filter(i => i.type.startsWith('image/'))
      if (!items.length) return
      e.preventDefault()
      send(items.map(i => i.getAsFile()).filter(Boolean))
    }
    document.addEventListener('paste', onPaste)
    return () => document.removeEventListener('paste', onPaste)
  }, [ready, share, r.id])

  const photos = r.photos || []

  return (
    <div
      // 枠の余白を押したときも貼り付け待ちにする。
      // 「＋」や画像そのものを押したときは、そちらの動きを邪魔しない
      onMouseDown={share ? undefined : e => {
        if (e.target === e.currentTarget) {
          e.preventDefault()
          pasteBtn.current?.focus()
        }
      }}
      onDragOver={share ? undefined : e => { e.preventDefault(); setOver(true) }}
      onDragLeave={share ? undefined : () => setOver(false)}
      onDrop={share ? undefined : e => {
        e.preventDefault(); setOver(false); send(e.dataTransfer.files)
      }}
      style={{ display: 'flex', flexWrap: 'wrap', gap: 4, minHeight: 28,
        padding: 2, borderRadius: 4,
        outline: over ? `2px dashed ${C.key}` : 'none',
        background: over ? '#eff6ff' : 'transparent' }}>
      {photos.map(id => (
        <div key={id} style={{ position: 'relative' }}>
          <img src={src(id, true)} alt="参考画像"
            onClick={() => onOpen(src(id, false))}
            style={{ width: 46, height: 46, objectFit: 'cover', borderRadius: 4,
              border: `1px solid ${C.line}`, cursor: 'zoom-in',
              display: 'block' }} />
          {!share && (
            <button onClick={() => remove(id)} title="消す" disabled={busy}
              style={{ position: 'absolute', top: -5, right: -5, width: 16,
                height: 16, lineHeight: '14px', padding: 0, fontSize: 11,
                borderRadius: 8, border: `1px solid ${C.line}`,
                background: '#fff', color: C.bad, cursor: 'pointer' }}>×</button>
          )}
        </div>
      ))}
      {!share && (
        <>
          {/* ファイルを選ぶ */}
          <label title="画像ファイルを選ぶ（ここへドラッグしても入ります）"
            style={{ width: 46, height: 46, borderRadius: 4, cursor: 'pointer',
              border: `1px dashed ${C.line}`, color: C.sub, fontSize: 18,
              display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            {busy ? '…' : '＋'}
            <input type="file" accept="image/*" multiple hidden disabled={busy}
              onChange={e => { send(e.target.files); e.target.value = '' }} />
          </label>
          {/* 貼り付け。押してから Ctrl+V。ファイル選択と取り合いにならないよう分けてある */}
          <button type="button" disabled={busy} ref={pasteBtn}
            title="押してから Ctrl+V でコピーした画像を貼り付け"
            onFocus={() => setReady(true)}
            onBlur={() => setReady(false)}
            style={{ width: 46, height: 46, borderRadius: 4, cursor: 'pointer',
              padding: 0, lineHeight: 1.2, textAlign: 'center',
              border: `1px dashed ${ready ? C.key : C.line}`,
              background: ready ? '#eff6ff' : '#fff',
              color: ready ? C.key : C.sub,
              fontSize: ready ? 10 : 15, fontWeight: ready ? 700 : 400 }}>
            {ready ? 'Ctrl+V' : '📋'}
          </button>
        </>
      )}
      {share && photos.length === 0 && (
        <span style={{ fontSize: 11, color: C.sub }}>—</span>
      )}
    </div>
  )
}

function Field({ label, w, children }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2, width: w }}>
      <span style={{ fontSize: 11, color: C.sub }}>{label}</span>
      {children}
    </div>
  )
}
