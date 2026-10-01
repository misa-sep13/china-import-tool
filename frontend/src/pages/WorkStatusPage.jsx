import { useCallback, useEffect, useState } from 'react'
import api from '../api/client'
import { matchesQuery } from '../searchUtil'

/**
 * 状況確認シート。商品ごとに「いま誰の番か」と質問のやり取りを持つ。
 *
 * チャットワークだけでやり取りしていると話が流れてしまい、
 * 「これは誰の番なのか」「この質問は答えたのか」が分からなくなる。
 * 外注さんから一覧で見たいという声が出たので作った。
 *
 * 1行＝商品（SKU）1つ。Amazonも楽天も同じ並びに出す。
 * 外注さん用に、この一覧だけを見せる共有URLがある（WorkStatusPublicPage）。
 */

const C = {
  line: '#e5e7eb', sub: '#64748b', text: '#0f172a',
  good: '#16a34a', warn: '#b45309', bad: '#dc2626', key: '#2563eb',
}

// 誰の番か。一覧の主役なので、色ではっきり分ける。
// 名前ではなく役割で持つ（owner＝ゆな、staff＝外注さん）。
// 外注さんが交代しても保存済みのデータを直さなくて済む
const BALL_COLOR = {
  owner: { bg: '#fef2f2', fg: '#b91c1c' },  // ゆなが止めている
  staff: { bg: '#eff6ff', fg: '#1d4ed8' },  // 外注さんが動いている
  none:  { bg: '#f1f5f9', fg: '#475569' },  // 待ちなし
}

// 質問を書いた人の見せ方
const WHO_LABEL = { owner: 'ゆな', staff: '外注さん' }

const CHANNEL_LABEL = { amazon: 'Amazon', rakuten: '楽天' }

const td = { padding: '6px 8px', borderTop: `1px solid ${C.line}`, fontSize: 12,
  verticalAlign: 'top' }
const th = { padding: '6px 8px', textAlign: 'left', whiteSpace: 'nowrap',
  fontSize: 12, color: C.sub, background: '#f8fafc' }

export default function WorkStatusPage({ share = '', me = 'owner' }) {
  const [rows, setRows] = useState([])
  const [balls, setBalls] = useState([])
  const [includeDone, setIncludeDone] = useState(false)
  // 完了したものだけを見る。終わった分をまとめて振り返るときに使う
  const [onlyDone, setOnlyDone] = useState(false)
  const [steps, setSteps] = useState([])
  const [extraSteps, setExtraSteps] = useState([])
  const [q, setQ] = useState('')
  const [onlyMine, setOnlyMine] = useState(false)
  const [err, setErr] = useState('')
  const [open, setOpen] = useState({})       // 質問欄を開いている行
  const [draft, setDraft] = useState({})     // 書きかけの質問
  const [ans, setAns] = useState({})         // 書きかけの答え
  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState({ sku: '', name: '', memo: '', channel: 'amazon' })

  // 共有URLで開いているときは合言葉を毎回付ける。
  // ログインしていないので、これが唯一の通行証になる
  const cfg = useCallback((extra = {}) => (
    share ? { ...extra, params: { ...(extra.params || {}), share },
      headers: { ...(extra.headers || {}), 'x-work-share': share } } : extra
  ), [share])

  const load = useCallback(async () => {
    setErr('')
    try {
      const r = await api.get('/work-status', cfg({ params: {
        include_done: includeDone ? 1 : 0,
        only_done: onlyDone ? 1 : 0,
      } }))
      setRows(r.data.items || [])
      setSteps(r.data.steps || [])
      setExtraSteps(r.data.extra_steps || [])
      setBalls(r.data.balls || [])
    } catch (e) {
      setErr(e?.response?.data?.detail || '読み込めませんでした')
    }
  }, [cfg, includeDone, onlyDone])

  useEffect(() => { load() }, [load])

  const patch = async (id, body) => {
    try {
      const r = await api.patch(`/work-status/${id}`, body, cfg())
      setRows(rs => rs.map(x => (x.id === id ? r.data : x)))
    } catch (e) {
      setErr(e?.response?.data?.detail || '保存できませんでした')
    }
  }

  const ask = async (id) => {
    const body = (draft[id] || '').trim()
    if (!body) return
    try {
      const r = await api.post(`/work-status/${id}/notes`,
        { who: me, body }, cfg())
      setRows(rs => rs.map(x => (x.id === id ? r.data : x)))
      setDraft(d => ({ ...d, [id]: '' }))
    } catch (e) {
      setErr(e?.response?.data?.detail || '送れませんでした')
    }
  }

  // やり取りを消す。テストや書き間違いが残ると、答えの要る質問が埋もれる
  const removeNote = async (id, noteId) => {
    if (!window.confirm('このやり取りを消します。よろしいですか？')) return
    try {
      const r = await api.delete(`/work-status/${id}/notes/${noteId}`, cfg())
      setRows(rs => rs.map(x => (x.id === id ? r.data : x)))
    } catch (e) {
      setErr(e?.response?.data?.detail || '消せませんでした')
    }
  }

  const reply = async (id, noteId) => {
    const answer = (ans[noteId] || '').trim()
    if (!answer) return
    try {
      const r = await api.patch(`/work-status/${id}/notes/${noteId}`,
        { answer }, cfg())
      setRows(rs => rs.map(x => (x.id === id ? r.data : x)))
      setAns(a => ({ ...a, [noteId]: '' }))
    } catch (e) {
      setErr(e?.response?.data?.detail || '送れませんでした')
    }
  }

  const add = async () => {
    if (!form.sku.trim() && !form.name.trim()) return
    try {
      await api.post('/work-status', form, cfg())
      setForm({ sku: '', name: '', memo: '', channel: 'amazon' })
      setAdding(false)
      load()
    } catch (e) {
      setErr(e?.response?.data?.detail || '追加できませんでした')
    }
  }

  const del = async (id) => {
    if (!window.confirm('この行を消します。よろしいですか？')) return
    try {
      await api.delete(`/work-status/${id}`, cfg())
      setRows(rs => rs.filter(x => x.id !== id))
    } catch (e) {
      setErr(e?.response?.data?.detail || '消せませんでした')
    }
  }

  const shown = rows.filter(r => {
    if (onlyMine && r.ball !== me) return false
    if (!q.trim()) return true
    return matchesQuery(q, [r.sku, r.name, r.memo])
  })

  // 自分の番のものが何件あるか。まずここを見てもらう
  const mine = rows.filter(r => r.ball === me).length
  const openQ = rows.reduce((a, r) => a + (r.open_count || 0), 0)

  return (
    <div>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center',
        flexWrap: 'wrap', marginBottom: 10 }}>
        <input value={q} onChange={e => setQ(e.target.value)}
          placeholder="SKU・商品名で絞り込み"
          style={{ padding: '6px 10px', border: `1px solid ${C.line}`,
            borderRadius: 6, fontSize: 13, width: 220 }} />
        <label style={{ fontSize: 12, color: C.sub, display: 'flex',
          alignItems: 'center', gap: 4 }}>
          <input type="checkbox" checked={onlyMine}
            onChange={e => setOnlyMine(e.target.checked)} />
          自分の番だけ（{mine}件）
        </label>
        <label style={{ fontSize: 12, color: C.sub, display: 'flex',
          alignItems: 'center', gap: 4 }}>
          <input type="checkbox" checked={includeDone} disabled={onlyDone}
            onChange={e => setIncludeDone(e.target.checked)} />
          完了も出す
        </label>
        <label style={{ fontSize: 12, color: C.sub, display: 'flex',
          alignItems: 'center', gap: 4 }}>
          <input type="checkbox" checked={onlyDone}
            onChange={e => setOnlyDone(e.target.checked)} />
          完了だけ出す
        </label>
        {openQ > 0 && (
          <span style={{ fontSize: 12, color: C.bad, fontWeight: 600 }}>
            答え待ちの質問 {openQ}件
          </span>
        )}
        {(
          <button onClick={() => setAdding(v => !v)}
            style={{ marginLeft: 'auto', padding: '6px 12px', fontSize: 12,
              border: `1px solid ${C.key}`, background: '#fff', color: C.key,
              borderRadius: 6, cursor: 'pointer' }}>
            ＋ 追加
          </button>
        )}
      </div>

      {err && <div style={{ color: C.bad, fontSize: 12, marginBottom: 8 }}>{err}</div>}

      {adding && (
        <div style={{ display: 'flex', gap: 6, marginBottom: 10,
          padding: 10, background: '#f8fafc', borderRadius: 6 }}>
          <select value={form.channel}
            onChange={e => setForm(f => ({ ...f, channel: e.target.value }))}
            style={{ fontSize: 12, padding: '5px 8px' }}>
            <option value="amazon">Amazon</option>
            <option value="rakuten">楽天</option>
          </select>
          <input value={form.sku} placeholder="SKU"
            onChange={e => setForm(f => ({ ...f, sku: e.target.value }))}
            style={{ fontSize: 12, padding: '5px 8px', width: 120 }} />
          <input value={form.name} placeholder="商品名"
            onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
            style={{ fontSize: 12, padding: '5px 8px', flex: 1 }} />
          <input value={form.memo || ''} placeholder="メモ（在庫切れ・リンク変更など）"
            onChange={e => setForm(f => ({ ...f, memo: e.target.value }))}
            style={{ fontSize: 12, padding: '5px 8px', flex: 1 }} />
          <button onClick={add}
            style={{ fontSize: 12, padding: '5px 14px', border: 'none',
              background: C.key, color: '#fff', borderRadius: 6,
              cursor: 'pointer' }}>追加</button>
        </div>
      )}

      <table style={{ width: '100%', borderCollapse: 'collapse',
        background: '#fff', border: `1px solid ${C.line}` }}>
        <thead>
          <tr>
            <th style={th}>登録日</th>
            <th style={th}>店</th>
            <th style={th}>SKU</th>
            <th style={th}>商品名</th>
            <th style={th}>いま誰の番</th>
            <th style={th}>工程（左の3つで完了）</th>
            <th style={th}>メモ</th>
            <th style={th}>質問</th>
            {!share && <th style={th}></th>}
          </tr>
        </thead>
        <tbody>
          {shown.map(r => {
            const bc = BALL_COLOR[r.ball] || BALL_COLOR.none
            const isOpen = !!open[r.id]
            return [
              <tr key={r.id}>
                {/* いつ載せた行かが分かるように。古いまま止まっているものを見つける手がかり */}
                <td style={{ ...td, color: C.sub, whiteSpace: 'nowrap' }}>
                  {(r.created_at || '').slice(0, 10).replace(/-/g, '/')}
                </td>
                <td style={{ ...td, color: C.sub, whiteSpace: 'nowrap' }}>
                  {CHANNEL_LABEL[r.channel] || r.channel}
                </td>
                <td style={{ ...td, fontWeight: 600, whiteSpace: 'nowrap' }}>{r.sku}</td>
                <td style={td}>{r.name}</td>
                <td style={td}>
                  <select value={r.ball}
                    onChange={e => patch(r.id, { ball: e.target.value })}
                    style={{ fontSize: 12, padding: '3px 6px', border: 'none',
                      borderRadius: 4, fontWeight: 600,
                      background: bc.bg, color: bc.fg, cursor: 'pointer' }}>
                    {balls.map(b => (
                      <option key={b.key} value={b.key}>{b.label}</option>
                    ))}
                  </select>
                </td>
                {/* 3つそろったら完了。プルダウンだと「発注は済んだが
                    画像はまだ」という途中を表せなかった */}
                <td style={td}>
                  <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap',
                    alignItems: 'center' }}>
                    {steps.map(st => (
                      <label key={st.key} style={{ fontSize: 12,
                        display: 'flex', alignItems: 'center', gap: 3,
                        cursor: 'pointer',
                        color: r[st.key] ? C.text : C.sub }}>
                        <input type="checkbox" checked={!!r[st.key]}
                          onChange={e => patch(r.id,
                            { [st.key]: e.target.checked })}
                          style={{ width: 'auto', margin: 0 }} />
                        {st.label}
                      </label>
                    ))}
                    {/* 完了の条件には入れない。問い合わせの要らない商品が
                        いつまでも完了にならなくなるため */}
                    {extraSteps.map(st => (
                      <label key={st.key} title="発注後にタオタロウへ問い合わせたり、確認してもらったとき"
                        style={{ fontSize: 12, display: 'flex',
                          alignItems: 'center', gap: 3, cursor: 'pointer',
                          paddingLeft: 8, borderLeft: `1px solid ${C.line}`,
                          color: r[st.key] ? C.text : C.sub }}>
                        <input type="checkbox" checked={!!r[st.key]}
                          onChange={e => patch(r.id,
                            { [st.key]: e.target.checked })}
                          style={{ width: 'auto', margin: 0 }} />
                        {st.label}
                      </label>
                    ))}
                    {r.done && (
                      <span style={{ fontSize: 11, fontWeight: 700,
                        color: '#166534', background: '#f0fdf4',
                        border: '1px solid #bbf7d0', borderRadius: 4,
                        padding: '1px 6px' }}>完了</span>
                    )}
                  </div>
                </td>
                <td style={td}>
                  <input defaultValue={r.memo}
                    onBlur={e => {
                      if (e.target.value !== r.memo) patch(r.id, { memo: e.target.value })
                    }}
                    placeholder="申し送り"
                    style={{ fontSize: 12, padding: '3px 6px', width: '100%',
                      border: `1px solid ${C.line}`, borderRadius: 4 }} />
                </td>
                {/* 3通りで見分ける。答え待ちは赤、やり取りが残っているものは青、
                    何も無いものは薄く。0件と1件が同じ見た目だと見落とす */}
                <td style={{ ...td, whiteSpace: 'nowrap' }}>
                  {(() => {
                    const has = r.notes.length > 0
                    const c = r.open_count
                      ? { bd: C.bad, bg: '#fef2f2', fg: C.bad }
                      : has
                        ? { bd: '#bfdbfe', bg: '#eff6ff', fg: C.key }
                        : { bd: C.line, bg: '#fff', fg: '#94a3b8' }
                    return (
                      <button onClick={() => setOpen(o => ({ ...o, [r.id]: !o[r.id] }))}
                        style={{ fontSize: 12, padding: '3px 10px',
                          border: `1px solid ${c.bd}`, background: c.bg,
                          color: c.fg, borderRadius: 4, cursor: 'pointer',
                          fontWeight: has || r.open_count ? 700 : 400 }}>
                        {r.open_count
                          ? `未回答 ${r.open_count}`
                          : `やり取り ${r.notes.length}`}
                      </button>
                    )
                  })()}
                </td>
                {!share && (
                  <td style={td}>
                    <button onClick={() => del(r.id)}
                      style={{ fontSize: 11, padding: '3px 8px', border: 'none',
                        background: 'none', color: C.sub, cursor: 'pointer' }}>
                      削除
                    </button>
                  </td>
                )}
              </tr>,
              isOpen && (
                <tr key={`${r.id}-notes`}>
                  <td colSpan={share ? 8 : 9}
                    style={{ ...td, background: '#f8fafc' }}>
                    {r.notes.map(n => (
                      <div key={n.id} style={{ marginBottom: 8, paddingBottom: 8,
                        borderBottom: `1px solid ${C.line}` }}>
                        <div style={{ fontSize: 12, color: C.text,
                          display: 'flex', alignItems: 'flex-start', gap: 6 }}>
                          <span style={{ flex: 1 }}>
                            <b style={{ color: n.who === 'staff' ? C.key : C.warn }}>
                              {WHO_LABEL[n.who] || n.who}
                            </b>
                            ：{n.body}
                          </span>
                          {!share && (
                            <button onClick={() => removeNote(r.id, n.id)}
                              title="このやり取りを消す"
                              style={{ fontSize: 11, color: C.bad,
                                background: 'none', border: 'none',
                                cursor: 'pointer', padding: 0 }}>削除</button>
                          )}
                        </div>
                        {n.answer ? (
                          <div style={{ fontSize: 12, color: C.good,
                            marginTop: 3, paddingLeft: 14 }}>
                            → {n.answer}
                          </div>
                        ) : (
                          <div style={{ display: 'flex', gap: 6, marginTop: 4,
                            paddingLeft: 14 }}>
                            <input value={ans[n.id] || ''}
                              onChange={e => setAns(a => ({ ...a, [n.id]: e.target.value }))}
                              onKeyDown={e => { if (e.key === 'Enter') reply(r.id, n.id) }}
                              placeholder="答えを書く"
                              style={{ fontSize: 12, padding: '4px 8px', flex: 1,
                                border: `1px solid ${C.line}`, borderRadius: 4 }} />
                            <button onClick={() => reply(r.id, n.id)}
                              style={{ fontSize: 12, padding: '4px 12px',
                                border: 'none', background: C.good, color: '#fff',
                                borderRadius: 4, cursor: 'pointer' }}>答える</button>
                          </div>
                        )}
                      </div>
                    ))}
                    <div style={{ display: 'flex', gap: 6 }}>
                      <input value={draft[r.id] || ''}
                        onChange={e => setDraft(d => ({ ...d, [r.id]: e.target.value }))}
                        onKeyDown={e => { if (e.key === 'Enter') ask(r.id) }}
                        placeholder="質問・連絡を書く（送ると相手の番になり、チャットワークにも知らせが飛びます）"
                        style={{ fontSize: 12, padding: '5px 8px', flex: 1,
                          border: `1px solid ${C.line}`, borderRadius: 4 }} />
                      <button onClick={() => ask(r.id)}
                        style={{ fontSize: 12, padding: '5px 14px', border: 'none',
                          background: C.key, color: '#fff', borderRadius: 4,
                          cursor: 'pointer' }}>送る</button>
                    </div>
                  </td>
                </tr>
              ),
            ]
          })}
          {!shown.length && (
            <tr><td colSpan={share ? 8 : 9}
              style={{ ...td, color: C.sub, textAlign: 'center', padding: 24 }}>
              {rows.length ? '絞り込みに合うものがありません' : 'まだ1件もありません'}
            </td></tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
