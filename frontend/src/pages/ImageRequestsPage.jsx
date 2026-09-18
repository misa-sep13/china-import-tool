import { useCallback, useEffect, useState } from 'react'
import api from '../api/client'
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
    || matchesQuery(q, [r.sku, r.name, r.doc_name, r.assignee, r.detail]))

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
          placeholder="SKU・商品名・担当で絞り込み"
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
            <Field label="担当" w={110}>
              <input value={form.assignee}
                onChange={e => setForm(f => ({ ...f, assignee: e.target.value }))} />
            </Field>
            <Field label="希望納期" w={130}>
              <input type="date" value={form.due_date}
                onChange={e => setForm(f => ({ ...f, due_date: e.target.value }))} />
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
              {['依頼日', '', 'SKU', '商品名', '商品補足', '担当', '希望納期',
                '進み具合', '連絡', ''].map((h, i) => (
                  <th key={i} style={th}>{h}</th>
                ))}
            </tr>
          </thead>
          <tbody>
            {shown.length === 0 && (
              <tr><td style={{ ...td, color: C.sub, padding: 20 }} colSpan={10}>
                {q ? `「${q}」に当てはまる依頼はありません。`
                  : '作業中の依頼はありません。'}
              </td></tr>
            )}
            {shown.map(r => {
              const c = STATUS_COLOR[r.status] || STATUS_COLOR.requested
              return (
                <tr key={r.id}>
                  <td style={{ ...td, whiteSpace: 'nowrap', color: C.sub }}>
                    {(r.sent_at || r.created_at || '').slice(5, 10).replace('-', '/')}
                  </td>
                  <td style={{ ...td, whiteSpace: 'nowrap', color: C.sub }}>
                    {SOURCE_LABEL[r.source] || r.source}
                  </td>
                  <td style={{ ...td, fontFamily: 'monospace', fontWeight: 600 }}>
                    {r.sku}
                  </td>
                  <td style={td}>
                    {r.name}
                    {r.doc_name && (
                      <div style={{ fontSize: 10, color: C.sub }}>{r.doc_name}</div>
                    )}
                    <div style={{ display: 'flex', gap: 8 }}>
                      {r.main_url && (
                        <a href={r.main_url} target="_blank" rel="noreferrer"
                          style={{ fontSize: 11 }}
                          title="仕入元のページ。画像素材と実物の作りはここで見られます">
                          1688の商品ページ
                        </a>
                      )}
                      {r.ref_url && (
                        <a href={r.ref_url} target="_blank" rel="noreferrer"
                          style={{ fontSize: 11 }}
                          title="競合のAmazon商品ページ">競合のAmazon</a>
                      )}
                    </div>
                  </td>
                  {/* デザイナーに伝えたいこと。シートの「商品補足」がそのまま入る */}
                  <td style={td}>
                    {share ? (
                      <span style={{ whiteSpace: 'pre-wrap' }}>{r.detail || '—'}</span>
                    ) : (
                      <textarea defaultValue={r.detail} rows={2}
                        placeholder="商品補足（デザイナーに伝えたいこと）"
                        onBlur={e => {
                          if (e.target.value !== r.detail)
                            patch(r.id, { detail: e.target.value })
                        }}
                        style={{ width: 230, fontSize: 12 }} />
                    )}
                  </td>
                  <td style={td}>{r.assignee || '—'}</td>
                  <td style={{ ...td, whiteSpace: 'nowrap' }}>{r.due_date || '—'}</td>
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
                  <td style={td}>
                    <input defaultValue={r.reply} placeholder="連絡・質問"
                      onBlur={e => {
                        if (e.target.value !== r.reply)
                          patch(r.id, { reply: e.target.value })
                      }}
                      style={{ width: 170, fontSize: 12 }} />
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

      <div style={{ fontSize: 11, color: C.sub, marginTop: 8, lineHeight: 1.8 }}>
        進み具合を「完了」にすると、この一覧から消えます（「完了したものも出す」で戻せます）。
        {!share && <><br />
          リサーチシートで「💬 Chatworkで送る」を押すと、ここに自動で1件増えます。
        </>}
      </div>
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
