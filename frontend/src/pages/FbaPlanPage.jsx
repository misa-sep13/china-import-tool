import { useState, useEffect, useMemo } from 'react'
import api from '../api/client'

const SHIP_LABELS = { air: '航空便', sea: '船便', hold: '保留' }
const SHIP_COLORS = { air: '#ef4444', sea: '#3b82f6', hold: '#9ca3af' }
const FILTER_OPTIONS = [
  { value: 'all', label: '全て' },
  { value: 'air', label: '航空便' },
  { value: 'sea', label: '船便' },
  { value: 'hold', label: '保留' },
  { value: 'need', label: '要納品' },
]

export default function FbaPlanPage() {
  const [status, setStatus] = useState('idle')
  const [jobId, setJobId] = useState(null)
  const [items, setItems] = useState([])
  const [planSettings, setPlanSettings] = useState(null)
  const [meta, setMeta] = useState({})
  const [filter, setFilter] = useState('need')
  const [sortKey, setSortKey] = useState('pipeline_days')
  const [sortAsc, setSortAsc] = useState(true)
  const [planQtys, setPlanQtys] = useState({})
  const [excludes, setExcludes] = useState({})
  const [exporting, setExporting] = useState(false)
  const [elapsed, setElapsed] = useState(0)

  const startFetch = async (force = false) => {
    setStatus('loading')
    setElapsed(0)
    try {
      const { data } = await api.post(`/fba-plan/start?force=${force}`)
      setJobId(data.job_id)
    } catch (e) {
      setStatus('error')
    }
  }

  useEffect(() => {
    if (!jobId) return
    const timer = setInterval(async () => {
      try {
        const { data } = await api.get(`/fba-plan/status/${jobId}`)
        setElapsed(data.elapsed || 0)
        if (data.status === 'done' && data.result) {
          setItems(data.result.items || [])
          setPlanSettings(data.result.settings || null)
          setMeta({
            sale_extra_days: data.result.sale_extra_days,
            target_stock_days: data.result.target_stock_days,
            lt_sea_total: data.result.lt_sea_total,
            lt_air_total: data.result.lt_air_total,
          })
          const initQtys = {}
          for (const it of data.result.items || []) {
            initQtys[it.sku] = it.plan_qty
          }
          setPlanQtys(initQtys)
          setExcludes({})
          setStatus('done')
          clearInterval(timer)
        } else if (data.status === 'error') {
          setStatus('error')
          clearInterval(timer)
        }
      } catch {
        setStatus('error')
        clearInterval(timer)
      }
    }, 1500)
    return () => clearInterval(timer)
  }, [jobId])

  useEffect(() => { startFetch() }, [])

  const handleSort = (key) => {
    if (sortKey === key) setSortAsc(!sortAsc)
    else { setSortKey(key); setSortAsc(true) }
  }

  const filteredItems = useMemo(() => {
    let list = items.filter(it => {
      if (filter === 'all') return true
      if (filter === 'air') return it.ship_method === 'air'
      if (filter === 'sea') return it.ship_method === 'sea'
      if (filter === 'hold') return it.ship_method === 'hold'
      if (filter === 'need') return it.ship_method !== 'hold' && it.recommended_sets > 0
      return true
    }).filter(it => !excludes[it.sku])

    list.sort((a, b) => {
      let va = a[sortKey], vb = b[sortKey]
      if (typeof va === 'string') va = va.toLowerCase()
      if (typeof vb === 'string') vb = vb.toLowerCase()
      if (va < vb) return sortAsc ? -1 : 1
      if (va > vb) return sortAsc ? 1 : -1
      return 0
    })
    return list
  }, [items, filter, excludes, sortKey, sortAsc])

  const summaryByMethod = useMemo(() => {
    const s = { air: 0, sea: 0, hold: 0 }
    for (const it of items) {
      if (!excludes[it.sku]) s[it.ship_method] = (s[it.ship_method] || 0) + 1
    }
    return s
  }, [items, excludes])

  const handleExport = async () => {
    const exportItems = filteredItems
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
    } catch (e) {
      alert('Excel出力に失敗しました')
    }
    setExporting(false)
  }

  const totalPlanPieces = useMemo(() => {
    return filteredItems.reduce((sum, it) => {
      if (it.ship_method === 'hold' || excludes[it.sku]) return sum
      return sum + (planQtys[it.sku] || 0) * it.set_size
    }, 0)
  }, [filteredItems, planQtys, excludes])

  const SortHeader = ({ label, field, style }) => (
    <th style={{ ...thStyle, cursor: 'pointer', userSelect: 'none', ...style }}
      onClick={() => handleSort(field)}>
      {label} {sortKey === field ? (sortAsc ? '▲' : '▼') : ''}
    </th>
  )

  return (
    <div>
      <h1>📦 FBA納品プラン</h1>

      {/* 設定サマリー */}
      {planSettings && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 24, fontSize: 13 }}>
            <div>
              <span style={{ color: '#6b7280' }}>無料保管: </span>
              <strong>{planSettings.free_storage_days}日</strong>
            </div>
            <div>
              <span style={{ color: '#6b7280' }}>発注〜倉庫着: </span>
              <strong>{planSettings.lt_order_to_warehouse}日</strong>
            </div>
            <div>
              <span style={{ color: '#6b7280' }}>配送依頼〜支払: </span>
              <strong>{planSettings.lt_shipping_request}日</strong>
            </div>
            <div>
              <span style={{ color: '#6b7280' }}>船便→FBA: </span>
              <strong>{planSettings.lt_sea_to_fba}日</strong>
              <span style={{ color: '#9ca3af', marginLeft: 4 }}>(合計{meta.lt_sea_total}日)</span>
            </div>
            <div>
              <span style={{ color: '#6b7280' }}>航空便→FBA: </span>
              <strong>{planSettings.lt_air_to_fba}日</strong>
              <span style={{ color: '#9ca3af', marginLeft: 4 }}>(合計{meta.lt_air_total}日)</span>
            </div>
            <div>
              <span style={{ color: '#6b7280' }}>航空便閾値: </span>
              <strong>≤{planSettings.air_threshold_days}日</strong>
            </div>
            <div>
              <span style={{ color: '#6b7280' }}>目標在庫: </span>
              <strong>{meta.target_stock_days}日</strong>
              {meta.sale_extra_days > 0 && (
                <span style={{ color: '#dc2626', marginLeft: 4 }}>+{meta.sale_extra_days}日(セール)</span>
              )}
            </div>
          </div>
        </div>
      )}

      {/* アクションバー */}
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 16, flexWrap: 'wrap' }}>
        <button className="btn btn-primary" onClick={() => startFetch(true)} disabled={status === 'loading'}>
          {status === 'loading' ? `取得中... (${elapsed.toFixed(0)}秒)` : '🔄 SP-APIから更新'}
        </button>
        <button className="btn" onClick={handleExport} disabled={exporting || status !== 'done'}
          style={{ background: '#059669', color: '#fff' }}>
          {exporting ? '出力中...' : '📥 納品プランExcel出力'}
        </button>
        <span style={{ fontSize: 13, color: '#6b7280' }}>
          合計出荷数: <strong style={{ color: '#1e40af' }}>{totalPlanPieces}個</strong>
        </span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
          {FILTER_OPTIONS.map(opt => (
            <button key={opt.value}
              onClick={() => setFilter(opt.value)}
              style={{
                padding: '4px 12px', fontSize: 12, borderRadius: 4, border: '1px solid #d1d5db',
                background: filter === opt.value ? '#1e40af' : '#fff',
                color: filter === opt.value ? '#fff' : '#374151',
                cursor: 'pointer',
              }}>
              {opt.label}
              {opt.value !== 'all' && opt.value !== 'need' && ` (${summaryByMethod[opt.value] || 0})`}
            </button>
          ))}
        </div>
      </div>

      {status === 'loading' && (
        <div className="card" style={{ textAlign: 'center', padding: 40, color: '#6b7280' }}>
          SP-APIからデータ取得中... ({elapsed.toFixed(0)}秒)
        </div>
      )}

      {status === 'error' && (
        <div className="card" style={{ textAlign: 'center', padding: 40, color: '#ef4444' }}>
          データ取得に失敗しました。もう一度お試しください。
        </div>
      )}

      {status === 'done' && (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ background: '#f8fafc', borderBottom: '2px solid #e2e8f0' }}>
                <SortHeader label="SKU" field="sku" />
                <th style={thStyle}>商品名</th>
                <SortHeader label="日販" field="daily" style={{ textAlign: 'right' }} />
                <SortHeader label="FBA" field="fba_available" style={{ textAlign: 'right' }} />
                <th style={{ ...thStyle, textAlign: 'right' }}>輸送中</th>
                <th style={{ ...thStyle, textAlign: 'right' }}>パイプライン</th>
                <SortHeader label="FBA残日数" field="fba_days" style={{ textAlign: 'right' }} />
                <SortHeader label="全体残日数" field="pipeline_days" style={{ textAlign: 'right' }} />
                <th style={{ ...thStyle, textAlign: 'center' }}>判定</th>
                <th style={{ ...thStyle, textAlign: 'right' }}>推奨(セット)</th>
                <th style={{ ...thStyle, textAlign: 'right' }}>納品数(セット)</th>
                <th style={{ ...thStyle, textAlign: 'center' }}>除外</th>
              </tr>
            </thead>
            <tbody>
              {filteredItems.map(it => {
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
                    <td style={{ ...tdStyle, textAlign: 'right', color: '#6b7280' }}>
                      {it.fba_inbound + it.ordered}
                    </td>
                    <td style={{ ...tdStyle, textAlign: 'right', fontWeight: 600 }}>{it.pipeline_stock}</td>
                    <td style={{ ...tdStyle, textAlign: 'right', color: daysColor, fontWeight: 600 }}>
                      {it.fba_days > 9000 ? '∞' : `${it.fba_days}日`}
                    </td>
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
              {filteredItems.length === 0 && (
                <tr>
                  <td colSpan={12} style={{ ...tdStyle, textAlign: 'center', color: '#9ca3af', padding: 32 }}>
                    該当する商品がありません
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* ロジック説明 */}
      <div className="card" style={{ marginTop: 32, background: '#fafafa', border: '1px solid #ebebeb' }}>
        <h2 style={{ color: '#9ca3af', marginBottom: 16 }}>納品プラン判定ロジック</h2>
        <table style={{ fontSize: 13, borderCollapse: 'collapse', width: '100%' }}>
          <tbody>
            <tr style={{ borderBottom: '1px solid #f3f4f6' }}>
              <td style={{ padding: '8px 12px', fontWeight: 600, color: '#9ca3af', width: 160 }}>目標在庫日数</td>
              <td style={{ padding: '8px 12px', color: '#6b7280' }}>
                無料保管期間({planSettings?.free_storage_days || 90}日) − 発注〜倉庫着({planSettings?.lt_order_to_warehouse || 7}日) = {meta.target_stock_days || 83}日
              </td>
            </tr>
            <tr style={{ borderBottom: '1px solid #f3f4f6' }}>
              <td style={{ padding: '8px 12px', fontWeight: 600, color: '#ef4444' }}>航空便</td>
              <td style={{ padding: '8px 12px', color: '#6b7280' }}>
                パイプライン残日数 ≤ {planSettings?.air_threshold_days || 18}日 → 在庫切れが迫っている
              </td>
            </tr>
            <tr style={{ borderBottom: '1px solid #f3f4f6' }}>
              <td style={{ padding: '8px 12px', fontWeight: 600, color: '#3b82f6' }}>船便</td>
              <td style={{ padding: '8px 12px', color: '#6b7280' }}>
                パイプライン残日数 &gt; {planSettings?.air_threshold_days || 18}日 → 余裕あり
              </td>
            </tr>
            <tr style={{ borderBottom: '1px solid #f3f4f6' }}>
              <td style={{ padding: '8px 12px', fontWeight: 600, color: '#9ca3af' }}>保留</td>
              <td style={{ padding: '8px 12px', color: '#6b7280' }}>
                日販 &lt; {planSettings?.hold_daily_threshold || 0.1} → 売れてない商品は送らない（TAO太郎で保管→返品/廃棄も選択可）
              </td>
            </tr>
            <tr>
              <td style={{ padding: '8px 12px', fontWeight: 600, color: '#9ca3af' }}>推奨納品数</td>
              <td style={{ padding: '8px 12px', color: '#6b7280' }}>
                日販 × 成長補正 × 目標日数 − パイプライン在庫（マイナスなら0）
              </td>
            </tr>
          </tbody>
        </table>
      </div>
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
