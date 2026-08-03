import { useState, useEffect, useMemo, useRef } from 'react'
import api from '../api/client'

const STATUS_LABELS = { ordered: '発注済', arrived: '到着済', shipped: '配送依頼済' }
const STATUS_COLORS = { ordered: '#f59e0b', arrived: '#22c55e', shipped: '#6b7280' }
const SHIP_LABELS = { air: '航空便', sea: '船便', hold: '保留' }
const SHIP_COLORS = { air: '#ef4444', sea: '#3b82f6', hold: '#9ca3af' }

export default function FbaPlanPage() {
  const [orders, setOrders] = useState([])
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState('all')
  const [importing, setImporting] = useState(false)
  const [importResult, setImportResult] = useState(null)
  const fileRef = useRef(null)

  // FBA plan state
  const [planStatus, setPlanStatus] = useState('idle')
  const [planItems, setPlanItems] = useState([])
  const [planSettings, setPlanSettings] = useState(null)
  const [meta, setMeta] = useState({})
  const [planQtys, setPlanQtys] = useState({})
  const [excludes, setExcludes] = useState({})
  const [exporting, setExporting] = useState(false)
  const [creatingPlan, setCreatingPlan] = useState(false)
  const [createResult, setCreateResult] = useState(null)
  const [elapsed, setElapsed] = useState(0)
  const [sortKey, setSortKey] = useState('pipeline_days')
  const [sortAsc, setSortAsc] = useState(true)

  const fetchOrders = async () => {
    setLoading(true)
    try {
      const { data } = await api.get('/fba-plan/orders')
      setOrders(data)
    } catch (e) {
      console.error(e)
    }
    setLoading(false)
  }

  useEffect(() => { fetchOrders() }, [])

  const handleImport = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setImporting(true)
    setImportResult(null)
    try {
      const form = new FormData()
      form.append('file', file)
      const { data } = await api.post('/fba-plan/import-taotaro', form)
      setImportResult(data)
      fetchOrders()
    } catch (err) {
      setImportResult({ error: 'Excel取込に失敗しました' })
    }
    setImporting(false)
    if (fileRef.current) fileRef.current.value = ''
  }

  const handleStatusChange = async (id, newStatus) => {
    try {
      await api.post(`/fba-plan/orders/${id}/status`, { status: newStatus })
      fetchOrders()
    } catch (e) {
      console.error(e)
    }
  }

  const filteredOrders = useMemo(() => {
    if (tab === 'all') return orders
    return orders.filter(o => o.status === tab)
  }, [orders, tab])

  const statusCounts = useMemo(() => {
    const c = { ordered: 0, arrived: 0, shipped: 0 }
    for (const o of orders) c[o.status] = (c[o.status] || 0) + 1
    return c
  }, [orders])

  // ---- FBA Plan (到着済み商品の納品プラン) ----
  const arrivedOrders = useMemo(() => orders.filter(o => o.status === 'arrived'), [orders])

  const startPlanFetch = async (force = false) => {
    setPlanStatus('loading')
    setElapsed(0)
    try {
      const { data } = await api.post(`/fba-plan/start?force=${force}`)
      const jobId = data.job_id
      const timer = setInterval(async () => {
        try {
          const { data: st } = await api.get(`/fba-plan/status/${jobId}`)
          setElapsed(st.elapsed || 0)
          if (st.status === 'done' && st.result) {
            clearInterval(timer)
            const arrivedSkus = new Set(arrivedOrders.map(o => o.sku))
            const filtered = (st.result.items || []).filter(it => arrivedSkus.has(it.sku))
            setPlanItems(filtered)
            setPlanSettings(st.result.settings || null)
            setMeta({
              sale_extra_days: st.result.sale_extra_days,
              target_stock_days: st.result.target_stock_days,
              lt_sea_total: st.result.lt_sea_total,
              lt_air_total: st.result.lt_air_total,
            })
            const initQtys = {}
            for (const it of filtered) initQtys[it.sku] = it.plan_qty
            setPlanQtys(initQtys)
            setExcludes({})
            setPlanStatus('done')
          } else if (st.status === 'error') {
            clearInterval(timer)
            setPlanStatus('error')
          }
        } catch {
          clearInterval(timer)
          setPlanStatus('error')
        }
      }, 1500)
    } catch {
      setPlanStatus('error')
    }
  }

  const handleSort = (key) => {
    if (sortKey === key) setSortAsc(!sortAsc)
    else { setSortKey(key); setSortAsc(true) }
  }

  const sortedPlanItems = useMemo(() => {
    const list = planItems.filter(it => !excludes[it.sku])
    list.sort((a, b) => {
      let va = a[sortKey], vb = b[sortKey]
      if (typeof va === 'string') va = va.toLowerCase()
      if (typeof vb === 'string') vb = vb.toLowerCase()
      if (va < vb) return sortAsc ? -1 : 1
      if (va > vb) return sortAsc ? 1 : -1
      return 0
    })
    return list
  }, [planItems, excludes, sortKey, sortAsc])

  const totalPlanPieces = useMemo(() => {
    return sortedPlanItems.reduce((sum, it) => {
      if (it.ship_method === 'hold' || excludes[it.sku]) return sum
      return sum + (planQtys[it.sku] || 0) * it.set_size
    }, 0)
  }, [sortedPlanItems, planQtys, excludes])

  // Amazonへの納品プラン作成。作れるのはSKUと数量まで（箱詰めはタオタロウが決める）
  const handleCreateInboundPlan = async () => {
    const targets = sortedPlanItems
      .filter(it => (planQtys[it.sku] || 0) > 0 && it.ship_method !== 'hold')
      .map(it => ({
        sku: it.sku,
        fnsku: it.fnsku,
        plan_qty: planQtys[it.sku] || 0,
        set_size: it.set_size,
      }))
    if (!targets.length) {
      alert('納品数が1以上の商品がありません')
      return
    }
    const pieces = targets.reduce((s, t) => s + t.plan_qty * t.set_size, 0)
    const detail = targets.map(t => `  ${t.sku}: ${t.plan_qty * t.set_size}個`).join('\n')
    if (!confirm(
      `Amazonに納品プランを作成します。\n\n${detail}\n\n` +
      `計 ${targets.length}SKU / ${pieces}個\n\n` +
      `作成後はセラーセントラルで商品ラベルをダウンロードしてください。`
    )) return

    setCreatingPlan(true)
    setCreateResult(null)
    try {
      const { data } = await api.post('/fba-plan/create-inbound-plan', { items: targets })
      setCreateResult(data)
    } catch (e) {
      setCreateResult({ error: e.response?.data?.detail || '納品プランの作成に失敗しました' })
    }
    setCreatingPlan(false)
  }

  const handleExport = async () => {
    const exportItems = sortedPlanItems
      .filter(it => (planQtys[it.sku] || 0) > 0 && it.ship_method !== 'hold')
      .map(it => ({
        sku: it.sku,
        fnsku: it.fnsku,
        plan_qty: planQtys[it.sku] || 0,
        set_size: it.set_size,
      }))
    if (!exportItems.length) {
      alert('納品数が1以上の商品がありません')
      return
    }
    setExporting(true)
    try {
      const res = await api.post('/fba-plan/export-excel', { items: exportItems }, { responseType: 'blob' })
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = `fba_plan_${new Date().toISOString().slice(0, 10).replace(/-/g, '')}.xlsx`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      alert('Excel出力に失敗しました')
    }
    setExporting(false)
  }

  const SortHeader = ({ label, field, style }) => (
    <th style={{ ...thStyle, cursor: 'pointer', userSelect: 'none', ...style }}
      onClick={() => handleSort(field)}>
      {label} {sortKey === field ? (sortAsc ? '▲' : '▼') : ''}
    </th>
  )

  return (
    <div>
      <h1>🚢 FBA納品プラン</h1>

      {/* 手順メモ。普段は畳んでおき、必要なときだけ開く */}
      <details style={{ marginBottom: 16 }}>
        <summary style={{
          cursor: 'pointer', padding: '8px 14px', background: '#f1f5f9',
          border: '1px solid #e2e8f0', borderRadius: 6,
          fontSize: 13, fontWeight: 600, color: '#334155', userSelect: 'none',
          display: 'inline-block',
        }}>
          📋 タオタロウFBA直送の流れ
        </summary>
        <div style={{
          marginTop: 8, padding: '14px 18px', background: '#fff',
          border: '1px solid #e2e8f0', borderRadius: 6,
        }}>
          <ol style={{ margin: 0, paddingLeft: 20, fontSize: 13, lineHeight: 2, color: '#334155' }}>
            <li>配送依頼をかける</li>
            <li>FBA指示書をダウンロード</li>
            <li>指示書と商品ラベルを一緒にDingtalkに送る</li>
            <li>インボイス作成完了のお知らせが来る</li>
            <li>支払い</li>
            <li>配送ラベルをDingtalkに送る</li>
          </ol>
        </div>
      </details>

      {/* タオタロウExcel取込 */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <label
            style={{
              padding: '8px 16px', background: '#ea580c', color: '#fff', borderRadius: 6,
              cursor: 'pointer', fontWeight: 600, fontSize: 13,
            }}
          >
            📥 タオタロウExcel取込
            <input ref={fileRef} type="file" accept=".xls,.xlsx" onChange={handleImport}
              style={{ display: 'none' }} />
          </label>
          {importing && <span style={{ color: '#6b7280' }}>取込中...</span>}
          {importResult && !importResult.error && (
            <span style={{ fontSize: 13 }}>
              <strong style={{ color: '#16a34a' }}>{importResult.matched}件</strong> 照合成功
              {importResult.unmatched?.length > 0 && (
                <span style={{ color: '#9ca3af', marginLeft: 8 }}>
                  ({importResult.unmatched.length}件 未照合)
                </span>
              )}
            </span>
          )}
          {importResult?.error && (
            <span style={{ color: '#ef4444', fontSize: 13 }}>{importResult.error}</span>
          )}
          <span style={{ fontSize: 12, color: '#9ca3af' }}>
            タオタロウ「入庫済み」→ EXCELダウンロード → ここにアップロード
          </span>
        </div>
        {importResult?.unmatched?.length > 0 && (
          <details style={{ marginTop: 8, fontSize: 12 }}>
            <summary style={{ cursor: 'pointer', color: '#f59e0b' }}>
              未照合 {importResult.unmatched.length}件を表示
            </summary>
            <div style={{ overflowX: 'auto', marginTop: 4 }}>
              <table style={{ fontSize: 12, borderCollapse: 'collapse', width: '100%' }}>
                <thead>
                  <tr style={{ background: '#fef3c7' }}>
                    <th style={thStyle}>タオタロウID</th>
                    <th style={thStyle}>商品名</th>
                    <th style={thStyle}>色/サイズ</th>
                    <th style={thStyle}>数量</th>
                  </tr>
                </thead>
                <tbody>
                  {importResult.unmatched.map((u, i) => (
                    <tr key={i} style={{ borderBottom: '1px solid #f1f5f9' }}>
                      <td style={tdStyle}>{u.taotaro_order_id}</td>
                      <td style={{ ...tdStyle, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {u.name_cn}
                      </td>
                      <td style={tdStyle}>{[u.color, u.size].filter(Boolean).join(' / ')}</td>
                      <td style={{ ...tdStyle, textAlign: 'right' }}>{u.qty}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        )}
      </div>

      {/* ステータスフィルタ */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 16, flexWrap: 'wrap' }}>
        <button
          onClick={() => setTab('all')}
          style={{
            padding: '6px 16px', fontSize: 13, borderRadius: 4, border: '1px solid #d1d5db',
            background: tab === 'all' ? '#1e40af' : '#fff',
            color: tab === 'all' ? '#fff' : '#374151',
            cursor: 'pointer', fontWeight: 600,
          }}
        >
          全て ({orders.length})
        </button>
        {['ordered', 'arrived'].map(s => (
          <button key={s}
            onClick={() => setTab(s)}
            style={{
              padding: '6px 16px', fontSize: 13, borderRadius: 4, border: '1px solid #d1d5db',
              background: tab === s ? STATUS_COLORS[s] : '#fff',
              color: tab === s ? '#fff' : '#374151',
              cursor: 'pointer', fontWeight: 600,
            }}
          >
            {STATUS_LABELS[s]} ({statusCounts[s] || 0})
          </button>
        ))}
      </div>

      {/* 発注済みリスト */}
      {loading ? (
        <div className="card" style={{ textAlign: 'center', padding: 40, color: '#6b7280' }}>読込中...</div>
      ) : orders.length === 0 ? (
        <div className="card" style={{ textAlign: 'center', padding: 40, color: '#9ca3af' }}>
          <div style={{ fontSize: 40 }}>📋</div>
          <p>発注済みの商品がありません。<br />発注管理で商品を発注してください。</p>
        </div>
      ) : (
        <div style={{ overflowX: 'auto', marginBottom: 24 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ background: '#f8fafc', borderBottom: '2px solid #e2e8f0' }}>
                <th style={thStyle}>ステータス</th>
                <th style={thStyle}>発注日</th>
                <th style={thStyle}>SKU</th>
                <th style={thStyle}>商品名</th>
                <th style={thStyle}>色/サイズ</th>
                <th style={{ ...thStyle, textAlign: 'right' }}>数量</th>
                <th style={{ ...thStyle, textAlign: 'right' }}>単価(元)</th>
                <th style={thStyle}>仕入URL</th>
                <th style={thStyle}>操作</th>
              </tr>
            </thead>
            <tbody>
              {filteredOrders.map(o => (
                <tr key={o.id} style={{
                  borderBottom: '1px solid #f1f5f9',
                  background: o.status === 'arrived' ? '#f0fdf4' : 'transparent',
                }}>
                  <td style={tdStyle}>
                    <span style={{
                      display: 'inline-block', padding: '2px 8px', borderRadius: 4, fontSize: 11,
                      fontWeight: 700, color: '#fff',
                      background: STATUS_COLORS[o.status] || '#9ca3af',
                    }}>
                      {STATUS_LABELS[o.status] || o.status}
                    </span>
                  </td>
                  <td style={{ ...tdStyle, fontSize: 12, whiteSpace: 'nowrap', color: '#666' }}>
                    {o.ordered_at ? new Date(o.ordered_at).toLocaleDateString('ja-JP', { month: '2-digit', day: '2-digit' }) : '-'}
                  </td>
                  <td style={{ ...tdStyle, fontFamily: 'monospace', fontSize: 12 }}>{o.sku}</td>
                  <td style={{ ...tdStyle, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {o.name}
                  </td>
                  <td style={{ ...tdStyle, fontSize: 12, color: '#666' }}>
                    {[o.color, o.size].filter(Boolean).join(' / ')}
                  </td>
                  <td style={{ ...tdStyle, textAlign: 'right', fontWeight: 600 }}>{o.qty}</td>
                  <td style={{ ...tdStyle, textAlign: 'right' }}>{o.price}</td>
                  <td style={tdStyle}>
                    {o.buy_url && (
                      <a href={o.buy_url} target="_blank" rel="noreferrer" style={{ color: '#e94560', fontSize: 12 }}>リンク</a>
                    )}
                  </td>
                  <td style={{ ...tdStyle, whiteSpace: 'nowrap' }}>
                    {o.status === 'ordered' && (
                      <button className="btn btn-sm"
                        style={{ background: '#dcfce7', color: '#166534', fontSize: 11 }}
                        onClick={() => handleStatusChange(o.id, 'arrived')}
                      >到着済みにする</button>
                    )}
                    {o.status === 'arrived' && (
                      <button className="btn btn-sm"
                        style={{ background: '#e0e7ff', color: '#3730a3', fontSize: 11 }}
                        onClick={() => handleStatusChange(o.id, 'shipped')}
                      >配送依頼済み</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* 到着済み商品のFBA納品プラン */}
      {arrivedOrders.length > 0 && (
        <div style={{ borderTop: '2px solid #e2e8f0', paddingTop: 24 }}>
          <h2 style={{ marginBottom: 12 }}>📦 到着済み商品のFBA納品プラン</h2>

          <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 16, flexWrap: 'wrap' }}>
            <button className="btn btn-primary" onClick={() => startPlanFetch(true)} disabled={planStatus === 'loading'}>
              {planStatus === 'loading' ? `取得中... (${elapsed.toFixed(0)}秒)` : '🔄 SP-APIから在庫取得'}
            </button>
            {planStatus === 'done' && (
              <>
                <button className="btn" onClick={handleCreateInboundPlan} disabled={creatingPlan}
                  style={{ background: '#ea580c', color: '#fff', fontWeight: 700 }}
                  title="この内容でAmazonに納品プランを作成します">
                  {creatingPlan ? '作成中...' : '🚀 Amazonに納品プランを作成'}
                </button>
                <button className="btn" onClick={handleExport} disabled={exporting}
                  style={{ background: '#059669', color: '#fff' }}>
                  {exporting ? '出力中...' : '📥 納品プランExcel出力'}
                </button>
                <span style={{ fontSize: 13, color: '#6b7280' }}>
                  合計出荷数: <strong style={{ color: '#1e40af' }}>{totalPlanPieces}個</strong>
                </span>
              </>
            )}
          </div>

          {/* 納品プラン作成の結果。作成後にやることを続けて示す */}
          {createResult && (
            <div className="card" style={{
              marginBottom: 16,
              borderLeft: `4px solid ${createResult.error ? '#ef4444' : '#16a34a'}`,
            }}>
              {createResult.error ? (
                <div style={{ color: '#dc2626', fontSize: 13 }}>{createResult.error}</div>
              ) : (
                <>
                  <div style={{ fontWeight: 700, color: '#166534', marginBottom: 8 }}>
                    納品プランを作成しました（{createResult.sku_count}SKU / {createResult.total_pieces}個）
                  </div>
                  <div style={{ fontSize: 12, color: '#475569', marginBottom: 10 }}>
                    プランID: <span style={{ fontFamily: 'monospace' }}>{createResult.inbound_plan_id}</span>
                  </div>
                  <div style={{ fontSize: 13, color: '#334155', marginBottom: 10 }}>
                    次にやること:
                    <ol style={{ margin: '6px 0 0', paddingLeft: 20, lineHeight: 1.9 }}>
                      <li>セラーセントラルでこのプランを開き、<b>商品ラベルをダウンロード</b></li>
                      <li>タオタロウのFBA指示書と一緒に<b>Dingtalkへ送る</b></li>
                      <li>（梱包・配送業者はタオタロウが決めるのでこちらでは指定しません）</li>
                    </ol>
                  </div>
                  <a href={createResult.seller_central_url} target="_blank" rel="noreferrer"
                    style={{
                      display: 'inline-block', padding: '8px 16px', background: '#1e40af',
                      color: '#fff', borderRadius: 6, fontSize: 13, fontWeight: 600,
                      textDecoration: 'none',
                    }}>
                    セラーセントラルで開く →
                  </a>
                </>
              )}
            </div>
          )}

          {planStatus === 'loading' && (
            <div className="card" style={{ textAlign: 'center', padding: 40, color: '#6b7280' }}>
              SP-APIからデータ取得中... ({elapsed.toFixed(0)}秒)
            </div>
          )}

          {planStatus === 'error' && (
            <div className="card" style={{ textAlign: 'center', padding: 40, color: '#ef4444' }}>
              データ取得に失敗しました。もう一度お試しください。
            </div>
          )}

          {planStatus === 'done' && (
            <>
              {planSettings && (
                <div className="card" style={{ marginBottom: 16 }}>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 24, fontSize: 13 }}>
                    <div>
                      <span style={{ color: '#6b7280' }}>目標在庫: </span>
                      <strong>{meta.target_stock_days}日</strong>
                    </div>
                    <div>
                      <span style={{ color: '#6b7280' }}>船便合計: </span>
                      <strong>{meta.lt_sea_total}日</strong>
                    </div>
                    <div>
                      <span style={{ color: '#6b7280' }}>航空便合計: </span>
                      <strong>{meta.lt_air_total}日</strong>
                    </div>
                    <div>
                      <span style={{ color: '#6b7280' }}>航空便閾値: </span>
                      <strong>≤{planSettings.air_threshold_days}日</strong>
                    </div>
                  </div>
                </div>
              )}

              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                  <thead>
                    <tr style={{ background: '#f8fafc', borderBottom: '2px solid #e2e8f0' }}>
                      <SortHeader label="SKU" field="sku" />
                      <th style={thStyle}>商品名</th>
                      <SortHeader label="日販" field="daily" style={{ textAlign: 'right' }} />
                      <SortHeader label="FBA" field="fba_available" style={{ textAlign: 'right' }} />
                      <th style={{ ...thStyle, textAlign: 'right' }}>パイプライン</th>
                      <SortHeader label="全体残日数" field="pipeline_days" style={{ textAlign: 'right' }} />
                      <th style={{ ...thStyle, textAlign: 'center' }}>判定</th>
                      <th style={{ ...thStyle, textAlign: 'right' }}>推奨(セット)</th>
                      <th style={{ ...thStyle, textAlign: 'right' }}>納品数(セット)</th>
                      <th style={{ ...thStyle, textAlign: 'center' }}>除外</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortedPlanItems.map(it => {
                      const daysColor = it.pipeline_days <= (planSettings?.air_threshold_days || 18)
                        ? '#ef4444'
                        : it.pipeline_days <= 30 ? '#f59e0b' : '#374151'
                      return (
                        <tr key={it.sku} style={{ borderBottom: '1px solid #f1f5f9' }}>
                          <td style={tdStyle}>
                            <span style={{ fontFamily: 'monospace', fontSize: 12 }}>{it.sku}</span>
                          </td>
                          <td style={{ ...tdStyle, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {it.name}
                          </td>
                          <td style={{ ...tdStyle, textAlign: 'right', fontFamily: 'monospace' }}>
                            {it.daily.toFixed(2)}
                          </td>
                          <td style={{ ...tdStyle, textAlign: 'right' }}>{it.fba_available}</td>
                          <td style={{ ...tdStyle, textAlign: 'right', fontWeight: 600 }}>{it.pipeline_stock}</td>
                          <td style={{ ...tdStyle, textAlign: 'right', color: daysColor, fontWeight: 600 }}>
                            {it.pipeline_days > 9000 ? '∞' : `${it.pipeline_days}日`}
                          </td>
                          <td style={{ ...tdStyle, textAlign: 'center' }}>
                            <span style={{
                              display: 'inline-block', padding: '2px 8px', borderRadius: 4, fontSize: 11,
                              fontWeight: 700, color: '#fff',
                              background: SHIP_COLORS[it.ship_method] || '#9ca3af',
                            }}>
                              {SHIP_LABELS[it.ship_method] || it.ship_method}
                            </span>
                          </td>
                          <td style={{ ...tdStyle, textAlign: 'right', color: '#6b7280' }}>
                            {it.recommended_sets}
                          </td>
                          <td style={{ ...tdStyle, textAlign: 'right' }}>
                            <input type="number" min={0}
                              value={planQtys[it.sku] ?? it.plan_qty}
                              onChange={e => setPlanQtys(p => ({ ...p, [it.sku]: Math.max(0, parseInt(e.target.value) || 0) }))}
                              style={{ width: 60, textAlign: 'right', padding: '2px 4px', border: '1px solid #d1d5db', borderRadius: 4 }}
                            />
                          </td>
                          <td style={{ ...tdStyle, textAlign: 'center' }}>
                            <input type="checkbox"
                              checked={!!excludes[it.sku]}
                              onChange={e => setExcludes(p => ({ ...p, [it.sku]: e.target.checked }))}
                            />
                          </td>
                        </tr>
                      )
                    })}
                    {sortedPlanItems.length === 0 && (
                      <tr>
                        <td colSpan={10} style={{ ...tdStyle, textAlign: 'center', color: '#9ca3af', padding: 32 }}>
                          到着済み商品のSP-APIデータがありません
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}

const thStyle = {
  padding: '8px 10px',
  textAlign: 'left',
  fontSize: 12,
  fontWeight: 600,
  color: '#6b7280',
  whiteSpace: 'nowrap',
}
const tdStyle = {
  padding: '6px 10px',
  color: '#374151',
}
