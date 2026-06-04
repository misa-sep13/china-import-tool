import { useState } from 'react'
import axios from 'axios'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000/api'

export default function InvoicePage() {
  const [parsed, setParsed] = useState(null)
  const [form, setForm] = useState({ invoice_date: '', exchange_rate: 20.0 })
  const [calculated, setCalculated] = useState(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(null)
  const [uploading, setUploading] = useState(false)

  async function handleFile(e) {
    const file = e.target.files[0]
    if (!file) return
    setUploading(true)
    const fd = new FormData()
    fd.append('file', file)
    try {
      const res = await axios.post(`${API}/invoices/parse-excel`, fd)
      setParsed(res.data)
      setForm(f => ({
        ...f,
        invoice_no: res.data.invoice_no,
        domestic_freight: res.data.domestic_freight,
        international_freight: res.data.international_freight,
        total_weight: res.data.total_weight,
        total_volume: res.data.total_volume,
      }))
      setCalculated(null)
      setSaved(null)
    } catch (e) {
      alert('読み込みエラー: ' + (e.response?.data?.detail || e.message))
    } finally {
      setUploading(false)
    }
  }

  async function handleCalculate() {
    if (!parsed) return
    const payload = {
      ...form,
      exchange_rate: parseFloat(form.exchange_rate),
      domestic_freight: parseFloat(form.domestic_freight || 0),
      international_freight: parseFloat(form.international_freight || 0),
      total_weight: parseFloat(form.total_weight || 0),
      total_volume: parseFloat(form.total_volume || 0),
      items: parsed.items,
    }
    const res = await axios.post(`${API}/invoices/calculate`, payload)
    setCalculated(res.data)
  }

  async function handleSave() {
    if (!calculated) return
    setSaving(true)
    try {
      const payload = {
        ...form,
        exchange_rate: parseFloat(form.exchange_rate),
        domestic_freight: parseFloat(form.domestic_freight || 0),
        international_freight: parseFloat(form.international_freight || 0),
        total_weight: parseFloat(form.total_weight || 0),
        total_volume: parseFloat(form.total_volume || 0),
        items: parsed.items,
      }
      const res = await axios.post(`${API}/invoices/save`, payload)
      setSaved(res.data)
    } catch (e) {
      alert('保存エラー: ' + (e.response?.data?.detail || e.message))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <h2 style={{ marginBottom: 24 }}>📦 仕入管理</h2>

      <div className="card" style={{ marginBottom: 16 }}>
        <h3 style={{ marginBottom: 16 }}>インボイス読み込み</h3>
        <input type="file" accept=".xlsx,.xls" onChange={handleFile} disabled={uploading} />
        {uploading && <span style={{ marginLeft: 12, color: '#888' }}>読み込み中...</span>}
      </div>

      {parsed && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h3 style={{ marginBottom: 16 }}>基本情報</h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
            {[
              ['インボイス番号', 'invoice_no'],
              ['仕入日', 'invoice_date'],
              ['為替レート（円/元）', 'exchange_rate'],
              ['国内運費（元）', 'domestic_freight'],
              ['国際運費（元）', 'international_freight'],
              ['総重量（kg）', 'total_weight'],
              ['総容積（m3）', 'total_volume'],
            ].map(([label, key]) => (
              <div key={key} className="form-group">
                <label>{label}</label>
                <input
                  value={form[key] ?? ''}
                  onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
                  type={['exchange_rate','domestic_freight','international_freight','total_weight','total_volume'].includes(key) ? 'number' : 'text'}
                  step="0.01"
                />
              </div>
            ))}
          </div>
          <div style={{ marginTop: 16 }}>
            <button className="btn-primary" onClick={handleCalculate}>原価を計算</button>
          </div>
        </div>
      )}

      {calculated && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <h3>計算結果</h3>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              {saved && (
                <span style={{ color: 'green', fontSize: 13 }}>
                  保存済み（{saved.updated_products}件の商品マスタを更新）
                </span>
              )}
              <button className="btn-primary" onClick={handleSave} disabled={saving || !!saved}>
                {saving ? '保存中...' : '商品マスタに反映して保存'}
              </button>
            </div>
          </div>

          <div style={{ marginBottom: 12, fontSize: 13, color: '#555' }}>
            合計数量: {calculated.total_qty}個 ／
            仕入合計: ¥{calculated.total_cny.toLocaleString()}元 ／
            送料合計: ¥{calculated.total_freight_cny.toLocaleString()}元 ／
            総原価: ¥{calculated.grand_total_jpy.toLocaleString()}円
          </div>

          <div style={{ overflowX: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th>TAO SKU</th>
                  <th>品名</th>
                  <th style={{ textAlign: 'right' }}>数量</th>
                  <th style={{ textAlign: 'right' }}>単価(元)</th>
                  <th style={{ textAlign: 'right' }}>小計(元)</th>
                  <th style={{ textAlign: 'right' }}>按分送料(元)</th>
                  <th style={{ textAlign: 'right', color: '#e94560', fontWeight: 'bold' }}>1個原価(円)</th>
                </tr>
              </thead>
              <tbody>
                {calculated.items.map((item, i) => (
                  <tr key={i}>
                    <td style={{ fontFamily: 'monospace', fontSize: 12 }}>{item.sku}</td>
                    <td style={{ fontSize: 12 }}>{item.name_jp || item.name_cn}</td>
                    <td style={{ textAlign: 'right' }}>{item.qty}</td>
                    <td style={{ textAlign: 'right' }}>{item.unit_price_cny}</td>
                    <td style={{ textAlign: 'right' }}>{item.total_price_cny}</td>
                    <td style={{ textAlign: 'right' }}>{item.freight_alloc_cny}</td>
                    <td style={{ textAlign: 'right', color: '#e94560', fontWeight: 'bold' }}>¥{item.cost_per_unit_jpy.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
