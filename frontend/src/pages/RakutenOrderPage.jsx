import React, { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'
import axios from 'axios'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000/api'

/* ===================== 配送依頼タブ ===================== */
function ShipmentTab() {
  const qc = useQueryClient()
  const [allProducts, setAllProducts] = useState([])
  const [uploading, setUploading] = useState(false)
  const [parsed, setParsed] = useState(null)
  const [matched, setMatched] = useState([])
  const [unmatched, setUnmatched] = useState([])
  const [saving, setSaving] = useState(false)
  const [note, setNote] = useState('')
  const [done, setDone] = useState(false)
  const [receiveResult, setReceiveResult] = useState(null)

  useEffect(() => {
    axios.get(`${API}/rakuten/products/`).then(r => setAllProducts(r.data)).catch(() => {})
  }, [])

  async function handleFile(e) {
    const file = e.target.files[0]
    if (!file) return
    setUploading(true)
    setParsed(null); setMatched([]); setUnmatched([]); setDone(false); setReceiveResult(null)
    const fd = new FormData()
    fd.append('file', file)
    try {
      const res = await axios.post(`${API}/shipment-orders/parse-excel`, fd)
      setParsed(res.data)
      const matchRes = await axios.post(`${API}/shipment-orders/match`, res.data.items)
      setMatched(matchRes.data.matched)
      setUnmatched(matchRes.data.unmatched)
    } catch (e) {
      alert('読み込みエラー: ' + (e.response?.data?.detail || e.message))
    } finally {
      setUploading(false)
    }
  }

  function handleUnmatchedSelect(index, productId) {
    setUnmatched(prev => prev.map((item, i) => {
      if (i !== index) return item
      const product = allProducts.find(p => p.id === parseInt(productId))
      return { ...item, product_id: product?.id || null, sku: product?.sku || '', name_jp: product?.name || '' }
    }))
  }

  // ---- 未照合行からの新規マスタ登録 ----
  const [regRow, setRegRow] = useState(null)
  const [regForm, setRegForm] = useState({ sku: '', name: '', set_size: 1, selling_price: '' })
  const [registering, setRegistering] = useState(false)

  function openRegister(i) {
    setRegRow(i)
    setRegForm({ sku: '', name: '', set_size: 1, selling_price: '' })
  }

  async function handleRegister() {
    const item = unmatched[regRow]
    if (!regForm.sku.trim()) { alert('SKUを入力してください'); return }
    setRegistering(true)
    try {
      const payload = {
        sku: regForm.sku.trim(),
        name: regForm.name.trim() || item.name_cn,
        buy_url: item.buy_url || '',
        supplier_spec: [item.color, item.size].filter(Boolean).join('、'),
        price: item.unit_price_cny || null,
        set_size: parseInt(regForm.set_size) || 1,
        selling_price: regForm.selling_price ? parseFloat(regForm.selling_price) : null,
        supplier: 'タオタロウ',
      }
      const res = await axios.post(`${API}/rakuten/products`, payload)
      const prod = res.data
      setAllProducts(prev => [...prev, prod])
      setUnmatched(prev => prev.map((it, idx) =>
        idx === regRow ? { ...it, product_id: prod.id, sku: prod.sku, name_jp: prod.name } : it))
      setRegRow(null)
      qc.invalidateQueries(['rakuten-products'])
    } catch (e) {
      alert('登録エラー: ' + (e.response?.data?.detail || e.message))
    } finally {
      setRegistering(false)
    }
  }

  async function handleSaveAndReceive() {
    if (!parsed) return
    setSaving(true)
    try {
      const saveRes = await axios.post(`${API}/shipment-orders/save`, {
        shipped_date: parsed.shipped_date,
        tracking_no: parsed.tracking_no,
        order_no: parsed.order_no,
        box_count: parsed.box_count,
        total_weight_kg: parsed.total_weight_kg,
        note,
        matched,
        unmatched,
      })
      const receiveRes = await axios.post(`${API}/shipment-orders/${saveRes.data.shipment_order_id}/receive`)
      setReceiveResult(receiveRes.data)
      setDone(true)
      qc.invalidateQueries(['rakuten-all-products-order'])
      qc.invalidateQueries(['rakuten-order-history'])
      qc.invalidateQueries(['rakuten-stock'])
      qc.invalidateQueries(['rakuten-products'])
    } catch (e) {
      alert('入荷反映エラー: ' + (e.response?.data?.detail || e.message))
    } finally {
      setSaving(false)
    }
  }

  function resetImport() {
    setParsed(null)
    setMatched([])
    setUnmatched([])
    setNote('')
    setDone(false)
    setReceiveResult(null)
  }

  return (
    <div>
      {done
          ? <div className="card">
              <p style={{ color: '#166534', fontWeight: 700 }}>入荷処理が完了しました。</p>
              {receiveResult && (
                <div style={{ fontSize: 13, color: '#475569', marginBottom: 12 }}>
                  在庫加算: {receiveResult.updated}件 / 未照合スキップ: {receiveResult.skipped}件 / 発注済消化: {receiveResult.order_consumed}件
                </div>
              )}
              <button className="btn btn-secondary" onClick={resetImport}>続けて取り込む</button>
            </div>
          : <>
              <div className="card" style={{ marginBottom: 16 }}>
                <h3 style={{ marginBottom: 12 }}>配送依頼ファイル（send-order-list.xls）</h3>
                <input type="file" accept=".xlsx,.xls" onChange={handleFile} disabled={uploading} />
                {uploading && <span style={{ marginLeft: 12, color: '#888' }}>読み込み・照合中...</span>}
              </div>

              {parsed && (
                <>
                  <div className="card" style={{ marginBottom: 16 }}>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 8, fontSize: 13 }}>
                      <div><b>追跡番号:</b> {parsed.tracking_no}</div>
                      <div><b>出荷日:</b> {parsed.shipped_date}</div>
                      <div><b>箱数:</b> {parsed.box_count}</div>
                      <div><b>重量:</b> {parsed.total_weight_kg}kg</div>
                    </div>
                    <div className="form-group" style={{ marginTop: 12 }}>
                      <label>メモ</label>
                      <input value={note} onChange={e => setNote(e.target.value)} />
                    </div>
                  </div>

                  {matched.length > 0 && (
                    <div className="card" style={{ marginBottom: 16 }}>
                      <h3 style={{ color: '#166534', marginBottom: 12 }}>照合済み {matched.length}件</h3>
                      <table>
                        <thead><tr><th>SKU</th><th>商品名</th><th>色</th><th>サイズ</th><th style={{ textAlign: 'right' }}>数量(仕入)</th><th style={{ textAlign: 'right' }}>在庫加算</th></tr></thead>
                        <tbody>
                          {matched.map((item, i) => {
                            const prod = allProducts.find(p => p.id === item.product_id)
                            const setSize = prod?.set_size || 1
                            const addQty = setSize > 1 ? Math.floor(item.qty / setSize) : item.qty
                            return (
                            <tr key={i}>
                              <td style={{ fontFamily: 'monospace', fontSize: 12 }}>{item.sku}</td>
                              <td style={{ fontSize: 12 }}>{item.name_jp || item.name_cn}</td>
                              <td style={{ fontSize: 12 }}>{item.color}</td>
                              <td style={{ fontSize: 12 }}>{item.size}</td>
                              <td style={{ textAlign: 'right' }}>{item.qty}</td>
                              <td style={{ textAlign: 'right', fontWeight: 700, color: '#166534' }}>
                                {addQty}{setSize > 1 && <span style={{ fontSize: 11, color: '#64748b', fontWeight: 400 }}>（{setSize}個で1セット）</span>}
                              </td>
                            </tr>
                            )
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {unmatched.length > 0 && (
                    <div className="card" style={{ marginBottom: 16 }}>
                      <h3 style={{ color: '#e94560', marginBottom: 12 }}>
                        未照合 {unmatched.filter(it => !it.sku && !it.excluded).length}件
                        {unmatched.some(it => it.excluded) && (
                          <span style={{ fontSize: 13, color: '#94a3b8', fontWeight: 400, marginLeft: 8 }}>
                            ／ 対象外 {unmatched.filter(it => it.excluded).length}件
                          </span>
                        )}
                      </h3>
                      <table>
                        <thead><tr><th>商品名(中)</th><th>色</th><th>サイズ</th><th style={{ textAlign: 'right' }}>数量</th><th>SKU選択</th></tr></thead>
                        <tbody>
                          {unmatched.map((item, i) => (
                            <React.Fragment key={i}>
                            <tr style={item.excluded ? { opacity: 0.45, background: '#f8fafc' } : undefined}>
                              <td style={{ fontSize: 12 }}>
                                <div>{item.name_cn}</div>
                                {item.buy_url && <a href={item.buy_url} target="_blank" rel="noreferrer" style={{ fontSize: 11, color: '#3b82f6' }}>URL</a>}
                              </td>
                              <td style={{ fontSize: 12 }}>{item.color}</td>
                              <td style={{ fontSize: 12 }}>{item.size}</td>
                              <td style={{ textAlign: 'right' }}>{item.qty}</td>
                              <td>
                                {item.excluded
                                  ? <span style={{ fontSize: 12, color: '#94a3b8' }}>
                                      対象外（在庫反映しない）
                                      <button className="btn btn-secondary" style={{ fontSize: 11, padding: '2px 8px', marginLeft: 8 }}
                                        onClick={() => setUnmatched(prev => prev.map((it, idx) => idx === i ? { ...it, excluded: false } : it))}>
                                        戻す
                                      </button>
                                    </span>
                                  : item.sku
                                  ? (() => {
                                      const prod = allProducts.find(p => p.id === item.product_id)
                                      const s = prod?.set_size || 1
                                      return (
                                        <span style={{ fontSize: 12, color: '#166534', fontWeight: 700 }}>
                                          {item.sku}
                                          <span style={{ fontSize: 11, color: '#64748b', fontWeight: 400, marginLeft: 6 }}>
                                            在庫加算 {Math.floor(item.qty / s)}{s > 1 ? `（${item.qty}÷${s}）` : ''}
                                          </span>
                                        </span>
                                      )
                                    })()
                                  : <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                                      <select style={{ fontSize: 12 }} defaultValue="" onChange={e => handleUnmatchedSelect(i, e.target.value)}>
                                        <option value="">-- 選択 --</option>
                                        {allProducts.map(p => <option key={p.id} value={p.id}>{p.sku} {p.name}</option>)}
                                      </select>
                                      <button className="btn btn-secondary" style={{ fontSize: 11, padding: '3px 8px', whiteSpace: 'nowrap' }}
                                        onClick={() => openRegister(i)}>＋新規登録</button>
                                      <button className="btn btn-secondary" style={{ fontSize: 11, padding: '3px 8px', whiteSpace: 'nowrap', color: '#94a3b8' }}
                                        title="梱包材など、在庫にも商品マスタにも入れない行"
                                        onClick={() => setUnmatched(prev => prev.map((it, idx) => idx === i ? { ...it, excluded: true, product_id: null, sku: '' } : it))}>
                                        対象外
                                      </button>
                                    </div>
                                }
                              </td>
                            </tr>
                            {regRow === i && !item.sku && (
                              <tr>
                                <td colSpan={5} style={{ background: '#f8fafc', padding: '12px 16px' }}>
                                  <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end', flexWrap: 'wrap' }}>
                                    <div>
                                      <label style={{ fontSize: 11, color: '#64748b', display: 'block' }}>SKU（必須）</label>
                                      <input value={regForm.sku} placeholder="例: y134_black" style={{ width: 140, fontSize: 12 }}
                                        onChange={e => setRegForm(f => ({ ...f, sku: e.target.value }))} />
                                    </div>
                                    <div>
                                      <label style={{ fontSize: 11, color: '#64748b', display: 'block' }}>商品名（空欄なら中国語名）</label>
                                      <input value={regForm.name} placeholder={item.name_cn} style={{ width: 240, fontSize: 12 }}
                                        onChange={e => setRegForm(f => ({ ...f, name: e.target.value }))} />
                                    </div>
                                    <div>
                                      <label style={{ fontSize: 11, color: '#64748b', display: 'block' }}>セット入数</label>
                                      <input type="number" min="1" value={regForm.set_size} style={{ width: 70, fontSize: 12 }}
                                        onChange={e => setRegForm(f => ({ ...f, set_size: e.target.value }))} />
                                    </div>
                                    <div>
                                      <label style={{ fontSize: 11, color: '#64748b', display: 'block' }}>販売価格（円・任意）</label>
                                      <input type="number" value={regForm.selling_price} style={{ width: 90, fontSize: 12 }}
                                        onChange={e => setRegForm(f => ({ ...f, selling_price: e.target.value }))} />
                                    </div>
                                    <div style={{ fontSize: 11, color: '#64748b' }}>
                                      入荷数: {item.qty} ÷ {parseInt(regForm.set_size) || 1} = <b>{Math.floor(item.qty / (parseInt(regForm.set_size) || 1))}</b>個
                                      ／ 仕入単価 {item.unit_price_cny}元・色/仕様は自動セット
                                    </div>
                                    <button className="btn btn-primary" style={{ fontSize: 12, padding: '4px 12px' }}
                                      onClick={handleRegister} disabled={registering}>
                                      {registering ? '登録中...' : '登録して照合'}
                                    </button>
                                    <button className="btn btn-secondary" style={{ fontSize: 12, padding: '4px 12px' }}
                                      onClick={() => setRegRow(null)}>キャンセル</button>
                                  </div>
                                </td>
                              </tr>
                            )}
                            </React.Fragment>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  <button className="btn btn-primary" onClick={handleSaveAndReceive} disabled={saving}>
                    {saving ? '反映中...' : '在庫に反映する'}
                  </button>
                </>
              )}
            </>
      }
    </div>
  )
}

async function downloadExcel(items) {
  const res = await api.post('/rakuten/orders/excel', {
    items,
    record_history: true,
    memo: '発注Excelから登録',
  }, { responseType: 'blob' })
  const url = URL.createObjectURL(new Blob([res.data]))
  const a = document.createElement('a')
  a.href = url
  a.download = `${new Date().toISOString().slice(0,10).replace(/-/g,'')}_rakuten_order.xlsx`
  a.click()
  URL.revokeObjectURL(url)
}

export default function RakutenOrderPage() {
  const qc = useQueryClient()
  const [tab, setTab] = useState('order')
  const [orderInputs, setOrderInputs] = useState({})
  const [ordering, setOrdering] = useState(null)
  const [downloading, setDownloading] = useState(false)
  const [search, setSearch] = useState('')
  const [onlyRecommended, setOnlyRecommended] = useState(false)

  const { data: allData, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['rakuten-all-products-order'],
    queryFn: () => api.get('/rakuten/orders/all-products').then(r => r.data),
    enabled: tab === 'order',
    staleTime: 0,
  })

  const { data: history = [] } = useQuery({
    queryKey: ['rakuten-order-history'],
    queryFn: () => api.get('/rakuten/orders/history').then(r => r.data),
    enabled: tab === 'history',
  })

  const createOrder = useMutation({
    mutationFn: (body) => api.post('/rakuten/orders/history', body),
    onSuccess: () => {
      qc.invalidateQueries(['rakuten-all-products-order'])
      qc.invalidateQueries(['rakuten-order-history'])
    },
  })

  const deleteOrder = useMutation({
    mutationFn: (id) => api.delete(`/rakuten/orders/history/${id}`),
    onSuccess: () => qc.refetchQueries(['rakuten-order-history']),
  })

  const changeStage = useMutation({
    mutationFn: ({ id, stage }) => api.patch(`/rakuten/orders/history/${id}/stage`, { stage }),
    onSuccess: () => {
      qc.refetchQueries(['rakuten-order-history'])
      qc.invalidateQueries(['rakuten-all-products-order'])
    },
  })

  const settings = allData?.settings || {}
  const thresholdDays = settings.threshold_days ?? 40

  const handleOrder = async (item) => {
    const qty = orderInputs[item.sku] ?? item.order_qty
    if (!qty || qty <= 0) return
    setOrdering(item.sku)
    try {
      await createOrder.mutateAsync({ sku: item.sku, name: item.name, qty: Number(qty) })
    } finally {
      setOrdering(null)
    }
  }

  const handleExcelDownload = async () => {
    const targets = displayItems
      .map(item => ({ sku: item.sku, qty: Number(orderInputs[item.sku] ?? item.order_qty) }))
      .filter(i => i.qty > 0)
    if (targets.length === 0) { alert('発注数が1以上の商品がありません'); return }
    setDownloading(true)
    try {
      await downloadExcel(targets)
      qc.invalidateQueries(['rakuten-all-products-order'])
      qc.invalidateQueries(['rakuten-order-history'])
    } finally {
      setDownloading(false)
    }
  }

  const allItems = allData?.items || []
  const displayItems = allItems.filter(item => {
    if (onlyRecommended && !item.needs_order) return false
    if (!search) return true
    const q = search.toLowerCase()
    return item.sku.toLowerCase().includes(q) || (item.name || '').toLowerCase().includes(q)
  })

  const recommendedCount = allItems.filter(i => i.needs_order).length

  if (isLoading && !allData && tab === 'order') return <div className="loading">読み込み中...</div>

  const toggleBtn = (
    <button
      onClick={() => setOnlyRecommended(v => !v)}
      style={{
        padding: '8px 18px', fontSize: 14, fontWeight: 700, borderRadius: 24, border: 'none', cursor: 'pointer',
        background: onlyRecommended ? '#ea580c' : '#e2e8f0',
        color: onlyRecommended ? '#fff' : '#374151',
        boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
      }}
    >
      {onlyRecommended ? `発注推奨のみ（${recommendedCount}件）` : `全商品（${allItems.length}件）`}
    </button>
  )

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20, flexWrap: 'wrap' }}>
        <h1>🛒 楽天 発注管理</h1>
        <button className="btn" onClick={() => refetch()} disabled={isFetching} style={{ fontSize: 13 }}>
          {isFetching ? '更新中...' : '🔄 更新'}
        </button>
        <button
          className="btn"
          style={{ fontSize: 13, background: '#22c55e', color: '#fff', border: 'none' }}
          disabled={downloading}
          onClick={handleExcelDownload}
        >
          {downloading ? '生成中...' : '📥 発注Excel（タオタロウ）'}
        </button>
      </div>

      {/* タブ */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        <button className={`btn ${tab === 'order' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setTab('order')}>発注管理</button>
        <button className={`btn ${tab === 'history' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setTab('history')}>発注済みリスト</button>
        <button className={`btn ${tab === 'shipment' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setTab('shipment')}>配送依頼（在庫反映）</button>
      </div>

      {/* ===== 発注管理（全商品 + 発注推奨フィルター統合） ===== */}
      {tab === 'order' && (
        <>
          {/* 設定サマリー＋フィルタートグル */}
          <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
            {[
              ['目標販売日数', `${settings.target_days ?? 30}日`,   '#dbeafe', '#1e40af'],
              ['リードタイム', `${settings.lead_days ?? 20}日`,     '#dcfce7', '#166534'],
              ['安全在庫率',  `${((settings.safety_stock_rate ?? 0.10) * 100).toFixed(0)}%`, '#fef9c3', '#854d0e'],
              ['発注閾値',    `在庫${thresholdDays}日分以下`, '#fce7f3', '#9d174d'],
            ].map(([label, val, bg, color]) => (
              <div key={label} style={{ background: bg, borderRadius: 8, padding: '8px 16px', fontSize: 13 }}>
                <span style={{ color }}>{label}: </span>
                <span style={{ color, fontWeight: 800 }}>{val}</span>
              </div>
            ))}
            {toggleBtn}
          </div>

          {/* 検索 */}
          <div style={{ marginBottom: 12 }}>
            <input
              type="text" placeholder="SKU・商品名で絞り込み"
              value={search} onChange={e => setSearch(e.target.value)}
              style={{ width: 280 }}
            />
          </div>

          <div className="card" style={{ padding: 0, overflow: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ background: '#f0f2f8', borderBottom: '2px solid #e2e8f0' }}>
                  {['商品名 / SKU', '実在庫', '発注済1', '発注済2', '全在庫', '日販', '在庫日数', '成長率', '提案発注数', '発注'].map(h => (
                    <th key={h} style={{ padding: '10px 12px', textAlign: 'center', whiteSpace: 'nowrap' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {displayItems.length === 0 && (
                  <tr><td colSpan={10} style={{ textAlign: 'center', padding: 32, color: '#999' }}>
                    {onlyRecommended ? '発注が必要な商品はありません' : '商品がありません'}
                  </td></tr>
                )}
                {displayItems.map(item => {
                  const needsOrder = item.needs_order
                  const rowBg = needsOrder ? '#fff7ed' : 'transparent'
                  const inputVal = orderInputs[item.sku] ?? (item.order_qty > 0 ? item.order_qty : 0)
                  const comps = item.set_components || []
                  return (
                    <tr key={item.sku} style={{ borderBottom: '1px solid #f0f2f8', background: rowBg }}>
                      <td style={{ padding: '10px 12px', minWidth: 160 }}>
                        <div style={{ fontWeight: 400, color: '#1a1a2e' }}>{item.name || '—'}</div>
                        <div style={{ color: '#999', fontSize: 11 }}>{item.sku}</div>
                        {item.buy_url && (
                          <a href={item.buy_url} target="_blank" rel="noreferrer" style={{ fontSize: 11, color: '#e94560' }}>仕入れURL</a>
                        )}
                        {comps.length > 0 && (
                          <div style={{ marginTop: 4, paddingLeft: 8, borderLeft: '2px solid #e2e8f0' }}>
                            {comps.map((c, i) => (
                              <div key={i} style={{ fontSize: 11, color: '#666', lineHeight: 1.6 }}>
                                └ {c.supplier_spec || c.notes || c.sku}
                                {c.price ? <span style={{ color: '#999', marginLeft: 4 }}>{c.price}元</span> : null}
                                {c.buy_url && (
                                  <a href={c.buy_url} target="_blank" rel="noreferrer" style={{ color: '#e94560', marginLeft: 4 }}>URL</a>
                                )}
                              </div>
                            ))}
                          </div>
                        )}
                      </td>
                      <td style={{ padding: '10px 12px', textAlign: 'center', fontWeight: 600 }}>{item.stock}</td>
                      <td style={{ padding: '10px 12px', textAlign: 'center', color: '#666' }}>{item.ordered_1 ?? item.ordered}</td>
                      <td style={{ padding: '10px 12px', textAlign: 'center', color: '#666' }}>{item.ordered_2 ?? 0}</td>
                      <td style={{ padding: '10px 12px', textAlign: 'center', fontWeight: 600 }}>{item.total_stock}</td>
                      <td style={{ padding: '10px 12px', textAlign: 'center', color: '#666' }}>
                        {item.daily_avg > 0 ? item.daily_avg.toFixed(1) : '—'}
                      </td>
                      <td style={{ padding: '10px 12px', textAlign: 'center' }}>
                        <span className={`badge ${
                          item.days_left < thresholdDays ? 'badge-danger'
                          : item.days_left < 90 ? 'badge-warn' : 'badge-ok'
                        }`}>
                          {item.days_left >= 9999 ? '∞' : `${item.days_left}日`}
                        </span>
                      </td>
                      <td style={{ padding: '10px 12px', textAlign: 'center' }}>
                        <span style={{ color: item.growth_rate > 0 ? '#16a34a' : item.growth_rate < 0 ? '#dc2626' : '#666', fontWeight: 600 }}>
                          {item.growth_rate > 0 ? '+' : ''}{item.growth_rate}%
                        </span>
                      </td>
                      <td style={{ padding: '10px 12px', textAlign: 'center' }}>
                        {needsOrder ? (
                          <span className="badge badge-danger" style={{ fontSize: 14, padding: '4px 12px' }}>{item.order_qty}</span>
                        ) : (
                          <span style={{ color: item.order_qty > 0 ? '#16a34a' : '#999', fontWeight: 600 }}>
                            {item.order_qty > 0 ? item.order_qty : '—'}
                          </span>
                        )}
                      </td>
                      <td style={{ padding: '10px 12px', textAlign: 'center', whiteSpace: 'nowrap' }}>
                        <div style={{ display: 'flex', gap: 4, alignItems: 'center', justifyContent: 'center' }}>
                          <input
                            type="number" min={0}
                            value={inputVal}
                            onChange={e => setOrderInputs(p => ({ ...p, [item.sku]: e.target.value }))}
                            style={{ width: 60, textAlign: 'center', padding: '4px 6px', fontSize: 13 }}
                          />
                          <button
                            className="btn btn-primary"
                            style={{ padding: '4px 10px', fontSize: 12 }}
                            disabled={ordering === item.sku || !inputVal || Number(inputVal) <= 0}
                            onClick={() => handleOrder(item)}
                          >
                            発注
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <div style={{ fontSize: 12, color: '#999', marginTop: 8 }}>
            ※ <span style={{ color: '#ea580c', fontWeight: 700 }}>オレンジ行</span> = 全在庫が閾値（{thresholdDays}日分）以下 → 発注タイミング
          </div>

          {/* 右下フローティングトグルボタン */}
          <div style={{ position: 'fixed', bottom: 32, right: 32, zIndex: 1000 }}>
            {toggleBtn}
          </div>
        </>
      )}

      {/* ===== 配送依頼 ===== */}
      {tab === 'shipment' && <ShipmentTab />}

      {/* ===== 発注済みリスト ===== */}
      {tab === 'history' && (
        <div className="card">
          <h2>発注済みリスト（{history.length}件）</h2>
          {history.length === 0 ? (
            <div className="empty-state">
              <div style={{ fontSize: 40 }}>📋</div>
              <p>発注履歴がありません。</p>
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table>
                <thead>
                  <tr>
                    <th>発注日</th>
                    <th>SKU</th>
                    <th>商品名</th>
                    <th>発注数</th>
                    <th style={{ textAlign: 'center' }}>ステージ</th>
                    <th>メモ</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {history.map(row => (
                    <tr key={row.id}>
                      <td style={{ fontSize: 12, whiteSpace: 'nowrap', color: '#666' }}>
                        {row.ordered_at || '—'}
                      </td>
                      <td style={{ fontFamily: 'monospace', fontSize: 12 }}>{row.sku}</td>
                      <td style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{row.name || '—'}</td>
                      <td style={{ textAlign: 'right', fontWeight: 600 }}>{row.qty}</td>
                      <td style={{ textAlign: 'center', whiteSpace: 'nowrap' }}>
                        <span style={{
                          padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 700,
                          background: (row.stage ?? 1) === 2 ? '#fef9c3' : '#dbeafe',
                          color: (row.stage ?? 1) === 2 ? '#854d0e' : '#1e40af',
                        }}>
                          発注済{row.stage ?? 1}
                        </span>
                        <button
                          className="btn btn-sm"
                          style={{ marginLeft: 6, fontSize: 11, padding: '2px 8px' }}
                          disabled={changeStage.isPending}
                          title={`発注済${(row.stage ?? 1) === 2 ? 1 : 2}に切り替えます`}
                          onClick={() => changeStage.mutate({ id: row.id, stage: (row.stage ?? 1) === 2 ? 1 : 2 })}
                        >⇄</button>
                      </td>
                      <td style={{ fontSize: 12, color: '#666' }}>{row.memo || '—'}</td>
                      <td>
                        <button
                          className="btn btn-sm"
                          style={{ background: '#fee2e2', color: '#991b1b', whiteSpace: 'nowrap' }}
                          onClick={() => {
                            if (confirm(`${row.sku} を発注済みリストから削除しますか？\n（納品済み・誤発注の場合に押してください）`))
                              deleteOrder.mutate(row.id)
                          }}
                        >削除</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <td colSpan={3} style={{ textAlign: 'right', fontWeight: 700, paddingTop: 12 }}>合計</td>
                    <td style={{ textAlign: 'right', fontWeight: 700 }}>
                      {history.reduce((s, r) => s + r.qty, 0)} 個
                    </td>
                    <td colSpan={3}></td>
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
