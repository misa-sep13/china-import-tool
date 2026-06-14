import { useState } from 'react'
import api from '../api/client'

export default function RakutenInvoicePage() {
  const [parsed, setParsed] = useState(null)
  const [form, setForm] = useState({
    invoice_no: '', invoice_date: '', exchange_rate: 20.0,
    domestic_freight: 0, international_freight: 0, import_tax_jpy: 0,
  })
  const [calculated, setCalculated] = useState(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [parsingPdf, setParsingPdf] = useState(false)
  const [pdfResult, setPdfResult] = useState(null)

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

  async function handlePdf(e) {
    const file = e.target.files[0]
    if (!file) return
    setParsingPdf(true)
    setPdfResult(null)
    const fd = new FormData()
    fd.append('file', file)
    try {
      const res = await api.post('/rakuten/invoices/parse-pdf', fd)
      setPdfResult(res.data)
      setForm(f => ({
        ...f,
        import_tax_jpy: res.data.import_tax_jpy || 0,
        ...(res.data.exchange_rate ? { exchange_rate: res.data.exchange_rate } : {}),
      }))
      setCalculated(null)
    } catch (err) {
      alert('PDF読み込みエラー: ' + (err.response?.data?.detail || err.message))
    } finally {
      setParsingPdf(false)
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
      import_tax_jpy: parseFloat(form.import_tax_jpy || 0),
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
        import_tax_jpy: parseFloat(form.import_tax_jpy || 0),
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
        <h3 style={{ marginBottom: 16 }}>ファイル読み込み</h3>
        <div style={{ fontSize: 12, color: '#92400e', background: '#fef3c7', border: '1px solid #fbbf24', borderRadius: 6, padding: '8px 12px', marginBottom: 12 }}>
          ⚠️ インボイスExcelと輸入許可証PDFは<strong>同じ船便のもの</strong>をセットでアップロードしてください。
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{ width: 180, fontSize: 13, color: '#475569', flexShrink: 0 }}>① インボイスExcel（必須）</span>
            <input type="file" accept=".xlsx,.xls" onChange={handleFile} disabled={uploading} />
            {uploading && <span style={{ color: '#888', fontSize: 13 }}>読み込み中...</span>}
            {parsed && <span style={{ color: '#16a34a', fontSize: 13 }}>✅ {parsed.items.length}件読み込み済み</span>}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{ width: 180, fontSize: 13, color: '#475569', flexShrink: 0 }}>② 輸入許可証PDF（任意）</span>
            <input type="file" accept=".pdf" onChange={handlePdf} disabled={parsingPdf} />
            {parsingPdf && <span style={{ color: '#888', fontSize: 13 }}>読み込み中...</span>}
            {pdfResult && (
              <span style={{ color: '#16a34a', fontSize: 13 }}>
                ✅ 輸入税 ¥{pdfResult.import_tax_jpy.toLocaleString()}
                {pdfResult.exchange_rate ? ` / 為替 ${pdfResult.exchange_rate}円` : ''}
              </span>
            )}
          </div>
        </div>
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
            <div className="form-group">
              <label>
                輸入税合計（円）
                <span style={{ fontSize: 11, color: '#94a3b8', marginLeft: 6 }}>関税＋消費税＋地方消費税</span>
              </label>
              <input
                value={form.import_tax_jpy ?? 0}
                onChange={e => setForm(f => ({ ...f, import_tax_jpy: e.target.value }))}
                type="number"
                step="1"
                style={{ borderColor: form.import_tax_jpy > 0 ? '#16a34a' : undefined }}
              />
            </div>
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
            輸入税: ¥{(calculated.import_tax_jpy || 0).toLocaleString()} ／
            総原価: ¥{calculated.grand_total_jpy.toLocaleString()}
          </div>

          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ background: '#f0f2f8', borderBottom: '2px solid #e2e8f0' }}>
                  {['SKU', '品名', '商品内訳', '数量', '単価(元)', '小計(元)', '按分送料(元)', '按分税(円)', '1個原価(円)'].map(h => (
                    <th key={h} style={{ padding: '8px 12px', textAlign: ['SKU', '品名', '商品内訳'].includes(h) ? 'left' : 'right', whiteSpace: 'nowrap' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {calculated.items.map((item, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid #e5e7eb', background: item.asin_memo ? '#fffbeb' : undefined }}>
                    <td style={{ padding: '8px 12px', fontFamily: 'monospace', fontSize: 12 }}>{item.sku}</td>
                    <td style={{ padding: '8px 12px', fontSize: 12 }}>{item.name_jp || '—'}</td>
                    <td style={{ padding: '8px 12px', fontSize: 12 }}>
                      {item.asin_memo
                        ? <span style={{ background: '#fef08a', border: '1px solid #ca8a04', borderRadius: 4, padding: '2px 6px', fontSize: 11, fontWeight: 600 }}>
                            ⚠️ {item.asin_memo}
                          </span>
                        : item.invoice_note
                          ? <span style={{ color: '#64748b', fontSize: 11 }}>{item.invoice_note}</span>
                          : '—'}
                    </td>
                    <td style={{ padding: '8px 12px', textAlign: 'right' }}>{item.qty}</td>
                    <td style={{ padding: '8px 12px', textAlign: 'right' }}>{item.unit_price_cny}</td>
                    <td style={{ padding: '8px 12px', textAlign: 'right' }}>{item.total_price_cny}</td>
                    <td style={{ padding: '8px 12px', textAlign: 'right' }}>{item.freight_alloc_cny}</td>
                    <td style={{ padding: '8px 12px', textAlign: 'right', color: '#7c3aed' }}>
                      {item.tax_alloc_jpy ? `¥${item.tax_alloc_jpy.toLocaleString()}` : '—'}
                    </td>
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
