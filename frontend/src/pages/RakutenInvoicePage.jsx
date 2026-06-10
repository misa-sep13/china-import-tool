import { useState } from 'react'
import api from '../api/client'

export default function RakutenInvoicePage() {
  const [parsed, setParsed] = useState(null)
  const [form, setForm] = useState({ invoice_no: '', invoice_date: '', exchange_rate: 20.0, domestic_freight: 0, international_freight: 0 })
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
      const res = await api.post('/rakuten/invoices/parse-excel', fd)
      setParsed(res.data)
      setForm(f => ({
        ...f,
        invoice_no: res.data.invoice_no || '',
        domestic_freight: res.data.domestic_freight || 0,
        international_freight: res.data.international_freight || 0,
      }))
      setCalculated(null)
      setSaved(null)
    } catch (err) {
      alert('読み込みエラー: ' + (err.response?.data?.detail || err.message))
    } finally {
      setUploading(false)
      e.target.value = ''
    }
  }

  async function handleCalculate() {
    if (!parsed) return
    const payload = {
      ...form,
      exchange_rate: parseFloat(form.exchange_rate),
      domestic_freight: parseFloat(form.domestic_freight || 0),
      international_freight: parseFloat(form.international_freight || 0),
      items: parsed.items,
    }
    try {
      const res = await api.post('/rakuten/invoices/calculate', payload)
      setCalculated(res.data)
    } catch (err) {
      alert('計算エラー: ' + (err.response?.data?.detail || err.message))
    }
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
        items: parsed.items,
      }
      const res = await api.post('/rakuten/invoices/save', payload)
      setSaved(res.data)
    } catch (err) {
      alert('保存エラー: ' + (err.response?.data?.detail || err.message))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <h2 style={{ marginBottom: 24 }}>📄 楽天 仕入管理</h2>

      <div className="card" style={{ marginBottom: 16 }}>
        <h3 style={{ marginBottom: 16 }}>インボイスExcel読み込み</h3>
        <input type="file" accept=".xlsx,.xls" onChange={handleFile} disabled={uploading} />
        {uploading && <span style={{ marginLeft: 12, color: '#888' }}>読み込み中...</span>}
      </div>

      {parsed && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h3 style={{ marginBottom: 16 }}>基本情報</h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
            {[
              ['インボイス番号', 'invoice_no', 'text'],
              ['仕入日', 'invoice_date', 'date'],
              ['為替レート（円/元）', 'exchange_rate', 'number'],
              ['国内運費（元）', 'domestic_freight', 'number'],
              ['国際運費（元）', 'international_freight', 'number'],
            ].map(([label, key, type]) => (
              <div key={key} className="form-group">
                <label>{label}</label>
                <input
                  value={form[key] ?? ''}
                  onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
                  type={type}
                  step="0.01"
                />
              </div>
            ))}
          </div>
          <div style={{ marginTop: 16 }}>
            <button className="btn btn-primary" onClick={handleCalculate}>原価を計算</button>
          </div>
        </div>
      )}

      {calculated && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <h3>計算結果</h3>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              {saved && (
                <span style={{ color: '#16a34a', fontSize: 13 }}>
                  ✅ 保存済み（{saved.updated}件の商品マスタを更新）
                </span>
              )}
              <button className="btn btn-primary" onClick={handleSave} disabled={saving || !!saved}>
                {saving ? '保存中...' : '商品マスタに反映して保存'}
              </button>
            </div>
          </div>

          <div style={{ marginBottom: 12, fontSize: 13, color: '#555' }}>
            仕入合計: {calculated.total_cny.toLocaleString()}元 ／
            送料合計: {calculated.total_freight_cny.toLocaleString()}元 ／
            総原価: ¥{calculated.grand_total_jpy.toLocaleString()}円
          </div>

          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ background: '#f0f2f8', borderBottom: '2px solid #e2e8f0' }}>
                  {['SKU', '品名', '数量', '単価(元)', '小計(元)', '按分送料(元)', '1個原価(円)'].map(h => (
                    <th key={h} style={{ padding: '8px 12px', textAlign: h === 'SKU' || h === '品名' ? 'left' : 'right', whiteSpace: 'nowrap' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {calculated.items.map((item, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid #e5e7eb' }}>
                    <td style={{ padding: '8px 12px', fontFamily: 'monospace', fontSize: 12 }}>{item.sku}</td>
                    <td style={{ padding: '8px 12px', fontSize: 12 }}>{item.name_jp || '—'}</td>
                    <td style={{ padding: '8px 12px', textAlign: 'right' }}>{item.qty}</td>
                    <td style={{ padding: '8px 12px', textAlign: 'right' }}>{item.unit_price_cny}</td>
                    <td style={{ padding: '8px 12px', textAlign: 'right' }}>{item.total_price_cny}</td>
                    <td style={{ padding: '8px 12px', textAlign: 'right' }}>{item.freight_alloc_cny}</td>
                    <td style={{ padding: '8px 12px', textAlign: 'right', color: '#e94560', fontWeight: 700 }}>
                      ¥{item.cost_jpy.toLocaleString()}
                    </td>
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
