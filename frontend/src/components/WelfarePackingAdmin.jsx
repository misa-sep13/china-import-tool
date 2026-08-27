import { useMemo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'
import initialTasks from '../data/welfarePackingTasks.json'

const yen = (v) => `¥${Math.round(v || 0).toLocaleString()}`
const today = () => new Date().toISOString().slice(0, 10)
const thisMonth = () => today().slice(0, 7)
const fmtMonth = (m) => {
  const mm = String(m || '').split('-')[1]
  return mm ? `${Number(mm)}月分` : m
}

/**
 * 再梱包の作業依頼を作る・直す管理画面。
 *
 * 梱包材・梱包方法・単価・1セットの数は「作業マスタ」に持たせてあるので、
 * 作業を選べば自動で入る。今回だけ違う場合はここで上書きできる。
 */
export default function WelfarePackingAdmin() {
  const qc = useQueryClient()
  const [tab, setTab] = useState('orders')
  const [month, setMonth] = useState(thisMonth())
  const [form, setForm] = useState({
    order_date: today(), priority: '', task_id: '', set_count: '', note: '',
  })
  const [taskQuery, setTaskQuery] = useState('')
  const [taskSearch, setTaskSearch] = useState('')
  // 荷受けから作った候補。既定は直近30日ぶんだけ見る
  // （全期間だと過去の未処理分まで積み上がって実態と合わない）
  const [since, setSince] = useState(() => {
    const d = new Date(); d.setDate(d.getDate() - 30)
    return d.toISOString().slice(0, 10)
  })
  const [picked, setPicked] = useState({})   // {task_id: セット数}
  // 商品と紐づかない作業（郵便書簡・封筒など）を手で足すためのフォーム
  const [newTask, setNewTask] = useState({
    name: '', sku: '', set_qty: '', unit_price: '', packing_material: '', packing_method: '',
  })

  const { data } = useQuery({
    queryKey: ['packing-orders', month],
    queryFn: () => api.get('/welfare/packing-orders', { params: { month } }).then(r => r.data),
  })
  const { data: monthsData } = useQuery({
    queryKey: ['packing-order-months'],
    queryFn: () => api.get('/welfare/packing-orders/months').then(r => r.data),
  })
  const { data: tasksData } = useQuery({
    queryKey: ['packing-tasks'],
    queryFn: () => api.get('/welfare/packing-tasks').then(r => r.data),
  })
  const { data: candData, isFetching: candLoading } = useQuery({
    queryKey: ['packing-candidates', since],
    queryFn: () => api.get('/welfare/packing-orders/candidates',
      { params: since ? { since } : {} }).then(r => r.data),
  })

  const rows = data?.items || []
  const months = monthsData?.months || []
  const tasks = tasksData?.tasks || []
  const fromReceiving = candData?.candidates || []   // 荷受けから作った依頼の候補

  const candidates = useMemo(() => {
    const q = taskQuery.trim().toLowerCase()
    if (!q) return []
    return tasks.filter(t =>
      (t.name || '').toLowerCase().includes(q) || (t.sku || '').toLowerCase().includes(q)
    ).slice(0, 12)
  }, [tasks, taskQuery])

  const selected = useMemo(
    () => tasks.find(t => t.id === Number(form.task_id)) || null,
    [tasks, form.task_id]
  )

  const filteredTasks = useMemo(() => {
    const q = taskSearch.trim().toLowerCase()
    if (!q) return tasks
    return tasks.filter(t =>
      (t.name || '').toLowerCase().includes(q) || (t.sku || '').toLowerCase().includes(q)
    )
  }, [tasks, taskSearch])

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['packing-orders'] })
    qc.invalidateQueries({ queryKey: ['packing-order-months'] })
  }
  const refreshTasks = () => qc.invalidateQueries({ queryKey: ['packing-tasks'] })

  const create = useMutation({
    mutationFn: (body) => api.post('/welfare/packing-orders', body).then(r => r.data),
    onSuccess: () => {
      setForm(f => ({ order_date: f.order_date, priority: '', task_id: '', set_count: '', note: '' }))
      setTaskQuery('')
      refresh()
    },
    onError: (e) => alert('登録エラー: ' + (e.response?.data?.detail || e.message)),
  })

  const update = useMutation({
    mutationFn: ({ id, body }) => api.patch(`/welfare/packing-orders/${id}`, body).then(r => r.data),
    onSuccess: refresh,
    onError: (e) => alert('更新エラー: ' + (e.response?.data?.detail || e.message)),
  })

  const remove = useMutation({
    mutationFn: (id) => api.delete(`/welfare/packing-orders/${id}`),
    onSuccess: refresh,
  })

  // 初回だけ使う想定の取り込み。作業名で照合して上書きするので、
  // 間違えて2回押しても増えない
  const seedTasks = useMutation({
    // deactivate_missing: リストから外した作業は一覧から消す。
    // 取り込む内容を減らしたとき、前回入れた分が残らないようにするため
    mutationFn: () => api.post('/welfare/packing-tasks/bulk', initialTasks,
      { params: { deactivate_missing: true } }).then(r => r.data),
    onSuccess: (d) => {
      refreshTasks()
      alert(`取り込みました（新規${d.created}件 / 更新${d.updated}件`
        + `${d.deactivated ? ` / 一覧から外した${d.deactivated}件` : ''}）`)
    },
    onError: (e) => alert('取り込みエラー: ' + (e.response?.data?.detail || e.message)),
  })

  const removeTask = useMutation({
    mutationFn: (id) => api.delete(`/welfare/packing-tasks/${id}`),
    onSuccess: refreshTasks,
    onError: (e) => alert('削除エラー: ' + (e.response?.data?.detail || e.message)),
  })

  const createTask = useMutation({
    mutationFn: (body) => api.post('/welfare/packing-tasks', body).then(r => r.data),
    onSuccess: () => {
      setNewTask({ name: '', sku: '', set_qty: '', unit_price: '',
        packing_material: '', packing_method: '' })
      refreshTasks()
    },
    onError: (e) => alert('登録エラー: ' + (e.response?.data?.detail || e.message)),
  })

  const updateTask = useMutation({
    mutationFn: ({ id, body }) => api.patch(`/welfare/packing-tasks/${id}`, body).then(r => r.data),
    onSuccess: refreshTasks,
    onError: (e) => alert('更新エラー: ' + (e.response?.data?.detail || e.message)),
  })

  const submit = () => {
    if (!form.task_id) return alert('作業を選んでください')
    if (!form.set_count) return alert('セット数を入れてください')
    create.mutate({
      order_date: form.order_date,
      priority: form.priority === '' ? null : Number(form.priority),
      task_id: Number(form.task_id),
      set_count: Number(form.set_count),
      note: form.note || '',
    })
  }

  return (
    <div className="card">
      <div style={{ display: 'flex', gap: 8, marginBottom: 14 }}>
        {[{ k: 'orders', l: '作業依頼' }, { k: 'tasks', l: `作業マスタ（${tasks.length}）` }].map(t => (
          <button key={t.k} onClick={() => setTab(t.k)}
            className={`btn ${tab === t.k ? 'btn-primary' : 'btn-secondary'}`}>
            {t.l}
          </button>
        ))}
      </div>

      {tab === 'orders' ? (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14, flexWrap: 'wrap' }}>
            <select value={month} onChange={e => setMonth(e.target.value)} style={{ width: 'auto' }}>
              {(months.some(m => m.month === month) ? months : [{ month }, ...months]).map(m => (
                <option key={m.month} value={m.month}>{fmtMonth(m.month)}</option>
              ))}
            </select>
            <div style={{ marginLeft: 'auto', textAlign: 'right' }}>
              <div style={{ fontSize: 12, color: '#64748b' }}>{fmtMonth(month)} 合計</div>
              <div style={{ fontSize: 22, fontWeight: 700 }}>{yen(data?.total_amount)}</div>
            </div>
          </div>

          {/* 荷受けから作った候補。チェックして一括で依頼にする */}
          <details open={fromReceiving.length > 0} style={{ marginBottom: 16 }}>
            <summary style={{ cursor: 'pointer', fontSize: 14, fontWeight: 600, padding: '6px 0' }}>
              荷受けから作業依頼を作る（{candLoading ? '…' : `${fromReceiving.length}件`}）
            </summary>
            <div style={{
              padding: 14, marginTop: 8, borderRadius: 8,
              background: '#f0f9ff', border: '1px solid #bae6fd',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10, flexWrap: 'wrap' }}>
                <label style={{ fontSize: 12, color: '#0c4a6e' }}>いつ以降の荷受けを見るか</label>
                <input type="date" value={since} style={{ width: 'auto' }}
                  onChange={e => setSince(e.target.value)} />
                <span style={{ fontSize: 12, color: '#0369a1' }}>
                  「作業」指示が付いた商品から、作れるセット数を出しています
                </span>
              </div>

              {fromReceiving.length === 0 ? (
                <div style={{ padding: 16, textAlign: 'center', color: '#64748b', fontSize: 13 }}>
                  {candLoading ? '読み込み中...' : '対象の荷受けがありません'}
                </div>
              ) : (
                <>
                  <div style={{ overflowX: 'auto', background: '#fff', borderRadius: 6 }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                      <thead>
                        <tr style={{ background: '#f8fafc', borderBottom: '2px solid #e2e8f0' }}>
                          {['', '作業名', 'SKU', '荷受けの残', '入数', 'セット数', '金額'].map(h => (
                            <th key={h} style={{ padding: '8px 10px', whiteSpace: 'nowrap' }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {fromReceiving.map(x => {
                          const on = picked[x.task_id] !== undefined
                          const count = on ? picked[x.task_id] : x.suggested_set_count
                          return (
                            <tr key={x.task_id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                              <td style={{ padding: '8px 10px', textAlign: 'center' }}>
                                <input type="checkbox" checked={on} style={{ width: 'auto' }}
                                  onChange={e => setPicked(p => {
                                    const n = { ...p }
                                    if (e.target.checked) n[x.task_id] = x.suggested_set_count
                                    else delete n[x.task_id]
                                    return n
                                  })} />
                              </td>
                              <td style={{ padding: '8px 10px' }}>
                                <div style={{ fontWeight: 600 }}>{x.task_name}</div>
                                <div style={{ fontSize: 11, color: '#94a3b8' }}>
                                  {x.sources.length}件の荷受けから
                                </div>
                              </td>
                              <td style={{ padding: '8px 10px' }}>{x.sku}</td>
                              <td style={{ padding: '8px 10px', textAlign: 'right' }}>{x.remaining_qty}</td>
                              <td style={{ padding: '8px 10px', textAlign: 'right' }}>{x.set_qty || 1}</td>
                              <td style={{ padding: '8px 10px', textAlign: 'right' }}>
                                <input type="number" value={count} style={{ width: 80 }}
                                  disabled={!on}
                                  onChange={e => setPicked(p => ({ ...p, [x.task_id]: Number(e.target.value || 0) }))} />
                              </td>
                              <td style={{ padding: '8px 10px', textAlign: 'right', fontWeight: 600 }}>
                                {yen(count * (x.unit_price || 0))}
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                  <div style={{ marginTop: 12, display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                    <button className="btn btn-primary"
                      disabled={Object.keys(picked).length === 0 || create.isPending}
                      onClick={async () => {
                        const list = fromReceiving.filter(x => picked[x.task_id] !== undefined)
                        if (!list.length) return
                        const total = list.reduce((s, x) => s + picked[x.task_id] * (x.unit_price || 0), 0)
                        if (!confirm(`${list.length}件を${form.order_date}の依頼にします（合計${yen(total)}）`)) return
                        for (const [i, x] of list.entries()) {
                          await api.post('/welfare/packing-orders', {
                            order_date: form.order_date,
                            priority: i + 1,
                            task_id: x.task_id,
                            set_count: picked[x.task_id],
                          })
                        }
                        setPicked({})
                        refresh()
                        qc.invalidateQueries({ queryKey: ['packing-fromReceiving'] })
                      }}>
                      選んだ{Object.keys(picked).length}件を依頼にする
                    </button>
                    <button className="btn btn-secondary"
                      onClick={() => setPicked(
                        Object.fromEntries(fromReceiving.map(x => [x.task_id, x.suggested_set_count])))}>
                      すべて選ぶ
                    </button>
                    {Object.keys(picked).length > 0 && (
                      <button className="btn btn-secondary" onClick={() => setPicked({})}>
                        選択を外す
                      </button>
                    )}
                  </div>
                </>
              )}
            </div>
          </details>

          {/* 依頼の追加（手入力） */}
          <div style={{
            padding: 14, marginBottom: 16, borderRadius: 8,
            background: '#f8fafc', border: '1px solid #e2e8f0',
          }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 10 }}>
              <div className="form-group" style={{ margin: 0 }}>
                <label>依頼日</label>
                <input type="date" value={form.order_date}
                  onChange={e => setForm(f => ({ ...f, order_date: e.target.value }))} />
              </div>
              <div className="form-group" style={{ margin: 0 }}>
                <label>優先順位</label>
                <input type="number" value={form.priority} placeholder="1"
                  onChange={e => setForm(f => ({ ...f, priority: e.target.value }))} />
              </div>
              <div className="form-group" style={{ margin: 0, position: 'relative' }}>
                <label>作業（名前・SKUで検索）</label>
                <input
                  value={selected ? selected.name : taskQuery}
                  placeholder="ガーゼ / y27 など"
                  onChange={e => { setTaskQuery(e.target.value); setForm(f => ({ ...f, task_id: '' })) }}
                />
                {candidates.length > 0 && !form.task_id && (
                  <div style={{
                    position: 'absolute', zIndex: 20, top: '100%', left: 0, right: 0,
                    background: '#fff', border: '1px solid #cbd5e1', borderRadius: 6,
                    maxHeight: 240, overflowY: 'auto', boxShadow: '0 4px 12px rgba(0,0,0,.08)',
                  }}>
                    {candidates.map(t => (
                      <div key={t.id}
                        onClick={() => { setForm(f => ({ ...f, task_id: t.id })); setTaskQuery('') }}
                        style={{ padding: '8px 10px', cursor: 'pointer', fontSize: 13, borderBottom: '1px solid #f1f5f9' }}
                      >
                        <div style={{ fontWeight: 600 }}>{t.name}</div>
                        <div style={{ fontSize: 11, color: '#94a3b8' }}>
                          {t.sku || '(SKU紐づけなし)'} ・ {yen(t.unit_price)}
                          {t.set_qty ? ` ・ 1セット${t.set_qty}個` : ''}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <div className="form-group" style={{ margin: 0 }}>
                <label>セット数</label>
                <input type="number" value={form.set_count} placeholder="200"
                  onChange={e => setForm(f => ({ ...f, set_count: e.target.value }))} />
              </div>
              <div className="form-group" style={{ margin: 0 }}>
                <label>備考（任意）</label>
                <input value={form.note}
                  onChange={e => setForm(f => ({ ...f, note: e.target.value }))} />
              </div>
            </div>

            {selected && (
              <div style={{ marginTop: 10, fontSize: 12, color: '#475569' }}>
                単価 <b>{yen(selected.unit_price)}</b>
                {selected.set_qty ? <> ／ 1セット {selected.set_qty}個</> : null}
                {form.set_count
                  ? <> → 金額 <b>{yen(selected.unit_price * Number(form.set_count))}</b></>
                  : null}
                {selected.packing_method && (
                  <div style={{ marginTop: 4 }}>作業内容: {selected.packing_method}</div>
                )}
              </div>
            )}

            <div style={{ marginTop: 12 }}>
              <button className="btn btn-primary" onClick={submit} disabled={create.isPending}>
                {create.isPending ? '追加中...' : '依頼に追加'}
              </button>
            </div>
          </div>

          {/* 依頼一覧 */}
          {rows.length === 0 ? (
            <div style={{ padding: 30, textAlign: 'center', color: '#9ca3af' }}>
              {fmtMonth(month)}の依頼はまだありません
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr style={{ background: '#f8fafc', borderBottom: '2px solid #e2e8f0' }}>
                    {['優先', '依頼日', '作業名', '全数量', 'セット数', '単価', '金額', '状態', ''].map(h => (
                      <th key={h} style={{ padding: '8px 10px', whiteSpace: 'nowrap' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map(r => (
                    <tr key={r.id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                      <td style={{ padding: '8px 10px', textAlign: 'center' }}>
                        <input type="number" defaultValue={r.priority ?? ''} style={{ width: 56 }}
                          onBlur={e => {
                            const v = e.target.value === '' ? null : Number(e.target.value)
                            if (v !== r.priority) update.mutate({ id: r.id, body: { priority: v } })
                          }} />
                      </td>
                      <td style={{ padding: '8px 10px', whiteSpace: 'nowrap' }}>{r.order_date}</td>
                      <td style={{ padding: '8px 10px' }}>
                        <div style={{ fontWeight: 600 }}>{r.name_jp}</div>
                        {r.sku && <div style={{ fontSize: 11, color: '#94a3b8' }}>{r.sku}</div>}
                      </td>
                      <td style={{ padding: '8px 10px', textAlign: 'right' }}>{r.set_qty || '-'}</td>
                      <td style={{ padding: '8px 10px', textAlign: 'right' }}>
                        <input type="number" defaultValue={r.set_count} style={{ width: 80 }}
                          onBlur={e => {
                            const v = Number(e.target.value || 0)
                            if (v !== r.set_count) update.mutate({ id: r.id, body: { set_count: v } })
                          }} />
                      </td>
                      <td style={{ padding: '8px 10px', textAlign: 'right' }}>
                        <input type="number" step="0.1" defaultValue={r.unit_price} style={{ width: 70 }}
                          onBlur={e => {
                            const v = Number(e.target.value || 0)
                            if (v !== r.unit_price) update.mutate({ id: r.id, body: { unit_price: v } })
                          }} />
                      </td>
                      <td style={{ padding: '8px 10px', textAlign: 'right', fontWeight: 600 }}>{yen(r.amount)}</td>
                      <td style={{ padding: '8px 10px', textAlign: 'center' }}>
                        <button className="btn btn-secondary" style={{ padding: '2px 10px', fontSize: 12 }}
                          onClick={() => update.mutate({
                            id: r.id, body: { status: r.status === 'done' ? 'open' : 'done' },
                          })}>
                          {r.status === 'done' ? '完了' : '依頼中'}
                        </button>
                      </td>
                      <td style={{ padding: '8px 10px', textAlign: 'center' }}>
                        <button className="btn btn-secondary"
                          style={{ padding: '2px 8px', fontSize: 12, color: '#dc2626' }}
                          onClick={() => { if (confirm('この依頼を削除しますか？')) remove.mutate(r.id) }}>
                          削除
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr style={{ background: '#f8fafc', borderTop: '2px solid #e2e8f0', fontWeight: 700 }}>
                    <td colSpan={4} style={{ padding: 10, textAlign: 'right' }}>合計</td>
                    <td style={{ padding: 10, textAlign: 'right' }}>{(data?.total_sets || 0).toLocaleString()}</td>
                    <td />
                    <td style={{ padding: 10, textAlign: 'right' }}>{yen(data?.total_amount)}</td>
                    <td colSpan={2} />
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
        </>
      ) : (
        /* 作業マスタ */
        <>
          <div style={{ marginBottom: 12 }}>
            <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
              <input
                className="search-input-ja"
                style={{ maxWidth: 320 }}
                value={taskSearch}
                onChange={e => setTaskSearch(e.target.value)}
                placeholder="作業名・SKUで検索"
              />
              <button
                className="btn btn-secondary"
                disabled={seedTasks.isPending}
                onClick={() => {
                  if (confirm(`いま使っている作業 ${initialTasks.length}件を取り込みます。
`
                    + '同じ作業名があれば上書きします。よろしいですか？')) seedTasks.mutate()
                }}
              >
                {seedTasks.isPending ? '取り込み中...' : `作業${initialTasks.length}件を取り込む`}
              </button>
            </div>
            <div style={{ fontSize: 12, color: '#64748b', marginTop: 6 }}>
              単価・梱包材・作業内容はここで直せます。依頼を作るときにこの内容がコピーされます
              （後から直しても、過去の依頼の金額は変わりません）。
            </div>
          </div>

          {/* 商品と紐づかない作業（郵便書簡・封筒など）を手で足す。
              SKUは空でよい */}
          <details style={{ marginBottom: 14 }}>
            <summary style={{ cursor: 'pointer', fontSize: 13, color: '#334155', padding: '6px 0' }}>
              ＋ 作業を手で追加する（郵便書簡・封筒など商品でないもの）
            </summary>
            <div style={{
              padding: 14, marginTop: 8, borderRadius: 8,
              background: '#f8fafc', border: '1px solid #e2e8f0',
            }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10 }}>
                <div className="form-group" style={{ margin: 0 }}>
                  <label>作業名 <span style={{ color: '#dc2626' }}>*</span></label>
                  <input value={newTask.name} placeholder="郵便書簡（ミニレター）"
                    onChange={e => setNewTask(f => ({ ...f, name: e.target.value }))} />
                </div>
                <div className="form-group" style={{ margin: 0 }}>
                  <label>SKU（任意）</label>
                  <input value={newTask.sku} placeholder="空でOK"
                    onChange={e => setNewTask(f => ({ ...f, sku: e.target.value }))} />
                </div>
                <div className="form-group" style={{ margin: 0 }}>
                  <label>1セットの数（任意）</label>
                  <input type="number" value={newTask.set_qty} placeholder="-"
                    onChange={e => setNewTask(f => ({ ...f, set_qty: e.target.value }))} />
                </div>
                <div className="form-group" style={{ margin: 0 }}>
                  <label>単価（円）</label>
                  <input type="number" step="0.1" value={newTask.unit_price} placeholder="3"
                    onChange={e => setNewTask(f => ({ ...f, unit_price: e.target.value }))} />
                </div>
                <div className="form-group" style={{ margin: 0 }}>
                  <label>梱包材（任意）</label>
                  <input value={newTask.packing_material} placeholder="セロテープ、両面テープ"
                    onChange={e => setNewTask(f => ({ ...f, packing_material: e.target.value }))} />
                </div>
              </div>
              <div className="form-group" style={{ marginTop: 10, marginBottom: 0 }}>
                <label>作業内容（任意）</label>
                <textarea rows={2} value={newTask.packing_method}
                  onChange={e => setNewTask(f => ({ ...f, packing_method: e.target.value }))} />
              </div>
              <div style={{ marginTop: 12 }}>
                <button className="btn btn-primary" disabled={createTask.isPending}
                  onClick={() => {
                    if (!newTask.name.trim()) return alert('作業名を入れてください')
                    createTask.mutate({
                      name: newTask.name.trim(),
                      sku: newTask.sku.trim(),
                      set_qty: newTask.set_qty === '' ? null : Number(newTask.set_qty),
                      unit_price: newTask.unit_price === '' ? 0 : Number(newTask.unit_price),
                      packing_material: newTask.packing_material,
                      packing_method: newTask.packing_method,
                      sort_order: 999,
                    })
                  }}>
                  {createTask.isPending ? '追加中...' : 'この作業を追加'}
                </button>
              </div>
            </div>
          </details>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ background: '#f8fafc', borderBottom: '2px solid #e2e8f0' }}>
                  {['作業名', 'SKU', '楽天の商品名', '全数量', '単価', '梱包材', '作業内容', ''].map(h => (
                    <th key={h} style={{ padding: '8px 10px', textAlign: 'left', whiteSpace: 'nowrap' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredTasks.map(t => (
                  <tr key={t.id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                    <td style={{ padding: '8px 10px', fontWeight: 600, minWidth: 180 }}>{t.name}</td>
                    <td style={{ padding: '8px 10px' }}>
                      <input defaultValue={t.sku || ''} style={{ width: 110 }} placeholder="-"
                        onBlur={e => {
                          const v = e.target.value.trim()
                          if (v !== (t.sku || '')) updateTask.mutate({ id: t.id, body: { sku: v } })
                        }} />
                    </td>
                    <td style={{ padding: '8px 10px', fontSize: 12, color: '#64748b', maxWidth: 200 }}>
                      {t.product_name || (t.sku ? '（マスタに無し）' : '—')}
                    </td>
                    <td style={{ padding: '8px 10px' }}>
                      <input type="number" defaultValue={t.set_qty ?? ''} style={{ width: 60 }}
                        onBlur={e => {
                          const v = e.target.value === '' ? null : Number(e.target.value)
                          if (v !== t.set_qty) updateTask.mutate({ id: t.id, body: { set_qty: v } })
                        }} />
                    </td>
                    <td style={{ padding: '8px 10px' }}>
                      <input type="number" step="0.1" defaultValue={t.unit_price ?? 0} style={{ width: 66 }}
                        onBlur={e => {
                          const v = Number(e.target.value || 0)
                          if (v !== t.unit_price) updateTask.mutate({ id: t.id, body: { unit_price: v } })
                        }} />
                    </td>
                    <td style={{ padding: '8px 10px' }}>
                      <input defaultValue={t.packing_material || ''} style={{ width: 150 }}
                        onBlur={e => {
                          const v = e.target.value
                          if (v !== (t.packing_material || '')) updateTask.mutate({ id: t.id, body: { packing_material: v } })
                        }} />
                    </td>
                    <td style={{ padding: '8px 10px', minWidth: 300 }}>
                      <textarea defaultValue={t.packing_method || ''} rows={2}
                        style={{ width: '100%', minWidth: 280 }}
                        onBlur={e => {
                          const v = e.target.value
                          if (v !== (t.packing_method || '')) updateTask.mutate({ id: t.id, body: { packing_method: v } })
                        }} />
                    </td>
                    <td style={{ padding: '8px 10px', textAlign: 'center' }}>
                      <button className="btn btn-secondary"
                        style={{ padding: '2px 8px', fontSize: 12, color: '#dc2626' }}
                        onClick={() => {
                          if (confirm(`「${t.name}」を一覧から外しますか？
過去の依頼はそのまま残ります。`)) {
                            removeTask.mutate(t.id)
                          }
                        }}>
                        削除
                      </button>
                    </td>
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
