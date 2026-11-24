import { useEffect, useMemo, useState } from 'react'
import api from '../api/client'

/**
 * 秘書。毎月くり返す仕事と、都度の仕事を1か所で見る。
 *
 * 建設と物販が混ざるので区分で分ける。ツールは「いつ・何を」を出すところまでで、
 * やるかどうかは人が決める。見落とすと困るものだけが出ていればよく、
 * 全部を管理しようとしない。
 *
 *   やること … 期限が近づいたものと、過ぎたもの
 *   今月     … その月の一覧。済んだものも見える
 *   決まり   … くり返しの設定
 */

const C = {
  line: '#e5e7eb', sub: '#64748b', text: '#0f172a',
  good: '#16a34a', bad: '#dc2626', warn: '#b45309', blue: '#2563eb',
}

const AREA_COLOR = {
  construction: '#0f766e',
  resale: '#7c3aed',
  money: '#b45309',
}

const th = { padding: '8px 10px', textAlign: 'left', fontSize: 12, color: C.sub, background: '#f8fafc', whiteSpace: 'nowrap' }
const td = { padding: '8px 10px', borderTop: `1px solid ${C.line}`, fontSize: 13, verticalAlign: 'top' }

const todayStr = () => new Date().toISOString().slice(0, 10)

const yen = (n) => (n == null ? '' : `¥${Math.round(n).toLocaleString('ja-JP')}`)

// 原本のPDF。ログインの合言葉が要るので、リンクで開かずに取ってから開く
async function openPermit(permitId) {
  const r = await api.get(`/import-permits/${permitId}/pdf`, { responseType: 'blob' })
  const href = URL.createObjectURL(r.data)
  window.open(href, '_blank', 'noopener')
  setTimeout(() => URL.revokeObjectURL(href), 60000)
}

const thisPeriod = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

const shiftPeriod = (period, offset) => {
  const y = Number(period.slice(0, 4))
  const m = Number(period.slice(5, 7))
  const total = y * 12 + (m - 1) + offset
  return `${Math.floor(total / 12)}-${String((total % 12) + 1).padStart(2, '0')}`
}

const periodLabel = (p) => (p ? `${Number(p.slice(5, 7))}月分` : '')

// 期限までの言い方。数字より「あと何日」のほうが判断しやすい
const dueLabel = (run) => {
  const n = run.days_left
  if (run.status !== 'open') return ''
  if (n < 0) return `${-n}日 過ぎています`
  if (n === 0) return '今日'
  if (n === 1) return '明日'
  return `あと${n}日`
}

const dueColor = (run) => {
  if (run.status !== 'open') return C.sub
  if (run.days_left < 0) return C.bad
  if (run.days_left <= 1) return C.warn
  return C.sub
}

function AreaTag({ run }) {
  const color = AREA_COLOR[run.area] || C.sub
  return (
    <span style={{
      fontSize: 11, fontWeight: 700, color, border: `1px solid ${color}33`,
      background: `${color}11`, borderRadius: 4, padding: '2px 6px', whiteSpace: 'nowrap',
    }}>{run.area_label}</span>
  )
}

/** 1件の行。手順があれば開いて見られる */
function RunRow({ run, onDone, onSkip, onReopen, busy }) {
  const [open, setOpen] = useState(false)
  const steps = String(run.checklist || '').split('\n').map(s => s.trim()).filter(Boolean)
  const done = run.status !== 'open'

  return (
    <>
      <tr style={{ background: run.overdue ? '#fef2f2' : undefined }}>
        <td style={td}><AreaTag run={run} /></td>
        <td style={td}>
          <div style={{
            fontWeight: 600, color: done ? C.sub : C.text,
            textDecoration: run.status === 'done' ? 'line-through' : undefined,
          }}>
            {run.title}
            {run.target_period && (
              <span style={{ marginLeft: 6, fontSize: 12, color: C.blue, fontWeight: 600 }}>
                （{periodLabel(run.target_period)}）
              </span>
            )}
          </div>
          {run.amount != null && (
            <span style={{ marginRight: 10, fontSize: 13, fontWeight: 700, color: C.text }}>
              {yen(run.amount)}
            </span>
          )}
          {run.permit_id && (
            <button onClick={() => openPermit(run.permit_id)} style={{
              marginRight: 10, fontSize: 12, color: C.blue, background: 'none',
              border: 'none', cursor: 'pointer', padding: 0, textDecoration: 'underline',
            }}>請求書を見る</button>
          )}
          {run.ref_url && (
            <a href={run.ref_url} target={run.ref_url.startsWith('#') ? undefined : '_blank'}
              rel="noreferrer"
              style={{ fontSize: 12, color: C.blue }}>開く</a>
          )}
          {steps.length > 0 && (
            <button onClick={() => setOpen(v => !v)} style={{
              marginLeft: run.ref_url ? 10 : 0, fontSize: 12, color: C.sub,
              background: 'none', border: 'none', cursor: 'pointer', padding: 0,
            }}>{open ? '手順を閉じる' : `手順 ${steps.length}`}</button>
          )}
          {run.status === 'skipped' && (
            <span style={{ marginLeft: 8, fontSize: 12, color: C.sub }}>見送り</span>
          )}
        </td>
        <td style={{ ...td, whiteSpace: 'nowrap' }}>
          <div style={{ fontSize: 12, color: C.sub }}>{run.due_date.slice(5).replace('-', '/')}</div>
          <div style={{ fontSize: 12, color: dueColor(run), fontWeight: run.overdue ? 700 : 400 }}>
            {dueLabel(run)}
          </div>
        </td>
        <td style={{ ...td, whiteSpace: 'nowrap', textAlign: 'right' }}>
          {done ? (
            <button onClick={() => onReopen(run)} disabled={busy} style={btnGhost}>戻す</button>
          ) : (
            <>
              <button onClick={() => onDone(run)} disabled={busy} style={btnMain}>やった</button>
              <button onClick={() => onSkip(run)} disabled={busy} style={{ ...btnGhost, marginLeft: 6 }}>今月はしない</button>
            </>
          )}
        </td>
      </tr>
      {open && steps.length > 0 && (
        <tr>
          <td />
          <td colSpan={3} style={{ ...td, borderTop: 'none', paddingTop: 0 }}>
            <ul style={{ margin: '4px 0 8px', paddingLeft: 18, color: C.sub, fontSize: 13 }}>
              {steps.map((s, i) => <li key={i} style={{ marginBottom: 2 }}>{s}</li>)}
            </ul>
          </td>
        </tr>
      )}
    </>
  )
}

const btnMain = {
  fontSize: 12, fontWeight: 700, color: '#fff', background: C.good,
  border: 'none', borderRadius: 6, padding: '5px 12px', cursor: 'pointer',
}
const btnGhost = {
  fontSize: 12, color: C.sub, background: '#fff',
  border: `1px solid ${C.line}`, borderRadius: 6, padding: '5px 10px', cursor: 'pointer',
}

export default function SecretaryPage() {
  const [tab, setTab] = useState('today')
  const [runs, setRuns] = useState([])
  const [tasks, setTasks] = useState([])
  const [senders, setSenders] = useState([])
  const [rules, setRules] = useState([])
  const [notify, setNotify] = useState(null)
  const [forwards, setForwards] = useState(null)
  const [period, setPeriod] = useState(thisPeriod())
  const [ahead, setAhead] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [adding, setAdding] = useState(false)
  const [draft, setDraft] = useState({ title: '', area: 'construction', due_date: todayStr() })
  const [fetching, setFetching] = useState(false)
  const [fetchResult, setFetchResult] = useState(null)

  const loadToday = async () => {
    const r = await api.get('/secretary/today', { params: { days: ahead } })
    setRuns(r.data.runs || [])
  }
  const loadMonth = async (p) => {
    const r = await api.get('/secretary/runs', { params: { period: p } })
    setRuns(r.data.runs || [])
  }
  const loadTasks = async () => {
    const r = await api.get('/secretary/tasks')
    setTasks(r.data.tasks || [])
  }
  const loadForwards = async () => {
    const r = await api.get('/secretary/forwards')
    setForwards(r.data)
  }
  const loadNotify = async () => {
    const r = await api.get('/secretary/notify')
    setNotify(r.data)
  }
  const loadSenders = async () => {
    const r = await api.get('/secretary/senders')
    setSenders(r.data.senders || [])
    setRules(r.data.due_rules || [])
  }

  const reload = async () => {
    setError('')
    try {
      if (tab === 'today') await loadToday()
      else if (tab === 'month') await loadMonth(period)
      else if (tab === 'senders') await loadSenders()
      else if (tab === 'notify') await loadNotify()
      else if (tab === 'videos') await loadForwards()
      else await loadTasks()
    } catch (e) {
      setError(e.response?.data?.detail || e.message)
    }
  }

  useEffect(() => { reload() }, [tab, period, ahead])

  const setStatus = async (run, status) => {
    setBusy(true)
    setError('')
    try {
      // 変える項目だけを送る。他の値は触らない
      await api.patch(`/secretary/runs/${run.id}`, { status })
      await reload()
    } catch (e) {
      setError(e.response?.data?.detail || e.message)
    } finally {
      setBusy(false)
    }
  }

  const addRun = async () => {
    if (!draft.title.trim()) return
    setBusy(true)
    setError('')
    try {
      await api.post('/secretary/runs', {
        title: draft.title.trim(), area: draft.area, due_date: draft.due_date,
      })
      setDraft({ title: '', area: draft.area, due_date: todayStr() })
      setAdding(false)
      await reload()
    } catch (e) {
      setError(e.response?.data?.detail || e.message)
    } finally {
      setBusy(false)
    }
  }

  // メールを見に行って、届いている請求を振込待ちにする。
  // 同じ添付は二度入らないので、何度押しても増えない
  const fetchMail = async () => {
    setFetching(true)
    setError('')
    setFetchResult(null)
    try {
      const r = await api.post('/secretary/fetch-mail', { days: 45 })
      setFetchResult(r.data)
      await reload()
    } catch (e) {
      setError(e.response?.data?.detail || e.message)
    } finally {
      setFetching(false)
    }
  }

  const overdue = useMemo(() => runs.filter(r => r.overdue), [runs])
  const rest = useMemo(() => runs.filter(r => !r.overdue), [runs])

  const Tab = ({ id, label }) => (
    <button onClick={() => setTab(id)} style={{
      fontSize: 13, fontWeight: tab === id ? 700 : 500,
      color: tab === id ? C.text : C.sub,
      background: 'none', border: 'none', borderBottom: `2px solid ${tab === id ? C.blue : 'transparent'}`,
      padding: '8px 14px', cursor: 'pointer',
    }}>{label}</button>
  )

  return (
    <div style={{ padding: 20, maxWidth: 1000 }}>
      <h2 style={{ margin: '0 0 4px', fontSize: 20 }}>🗒️ 秘書</h2>
      <div style={{ color: C.sub, fontSize: 13, marginBottom: 12 }}>
        毎月くり返す仕事と、都度の仕事。期限が近づいたものだけが出ます。
      </div>

      <div style={{ borderBottom: `1px solid ${C.line}`, marginBottom: 12 }}>
        <Tab id="today" label="やること" />
        <Tab id="month" label="今月の一覧" />
        <Tab id="tasks" label="くり返しの決まり" />
        <Tab id="senders" label="請求元のメール" />
        <Tab id="notify" label="毎朝のLINE" />
        <Tab id="videos" label="タオタロウの動画" />
      </div>

      {error && (
        <div style={{ background: '#fef2f2', color: C.bad, border: `1px solid ${C.bad}33`,
          borderRadius: 6, padding: '8px 12px', fontSize: 13, marginBottom: 12 }}>{error}</div>
      )}

      {tab === 'today' && (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
            <label style={{ fontSize: 13, color: C.sub }}>
              先まで見る：
              <select value={ahead} onChange={e => setAhead(Number(e.target.value))}
                style={{ marginLeft: 6, fontSize: 13, padding: '3px 6px' }}>
                <option value={0}>今日の分だけ</option>
                <option value={7}>1週間先まで</option>
                <option value={30}>1か月先まで</option>
              </select>
            </label>
            <div style={{ flex: 1 }} />
            <button onClick={fetchMail} disabled={fetching} style={btnGhost}>
              {fetching ? 'メールを見ています…' : '📥 請求メールを取り込む'}
            </button>
            <button onClick={() => setAdding(v => !v)} style={btnGhost}>＋ 都度の仕事を足す</button>
          </div>

          {fetchResult && (
            <div style={{
              border: `1px solid ${fetchResult.added ? C.good : C.line}33`,
              background: fetchResult.added ? '#f0fdf4' : '#f8fafc',
              borderRadius: 8, padding: '10px 12px', fontSize: 13, marginBottom: 12,
            }}>
              {fetchResult.added
                ? `${fetchResult.added}件の請求書を取り込みました。`
                : '新しい請求書はありませんでした。'}
              {fetchResult.skipped ? `（取り込み済み ${fetchResult.skipped}件）` : ''}
              {fetchResult.message && <span style={{ color: C.warn }}> {fetchResult.message}</span>}
              {(fetchResult.items || []).map((x, i) => (
                <div key={i} style={{ marginTop: 4, color: C.sub }}>
                  {x.sender}：{x.amount != null ? yen(x.amount) : '金額は読めませんでした'}
                  ／{x.due_date} まで
                </div>
              ))}
            </div>
          )}

          {adding && (
            <div style={{ border: `1px solid ${C.line}`, borderRadius: 8, padding: 12, marginBottom: 12,
              display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <input autoFocus value={draft.title} placeholder="やること"
                onChange={e => setDraft({ ...draft, title: e.target.value })}
                onKeyDown={e => { if (e.key === 'Enter') addRun() }}
                style={{ flex: '1 1 260px', fontSize: 13, padding: '6px 8px',
                  border: `1px solid ${C.line}`, borderRadius: 6 }} />
              <select value={draft.area} onChange={e => setDraft({ ...draft, area: e.target.value })}
                style={{ fontSize: 13, padding: '6px' }}>
                <option value="construction">建設</option>
                <option value="resale">物販</option>
                <option value="money">お金まわり</option>
              </select>
              <input type="date" value={draft.due_date}
                onChange={e => setDraft({ ...draft, due_date: e.target.value })}
                style={{ fontSize: 13, padding: '5px 6px', border: `1px solid ${C.line}`, borderRadius: 6 }} />
              <button onClick={addRun} disabled={busy} style={btnMain}>足す</button>
            </div>
          )}

          {runs.length === 0 ? (
            <div style={{ padding: 40, textAlign: 'center', color: C.sub, fontSize: 14 }}>
              今やることはありません。
            </div>
          ) : (
            <>
              {overdue.length > 0 && (
                <div style={{ fontSize: 13, color: C.bad, fontWeight: 700, margin: '4px 0 6px' }}>
                  期限を過ぎているもの {overdue.length}件
                </div>
              )}
              <RunTable runs={[...overdue, ...rest]} busy={busy}
                onDone={r => setStatus(r, 'done')}
                onSkip={r => setStatus(r, 'skipped')}
                onReopen={r => setStatus(r, 'open')} />
            </>
          )}
        </>
      )}

      {tab === 'month' && (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
            <button onClick={() => setPeriod(shiftPeriod(period, -1))} style={btnGhost}>← 前の月</button>
            <div style={{ fontSize: 15, fontWeight: 700, minWidth: 100, textAlign: 'center' }}>
              {period.slice(0, 4)}年{Number(period.slice(5, 7))}月
            </div>
            <button onClick={() => setPeriod(shiftPeriod(period, 1))} style={btnGhost}>次の月 →</button>
            {period !== thisPeriod() && (
              <button onClick={() => setPeriod(thisPeriod())} style={{ ...btnGhost, marginLeft: 4 }}>今月</button>
            )}
            <div style={{ flex: 1 }} />
            <div style={{ fontSize: 13, color: C.sub }}>
              済み {runs.filter(r => r.status === 'done').length} / {runs.length}
            </div>
          </div>
          {runs.length === 0 ? (
            <div style={{ padding: 40, textAlign: 'center', color: C.sub, fontSize: 14 }}>
              この月の仕事はありません。
            </div>
          ) : (
            <RunTable runs={runs} busy={busy}
              onDone={r => setStatus(r, 'done')}
              onSkip={r => setStatus(r, 'skipped')}
              onReopen={r => setStatus(r, 'open')} />
          )}
        </>
      )}

      {tab === 'tasks' && <TaskList tasks={tasks} onChanged={reload} />}
      {tab === 'senders' && <SenderList senders={senders} rules={rules} onChanged={reload} />}
      {tab === 'notify' && <NotifyPanel notify={notify} onChanged={reload} />}
      {tab === 'videos' && <VideoPanel data={forwards} onChanged={reload} />}
    </div>
  )
}

function RunTable({ runs, onDone, onSkip, onReopen, busy }) {
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', border: `1px solid ${C.line}` }}>
      <thead>
        <tr>
          <th style={{ ...th, width: 70 }}>区分</th>
          <th style={th}>やること</th>
          <th style={{ ...th, width: 110 }}>期限</th>
          <th style={{ ...th, width: 190 }} />
        </tr>
      </thead>
      <tbody>
        {runs.map(r => (
          <RunRow key={r.id} run={r} busy={busy}
            onDone={onDone} onSkip={onSkip} onReopen={onReopen} />
        ))}
      </tbody>
    </table>
  )
}

/** タオタロウの動画。届いたらチャットワークへ自動で流れる。その記録 */
function VideoPanel({ data, onChanged }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState('')

  if (!data) return <div style={{ color: C.sub, fontSize: 13 }}>読み込み中...</div>

  const run = async () => {
    setBusy(true)
    setError('')
    setResult('')
    try {
      const r = await api.post('/secretary/forward-videos', { days: 30 })
      setResult(r.data.message
        || (r.data.sent ? `${r.data.sent}件 送りました。`
          : '新しい動画はありませんでした。')
          + (r.data.failed ? `送れなかったもの ${r.data.failed}件。` : ''))
      await onChanged()
    } catch (e) {
      setError(e.response?.data?.detail || e.message)
    } finally {
      setBusy(false)
    }
  }

  const mb = (n) => (n ? `${(n / 1024 / 1024).toFixed(1)}MB` : '')
  const label = { sent: '送信済み', too_large: '大きすぎて送れず', error: '失敗' }
  const color = { sent: C.good, too_large: C.warn, error: C.bad }

  return (
    <div style={{ maxWidth: 820 }}>
      <div style={{ fontSize: 13, color: C.sub, marginBottom: 12 }}>
        <b style={{ color: C.text }}>{data.sender}</b> から動画が添付で届くと、
        チャットワークの北田しずくさんの部屋へ自動で流します（20分おきに見に行きます）。
        同じ動画は二度送りません。チャットワークの上限は1ファイル5MBで、
        超えるものは「送れませんでした」とだけ知らせます。
      </div>

      {error && (
        <div style={{ background: '#fef2f2', color: C.bad, borderRadius: 6,
          padding: '8px 12px', fontSize: 13, marginBottom: 10 }}>{error}</div>
      )}
      {result && (
        <div style={{ background: '#f0fdf4', color: C.good, borderRadius: 6,
          padding: '8px 12px', fontSize: 13, marginBottom: 10 }}>{result}</div>
      )}

      <button onClick={run} disabled={busy} style={{ ...btnGhost, marginBottom: 12 }}>
        {busy ? 'メールを見ています…' : '📥 いま届いている分を送る'}
      </button>

      {(data.forwards || []).length === 0 ? (
        <div style={{ padding: 30, textAlign: 'center', color: C.sub, fontSize: 14 }}>
          まだ送った動画はありません。
        </div>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse', border: `1px solid ${C.line}` }}>
          <thead>
            <tr>
              <th style={{ ...th, width: 100 }}>状態</th>
              <th style={th}>動画</th>
              <th style={{ ...th, width: 80 }}>大きさ</th>
              <th style={{ ...th, width: 130 }}>送った日時</th>
            </tr>
          </thead>
          <tbody>
            {data.forwards.map(f => (
              <tr key={f.id}>
                <td style={td}>
                  <span style={{ fontSize: 12, fontWeight: 700,
                    color: color[f.status] || C.sub }}>
                    {label[f.status] || f.status}
                  </span>
                </td>
                <td style={td}>
                  <div style={{ fontWeight: 600 }}>{f.filename}</div>
                  {f.mail_subject && (
                    <div style={{ fontSize: 12, color: C.sub, marginTop: 2 }}>{f.mail_subject}</div>
                  )}
                  {f.error && (
                    <div style={{ fontSize: 12, color: C.bad, marginTop: 2 }}>{f.error}</div>
                  )}
                </td>
                <td style={{ ...td, whiteSpace: 'nowrap' }}>{mb(f.size_bytes)}</td>
                <td style={{ ...td, whiteSpace: 'nowrap', fontSize: 12, color: C.sub }}>
                  {f.sent_at ? f.sent_at.slice(0, 16).replace('T', ' ') : (f.mail_date || '')}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

/** 毎朝のLINE。何時に送るかと、いま送ると何が届くか */
function NotifyPanel({ notify, onChanged }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [sent, setSent] = useState('')

  if (!notify) return <div style={{ color: C.sub, fontSize: 13 }}>読み込み中...</div>

  const patch = async (changes) => {
    setBusy(true)
    setError('')
    setSent('')
    try {
      // 変える項目だけを送る
      await api.patch('/secretary/notify', changes)
      await onChanged()
    } catch (e) {
      setError(e.response?.data?.detail || e.message)
    } finally {
      setBusy(false)
    }
  }

  const test = async () => {
    setBusy(true)
    setError('')
    setSent('')
    try {
      const r = await api.post('/secretary/notify/test')
      setSent(r.data.sent ? '送りました。LINEを見てください。' : (r.data.reason || ''))
      await onChanged()   // 「最後に送ったの」を出し直す
    } catch (e) {
      setError(e.response?.data?.detail || e.message)
    } finally {
      setBusy(false)
    }
  }

  const row = { display: 'flex', alignItems: 'center', gap: 10, padding: '10px 0',
    borderTop: `1px solid ${C.line}`, fontSize: 13 }

  return (
    <div style={{ maxWidth: 680 }}>
      {!notify.configured && (
        <div style={{ background: '#fffbeb', border: `1px solid ${C.warn}33`, color: C.warn,
          borderRadius: 8, padding: '10px 12px', fontSize: 13, marginBottom: 12 }}>
          LINEのトークンがまだ入っていません。サーバーの環境変数に
          <b> LINE_CHANNEL_TOKEN </b>（LINE公式アカウントのチャネルアクセストークン）と
          <b> LINE_TO </b>（送り先のユーザーID）を入れてください。
          トークンは「そのアカウントとして送れる権限」そのものなので、画面では預かりません。
        </div>
      )}
      {error && (
        <div style={{ background: '#fef2f2', color: C.bad, borderRadius: 6,
          padding: '8px 12px', fontSize: 13, marginBottom: 10 }}>{error}</div>
      )}
      {sent && (
        <div style={{ background: '#f0fdf4', color: C.good, borderRadius: 6,
          padding: '8px 12px', fontSize: 13, marginBottom: 10 }}>{sent}</div>
      )}

      <div style={row}>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', whiteSpace: 'nowrap' }}>
          <input type="checkbox" checked={notify.enabled} disabled={busy}
            onChange={e => patch({ enabled: e.target.checked })} />
          毎朝LINEで知らせる
        </label>
      </div>

      <div style={row}>
        <div style={{ width: 160, color: C.sub }}>送る時刻（日本時間）</div>
        <select value={notify.hour} disabled={busy}
          onChange={e => patch({ hour: Number(e.target.value) })}
          style={{ fontSize: 13, padding: '4px 6px' }}>
          {Array.from({ length: 24 }, (_, i) => i).map(h => (
            <option key={h} value={h}>{h}時台</option>
          ))}
        </select>
        <span style={{ color: C.sub, fontSize: 12 }}>その時刻を過ぎたら、その日1通だけ届きます</span>
      </div>

      <div style={row}>
        <div style={{ width: 160, color: C.sub }}>入れる範囲</div>
        <select value={notify.ahead_days} disabled={busy}
          onChange={e => patch({ ahead_days: Number(e.target.value) })}
          style={{ fontSize: 13, padding: '4px 6px' }}>
          <option value={0}>今日の分と遅れている分</option>
          <option value={3}>3日先まで</option>
          <option value={7}>1週間先まで</option>
        </select>
      </div>

      <div style={row}>
        <div style={{ width: 160, color: C.sub }}>送る前に</div>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', whiteSpace: 'nowrap' }}>
          <input type="checkbox" checked={notify.fetch_mail} disabled={busy}
            onChange={e => patch({ fetch_mail: e.target.checked })} />
          請求メールを見に行く
        </label>
        <span style={{ color: C.sub, fontSize: 12 }}>その朝に届いた請求も同じ1通に入ります</span>
      </div>

      <div style={row}>
        <div style={{ width: 160, color: C.sub }}>やることが無い日</div>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', whiteSpace: 'nowrap' }}>
          <input type="checkbox" checked={notify.send_when_empty} disabled={busy}
            onChange={e => patch({ send_when_empty: e.target.checked })} />
          「ありません」も送る
        </label>
      </div>

      <div style={{ ...row, borderBottom: `1px solid ${C.line}` }}>
        <div style={{ width: 160, color: C.sub }}>最後に送ったの</div>
        <div>
          {notify.last_sent_at ? notify.last_sent_at.slice(0, 16).replace('T', ' ') : 'まだありません'}
          {notify.last_error && (
            <div style={{ color: C.bad, fontSize: 12, marginTop: 2 }}>
              前回の失敗：{notify.last_error}
            </div>
          )}
        </div>
      </div>

      <div style={{ marginTop: 16 }}>
        <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 6 }}>いま送るとこう届きます</div>
        <pre style={{
          background: '#f8fafc', border: `1px solid ${C.line}`, borderRadius: 8,
          padding: 12, fontSize: 13, whiteSpace: 'pre-wrap', margin: 0,
          fontFamily: 'inherit', color: notify.preview ? C.text : C.sub,
        }}>{notify.preview || '今日やることはありません。'}</pre>
        <button onClick={test} disabled={busy || !notify.configured}
          style={{ ...btnMain, marginTop: 10 }}>
          {busy ? '送っています…' : '試しに1通送る'}
        </button>
      </div>
    </div>
  )
}

/** 請求元のメール。ここに登録した差出人だけを見に行く */
function SenderList({ senders, rules, onChanged }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [adding, setAdding] = useState(false)
  const [draft, setDraft] = useState({ name: '', match_from: '', due_rule: 'eom', due_day: 10 })

  const patch = async (s, changes) => {
    setBusy(true)
    setError('')
    try {
      // 変える項目だけを送る
      await api.patch(`/secretary/senders/${s.id}`, changes)
      await onChanged()
    } catch (e) {
      setError(e.response?.data?.detail || e.message)
    } finally {
      setBusy(false)
    }
  }

  const add = async () => {
    setBusy(true)
    setError('')
    try {
      await api.post('/secretary/senders', draft)
      setDraft({ name: '', match_from: '', due_rule: 'eom', due_day: 10 })
      setAdding(false)
      await onChanged()
    } catch (e) {
      setError(e.response?.data?.detail || e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div style={{ fontSize: 13, color: C.sub, marginBottom: 10 }}>
        ここに登録した差出人からメールが届くと、添付の請求書を月次管理表の「書類」に入れて、
        支払期限つきの振込待ちにします。件名では絞らないので、相手が件名を変えても拾えます。
      </div>
      {error && (
        <div style={{ background: '#fef2f2', color: C.bad, borderRadius: 6,
          padding: '8px 12px', fontSize: 13, marginBottom: 10 }}>{error}</div>
      )}
      <table style={{ width: '100%', borderCollapse: 'collapse', border: `1px solid ${C.line}` }}>
        <thead>
          <tr>
            <th style={th}>請求元</th>
            <th style={th}>差出人のメールアドレス</th>
            <th style={{ ...th, width: 200 }}>支払期限</th>
            <th style={{ ...th, width: 130 }}>何日前から出す</th>
            <th style={{ ...th, width: 80 }} />
          </tr>
        </thead>
        <tbody>
          {senders.map(s => (
            <tr key={s.id} style={{ opacity: s.active ? 1 : 0.45 }}>
              <td style={td}>
                <div style={{ fontWeight: 600 }}>{s.name}</div>
                {s.note && <div style={{ fontSize: 12, color: C.sub, marginTop: 2 }}>{s.note}</div>}
                {s.last_found_at && (
                  <div style={{ fontSize: 12, color: C.sub, marginTop: 2 }}>
                    最後に届いたのは {s.last_found_at.slice(0, 10)}
                  </div>
                )}
              </td>
              <td style={{ ...td, fontSize: 12, wordBreak: 'break-all' }}>{s.match_from}</td>
              <td style={td}>
                <select value={s.due_rule} disabled={busy}
                  onChange={e => patch(s, { due_rule: e.target.value })}
                  style={{ fontSize: 13, padding: '3px 4px', maxWidth: 180 }}>
                  {rules.map(r => <option key={r.key} value={r.key}>{r.label}</option>)}
                </select>
                {(s.due_rule === 'day' || s.due_rule === 'days') && (
                  <select value={s.due_day} disabled={busy}
                    onChange={e => patch(s, { due_day: Number(e.target.value) })}
                    style={{ fontSize: 13, padding: '3px 4px', marginTop: 4 }}>
                    {Array.from({ length: 28 }, (_, i) => i + 1).map(d => (
                      <option key={d} value={d}>{s.due_rule === 'day' ? `${d}日` : `${d}日後`}</option>
                    ))}
                  </select>
                )}
              </td>
              <td style={td}>
                <select value={s.lead_days} disabled={busy}
                  onChange={e => patch(s, { lead_days: Number(e.target.value) })}
                  style={{ fontSize: 13, padding: '3px 4px' }}>
                  {[0, 3, 5, 7, 10, 14].map(d => (
                    <option key={d} value={d}>{d === 0 ? '当日' : `${d}日前`}</option>
                  ))}
                </select>
              </td>
              <td style={{ ...td, textAlign: 'right' }}>
                <button disabled={busy} onClick={() => patch(s, { active: !s.active })} style={btnGhost}>
                  {s.active ? '止める' : '戻す'}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div style={{ marginTop: 10 }}>
        {adding ? (
          <div style={{ border: `1px solid ${C.line}`, borderRadius: 8, padding: 12,
            display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <input autoFocus placeholder="請求元の名前" value={draft.name}
              onChange={e => setDraft({ ...draft, name: e.target.value })}
              style={{ fontSize: 13, padding: '6px 8px', border: `1px solid ${C.line}`, borderRadius: 6 }} />
            <input placeholder="差出人のメールアドレス" value={draft.match_from}
              onChange={e => setDraft({ ...draft, match_from: e.target.value })}
              style={{ flex: '1 1 240px', fontSize: 13, padding: '6px 8px',
                border: `1px solid ${C.line}`, borderRadius: 6 }} />
            <select value={draft.due_rule}
              onChange={e => setDraft({ ...draft, due_rule: e.target.value })}
              style={{ fontSize: 13, padding: '6px' }}>
              {rules.map(r => <option key={r.key} value={r.key}>{r.label}</option>)}
            </select>
            <button onClick={add} disabled={busy} style={btnMain}>足す</button>
            <button onClick={() => setAdding(false)} style={btnGhost}>やめる</button>
          </div>
        ) : (
          <button onClick={() => setAdding(true)} style={btnGhost}>＋ 請求元を足す</button>
        )}
      </div>
    </>
  )
}

/** くり返しの決まり。日付と「何日前から出すか」をここで直す */
function TaskList({ tasks, onChanged }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const patch = async (task, changes) => {
    setBusy(true)
    setError('')
    try {
      // 変える項目だけを送る。送らなかった項目はサーバー側で今の値のまま残る
      await api.patch(`/secretary/tasks/${task.id}`, changes)
      await onChanged()
    } catch (e) {
      setError(e.response?.data?.detail || e.message)
    } finally {
      setBusy(false)
    }
  }

  // 選択肢に今の値が無いと、ブラウザが勝手に先頭（＝当日・月末）を選んだ顔をする。
  // 触っていないのに値が変わって見えるので、今の値は必ず混ぜておく
  const withCurrent = (list, current) => (
    list.includes(current) ? list : [...list, current].sort((a, b) => a - b)
  )

  return (
    <>
      {error && (
        <div style={{ background: '#fef2f2', color: C.bad, borderRadius: 6,
          padding: '8px 12px', fontSize: 13, marginBottom: 10 }}>{error}</div>
      )}
      <table style={{ width: '100%', borderCollapse: 'collapse', border: `1px solid ${C.line}` }}>
        <thead>
          <tr>
            <th style={{ ...th, width: 70 }}>区分</th>
            <th style={th}>くり返す仕事</th>
            <th style={{ ...th, width: 90 }}>いつ</th>
            <th style={{ ...th, width: 130 }}>何日前から出す</th>
            <th style={{ ...th, width: 80 }} />
          </tr>
        </thead>
        <tbody>
          {tasks.map(t => (
            <tr key={t.id} style={{ opacity: t.active ? 1 : 0.45 }}>
              <td style={td}><AreaTag run={t} /></td>
              <td style={td}>
                <div style={{ fontWeight: 600 }}>{t.title}</div>
                {t.note && <div style={{ fontSize: 12, color: C.sub, marginTop: 2 }}>{t.note}</div>}
                {t.target_month_offset !== 0 && (
                  <div style={{ fontSize: 12, color: C.blue, marginTop: 2 }}>
                    {-t.target_month_offset}か月前の分が対象
                  </div>
                )}
              </td>
              <td style={{ ...td, whiteSpace: 'nowrap' }}>
                <select value={t.day_of_month ?? ''} disabled={busy || t.cadence === 'adhoc'}
                  onChange={e => patch(t, { day_of_month: Number(e.target.value) })}
                  style={{ fontSize: 13, padding: '3px 4px' }}>
                  <option value={0}>月末</option>
                  {withCurrent(Array.from({ length: 28 }, (_, i) => i + 1),
                    t.day_of_month || 1).map(d => (
                    <option key={d} value={d}>{d}日</option>
                  ))}
                </select>
              </td>
              <td style={td}>
                <select value={t.lead_days} disabled={busy}
                  onChange={e => patch(t, { lead_days: Number(e.target.value) })}
                  style={{ fontSize: 13, padding: '3px 4px' }}>
                  {withCurrent([0, 1, 2, 3, 5, 7, 10, 14], t.lead_days || 0).map(d => (
                    <option key={d} value={d}>{d === 0 ? '当日' : `${d}日前`}</option>
                  ))}
                </select>
              </td>
              <td style={{ ...td, textAlign: 'right' }}>
                <button disabled={busy} onClick={() => patch(t, { active: !t.active })} style={btnGhost}>
                  {t.active ? '止める' : '戻す'}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ fontSize: 12, color: C.sub, marginTop: 8 }}>
        日付は聞き取りから置いたものです。違っていればここで直してください。
      </div>
    </>
  )
}
