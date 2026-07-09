import { useState, useEffect } from 'react'
import axios from 'axios'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000/api'

export default function ShipmentOrderPage() {
  const [tab, setTab] = useState('list')  // 'list' | 'new'
  const [orders, setOrders] = useState([])
  const [detail, setDetail] = useState(null)  // 詳細表示中のorder
  const [detailItems, setDetailItems] = useState([])

  // 新規取り込み用
  const [uploading, setUploading] = useState(false)
  const [parsed, setParsed] = useState(null)
  const [matched, setMatched] = useState([])
  const [unmatched, setUnmatched] = useState([])
  const [allProducts, setAllProducts] = useState([])
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState({ note: '' })

  useEffect(() => {
    fetchOrders()
    axios.get(`${API}/products/`).then(r => setAllProducts(r.data)).catch(() => {})
  }, [])

  async function fetchOrders() {
    const res = await axios.get(`${API}/shipment-orders/`)
    setOrders(res.data)
  }

  async function handleFile(e) {
    const file = e.target.files[0]
    if (!file) return
    setUploading(true)
    setParsed(null)
    setMatched([])
    setUnmatched([])
    const fd = new FormData()
    fd.append('file', file)
    try {
      const res = await axios.post(`${API}/shipment-orders/parse-excel`, fd)
      setParsed(res.data)
      // 照合
      const matchRes = await axios.post(`${API}/shipment-orders/match`, res.data.items)
      setMatched(matchRes.data.matched)
      setUnmatched(matchRes.data.unmatched)
      setForm({ note: '' })
    } catch (e) {
      alert('読み込みエラー: ' + (e.response?.data?.detail || e.message))
    } finally {
      setUploading(false)
    }
  }

  function handleUnmatchedProductSelect(index, productId) {
    setUnmatched(prev => prev.map((item, i) => {
      if (i !== index) return item
      const product = allProducts.find(p => p.id === parseInt(productId))
      return { ...item, product_id: product?.id || null, sku: product?.sku || '', name_jp: product?.name || '' }
    }))
  }

  async function handleSave() {
    if (!parsed) return
    setSaving(true)
    try {
      await axios.post(`${API}/shipment-orders/save`, {
        shipped_date: parsed.shipped_date,
        tracking_no: parsed.tracking_no,
        order_no: parsed.order_no,
        box_count: parsed.box_count,
        total_weight_kg: parsed.total_weight_kg,
        note: form.note,
        matched,
        unmatched,
      })
      await fetchOrders()
      setTab('list')
      setParsed(null)
      setMatched([])
      setUnmatched([])
    } catch (e) {
      alert('保存エラー: ' + (e.response?.data?.detail || e.message))
    } finally {
      setSaving(false)
    }
  }

  async function handleShowDetail(order) {
    setDetail(order)
    const res = await axios.get(`${API}/shipment-orders/${order.id}/items`)
    setDetailItems(res.data)
  }

  async function handleMatchItem(orderId, itemId, productId) {
    try {
      await axios.patch(`${API}/shipment-orders/${orderId}/items/${itemId}/match`, { product_id: parseInt(productId) })
      const res = await axios.get(`${API}/shipment-orders/${orderId}/items`)
      setDetailItems(res.data)
      await fetchOrders()
    } catch (e) {
      alert('照合エラー: ' + (e.response?.data?.detail || e.message))
    }
  }

  async function handleReceive(orderId) {
    if (!confirm('入荷済みにして在庫を加算しますか？（この操作は元に戻せません）')) return
    try {
      const res = await axios.post(`${API}/shipment-orders/${orderId}/receive`)
      const rmsFail = res.data.rms_push_fail || 0
      const dupSkip = res.data.duplicate_skipped || 0
      alert(
        `入荷処理完了。${res.data.updated}件の在庫を加算しました。（未照合スキップ: ${res.data.skipped}件）\n`
        + (dupSkip > 0 ? `色違い等の重複行スキップ: ${dupSkip}件\n` : '')
        + `RMS反映: ok ${res.data.rms_push_ok || 0} / fail ${rmsFail}`
        + (rmsFail > 0 ? '\nRMS反映に失敗したSKUがあります。補正pushが必要です。' : '')
      )
      await fetchOrders()
      if (detail?.id === orderId) {
        setDetail(prev => ({ ...prev, status: 'received' }))
      }
    } catch (e) {
      alert('エラー: ' + (e.response?.data?.detail || e.message))
    }
  }

  const tabStyle = (t) => ({
    padding: '8px 20px',
    cursor: 'pointer',
    borderBottom: tab === t ? '2px solid #3b82f6' : '2px solid transparent',
    fontWeight: tab === t ? 700 : 400,
    color: tab === t ? '#3b82f6' : '#555',
    background: 'none',
    border: 'none',
    borderBottom: tab === t ? '2px solid #3b82f6' : '2px solid transparent',
    fontSize: 14,
  })

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>配送依頼管理</h2>

      <div style={{ display: 'flex', borderBottom: '1px solid #ddd', marginBottom: 24 }}>
        <button style={tabStyle('list')} onClick={() => setTab('list')}>入荷予定一覧</button>
        <button style={tabStyle('new')} onClick={() => setTab('new')}>配送依頼を取り込む</button>
      </div>

      {/* ===== 一覧タブ ===== */}
      {tab === 'list' && !detail && (
        <div>
          {orders.length === 0 ? (
            <p style={{ color: '#888' }}>配送依頼がまだありません。</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>追跡番号</th>
                  <th>出荷日</th>
                  <th>箱数</th>
                  <th style={{ textAlign: 'right' }}>重量(kg)</th>
                  <th style={{ textAlign: 'center' }}>商品数</th>
                  <th style={{ textAlign: 'center' }}>未照合</th>
                  <th style={{ textAlign: 'center' }}>状態</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {orders.map(o => (
                  <tr key={o.id}>
                    <td style={{ fontFamily: 'monospace', fontSize: 12 }}>{o.tracking_no}</td>
                    <td>{o.shipped_date}</td>
                    <td>{o.box_count}</td>
                    <td style={{ textAlign: 'right' }}>{o.total_weight_kg}</td>
                    <td style={{ textAlign: 'center' }}>{o.item_count}</td>
                    <td style={{ textAlign: 'center', color: o.unmatched_count > 0 ? '#e94560' : '#22c55e', fontWeight: 700 }}>
                      {o.unmatched_count > 0 ? `${o.unmatched_count}件未照合` : '照合済'}
                    </td>
                    <td style={{ textAlign: 'center' }}>
                      <span style={{
                        padding: '2px 8px',
                        borderRadius: 4,
                        fontSize: 12,
                        background: o.status === 'received' ? '#dcfce7' : '#fef9c3',
                        color: o.status === 'received' ? '#166534' : '#854d0e',
                        fontWeight: 700,
                      }}>
                        {o.status === 'received' ? '入荷済' : '入荷待ち'}
                      </span>
                    </td>
                    <td>
                      <button className="btn-secondary" style={{ fontSize: 12, padding: '4px 10px' }} onClick={() => handleShowDetail(o)}>
                        詳細
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* ===== 詳細 ===== */}
      {tab === 'list' && detail && (
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
            <button className="btn-secondary" onClick={() => setDetail(null)}>一覧に戻る</button>
            <h3 style={{ margin: 0 }}>{detail.tracking_no}</h3>
            <span style={{ fontSize: 13, color: '#888' }}>{detail.shipped_date} ／ {detail.box_count}箱 ／ {detail.total_weight_kg}kg</span>
            {detail.status !== 'received' && (
              <button className="btn-primary" style={{ marginLeft: 'auto' }} onClick={() => handleReceive(detail.id)}>
                入荷済みにして在庫加算
              </button>
            )}
            {detail.status === 'received' && (
              <span style={{ marginLeft: 'auto', color: '#166534', fontWeight: 700 }}>入荷済み</span>
            )}
          </div>

          <table>
            <thead>
              <tr>
                <th>商品名(中)</th>
                <th>色</th>
                <th>サイズ</th>
                <th style={{ textAlign: 'right' }}>数量</th>
                <th>照合SKU</th>
                <th>照合状態</th>
                {detail.status !== 'received' && <th>手動照合</th>}
              </tr>
            </thead>
            <tbody>
              {detailItems.map(item => (
                <tr key={item.id}>
                  <td style={{ fontSize: 12, maxWidth: 200 }}>{item.name_cn}</td>
                  <td style={{ fontSize: 12 }}>{item.color}</td>
                  <td style={{ fontSize: 12 }}>{item.size}</td>
                  <td style={{ textAlign: 'right' }}>{item.qty}</td>
                  <td style={{ fontFamily: 'monospace', fontSize: 12 }}>
                    {item.sku || <span style={{ color: '#aaa' }}>未照合</span>}
                    {item.name_jp && <div style={{ fontSize: 11, color: '#555' }}>{item.name_jp}</div>}
                  </td>
                  <td style={{ textAlign: 'center' }}>
                    <span style={{ fontSize: 12, color: item.is_matched ? '#22c55e' : '#e94560', fontWeight: 700 }}>
                      {item.is_matched ? '照合済' : '未照合'}
                    </span>
                  </td>
                  {detail.status !== 'received' && (
                    <td>
                      {!item.is_matched && (
                        <select
                          style={{ fontSize: 12 }}
                          defaultValue=""
                          onChange={e => e.target.value && handleMatchItem(detail.id, item.id, e.target.value)}
                        >
                          <option value="">-- SKUを選択 --</option>
                          {allProducts.map(p => (
                            <option key={p.id} value={p.id}>{p.sku} {p.name}</option>
                          ))}
                        </select>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* ===== 新規取り込みタブ ===== */}
      {tab === 'new' && (
        <div>
          <div className="card" style={{ marginBottom: 16 }}>
            <h3 style={{ marginBottom: 16 }}>配送依頼ファイルを読み込む</h3>
            <input type="file" accept=".xlsx,.xls" onChange={handleFile} disabled={uploading} />
            {uploading && <span style={{ marginLeft: 12, color: '#888' }}>読み込み・照合中...</span>}
          </div>

          {parsed && (
            <>
              <div className="card" style={{ marginBottom: 16 }}>
                <h3 style={{ marginBottom: 12 }}>配送情報</h3>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, fontSize: 13 }}>
                  <div><b>追跡番号:</b> {parsed.tracking_no}</div>
                  <div><b>出荷日:</b> {parsed.shipped_date}</div>
                  <div><b>配送依頼No:</b> {parsed.order_no}</div>
                  <div><b>箱数:</b> {parsed.box_count}</div>
                  <div><b>重量:</b> {parsed.total_weight_kg}kg</div>
                </div>
                <div className="form-group" style={{ marginTop: 12 }}>
                  <label>メモ</label>
                  <input value={form.note} onChange={e => setForm(f => ({ ...f, note: e.target.value }))} />
                </div>
              </div>

              {matched.length > 0 && (
                <div className="card" style={{ marginBottom: 16 }}>
                  <h3 style={{ marginBottom: 12, color: '#166534' }}>照合済み（{matched.length}件）</h3>
                  <table>
                    <thead>
                      <tr>
                        <th>SKU</th>
                        <th>商品名</th>
                        <th>色</th>
                        <th>サイズ</th>
                        <th style={{ textAlign: 'right' }}>数量</th>
                        <th style={{ textAlign: 'right' }}>単価(元)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {matched.map((item, i) => (
                        <tr key={i}>
                          <td style={{ fontFamily: 'monospace', fontSize: 12 }}>{item.sku}</td>
                          <td style={{ fontSize: 12 }}>{item.name_jp || item.name_cn}</td>
                          <td style={{ fontSize: 12 }}>{item.color}</td>
                          <td style={{ fontSize: 12 }}>{item.size}</td>
                          <td style={{ textAlign: 'right' }}>{item.qty}</td>
                          <td style={{ textAlign: 'right' }}>{item.unit_price_cny}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {unmatched.length > 0 && (
                <div className="card" style={{ marginBottom: 16 }}>
                  <h3 style={{ marginBottom: 12, color: '#e94560' }}>未照合（{unmatched.length}件）- 手動でSKUを選択してください</h3>
                  <table>
                    <thead>
                      <tr>
                        <th>商品名(中)</th>
                        <th>色</th>
                        <th>サイズ</th>
                        <th style={{ textAlign: 'right' }}>数量</th>
                        <th>SKU選択</th>
                      </tr>
                    </thead>
                    <tbody>
                      {unmatched.map((item, i) => (
                        <tr key={i}>
                          <td style={{ fontSize: 12, maxWidth: 200 }}>
                            <div>{item.name_cn}</div>
                            <div style={{ fontSize: 11, color: '#3b82f6' }}>
                              <a href={item.buy_url} target="_blank" rel="noreferrer" style={{ color: '#3b82f6' }}>URL</a>
                            </div>
                          </td>
                          <td style={{ fontSize: 12 }}>{item.color}</td>
                          <td style={{ fontSize: 12 }}>{item.size}</td>
                          <td style={{ textAlign: 'right' }}>{item.qty}</td>
                          <td>
                            {item.sku ? (
                              <span style={{ fontSize: 12, color: '#166534', fontWeight: 700 }}>{item.sku}</span>
                            ) : (
                              <select
                                style={{ fontSize: 12 }}
                                defaultValue=""
                                onChange={e => handleUnmatchedProductSelect(i, e.target.value)}
                              >
                                <option value="">-- SKUを選択 --</option>
                                {allProducts.map(p => (
                                  <option key={p.id} value={p.id}>{p.sku} {p.name}</option>
                                ))}
                              </select>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              <div style={{ display: 'flex', gap: 12 }}>
                <button className="btn-primary" onClick={handleSave} disabled={saving}>
                  {saving ? '保存中...' : '保存する（未照合はそのまま保存）'}
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
