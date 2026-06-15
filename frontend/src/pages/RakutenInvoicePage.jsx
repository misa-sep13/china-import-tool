import { useState } from 'react'
import api from '../api/client'

export default function RakutenInvoicePage() {
  const [invoiceFile, setInvoiceFile] = useState(null)
  const [permitFile, setPermitFile]   = useState(null)
  const [validating, setValidating]   = useState(false)
  const [validation, setValidation]   = useState(null)
  const [parsed, setParsed]           = useState(null)
  const [pdfResult, setPdfResult]     = useState(null)
  const [form, setForm] = useState({
    invoice_no: '', invoice_date: '', exchange_rate: 20.0,
    domestic_freight: 0, international_freight: 0, import_tax_jpy: 0,
  })
  const [calculated, setCalculated] = useState(null)
  const [saving, setSaving]         = useState(false)
  const [saved, setSaved]           = useState(null)

  function reset() {
    setValidation(null); setParsed(null); setPdfResult(null); setCalculated(null); setSaved(null)
    setForm({ invoice_no: '', invoice_date: '', exchange_rate: 20.0, domestic_freight: 0, international_freight: 0, import_tax_jpy: 0 })
  }

  async function handleValidate() {
    if (!invoiceFile || !permitFile) {
      alert('インボイスと輸入許可書の両方を選択してください')
      return
    }
    setValidating(true)
    reset()
    try {
      // 整合性チェック
      const fd1 = new FormData()
      fd1.append('invoice_file', invoiceFile)
      fd1.append('permit_file', permitFile)
      const vRes = await api.post('/rakuten/invoices/validate-pair', fd1)
      setValidation(vRes.data)
      if (!vRes.data.ok) return

      // インボイスパース
      const fd2 = new FormData()
      fd2.append('file', invoiceFile)
      const invRes = await api.post('/rakuten/invoices/parse-excel', fd2)
      setParsed(invRes.data)
      setForm(f => ({
        ...f,
        invoice_no: invRes.data.invoice_no || '',
        domestic_freight: invRes.data.domestic_freight || 0,
        international_freight: invRes.data.international_freight || 0,
      }))

      // 輸入許可書パース
      const fd3 = new FormData()
      fd3.append('file', permitFile)
      const pdfRes = await api.post('/rakuten/invoices/parse-pdf', fd3)
      setPdfResult(pdfRes.data)
      setForm(f => ({
        ...f,
        import_tax_jpy: pdfRes.data.import_tax_jpy || 0,
        ...(pdfRes.data.exchange_rate ? { exchange_rate: pdfRes.data.exchange_rate } : {}),
      }))
    } catch (err) {
      alert('エラー: ' + (err.response?.data?.detail || err.message))
    } finally {
      setValidating(false)
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
      <h2 style={{ marginBottom: 24 }}>楽天 仕入管理（原価計算）</h2>

      {/* ファイル選択 */}
      <div className="card" style={{ marginBottom: 16 }}>
        <h3 style={{ marginBottom: 16 }}>ファイル選択（2つセットでアップロード）</h3>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <div className="form-group">
            <label>インボイス（.xlsx）</label>
            <input type="file" accept=".xlsx,.xls"
              onChange={e => { setInvoiceFile(e.target.files[0]); reset() }} />
          </div>
          <div className="form-group">
            <label>輸入許可書（.pdf）</label>
            <input type="file" accept=".pdf"
              onChange={e => { setPermitFile(e.target.files[0]); reset() }} />
          </div>
        </div>
        <div style={{ marginTop: 16 }}>
          <button className="btn btn-primary" onClick={handleValidate}
            disabled={validating || !invoiceFile || !permitFile}>
            {validating ? '照合中...' : '整合性チェック＆読み込み'}
          </button>
        </div>
      </div>

      {/* 照合結果 */}
      {validation && (
        <div className="card" style={{ marginBottom: 16, borderLeft: `4px solid ${validation.ok ? '#22c55e' : '#e94560'}` }}>
          <div style={{ fontWeight: 700, color: validation.ok ? '#166534' : '#e94560' }}>
            {validation.ok ? '照合OK — 同じ便のファイルです' : '照合NG — ファイルが対応していません'}
          </div>
          <div style={{ fontSize: 13, marginTop: 4, color: '#555' }}>
            インボイスCNY合計: {validation.invoice_cny}元 ／ 輸入許可書CNY: {validation.permit_cny}元 ／ 差額: {validation.diff}元
          </div>
          {!validation.ok && <div style={{ fontSize: 13, color: '#e94560', marginTop: 4 }}>{validation.message}</div>}
        </div>
      )}

      {/* 輸入許可書情報 */}
      {pdfResult && validation?.ok && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h3 style={{ marginBottom: 12 }}>輸入許可書情報</h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, fontSize: 13 }}>
            <div><b>為替レート:</b> {pdfResult.exchange_rate}円/元</div>
            <div><b>輸入税合計（関税＋消費税＋地方消費税）:</b> ¥{pdfResult.import_tax_jpy?.toLocaleString()}</div>
          </div>
        </div>
      )}

      {/* 基本情報入力 */}
      {parsed && validation?.ok && (
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
                <input value={form[key] ?? ''} type={type} step="0.01"
                  onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))} />
              </div>
            ))}
            <div className="form-group">
              <label>
                輸入税合計（円）
                <span style={{ fontSize: 11, color: '#94a3b8', marginLeft: 6 }}>関税＋消費税＋地方消費税</span>
              </label>
              <input value={form.import_tax_jpy ?? 0} type="number" step="1"
                style={{ borderColor: form.import_tax_jpy > 0 ? '#16a34a' : undefined }}
                onChange={e => setForm(f => ({ ...f, import_tax_jpy: e.target.value }))} />
            </div>
          </div>
          <div style={{ marginTop: 16 }}>
            <button className="btn btn-primary" onClick={handleCalculate}>原価を計算</button>
          </div>
        </div>
      )}

      {/* 計算結果 */}
      {calculated && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <h3>計算結果</h3>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              {saved && <span style={{ color: '#16a34a', fontSize: 13 }}>保存済み（{saved.updated}件の商品マスタを更新）</span>}
              <button className="btn btn-primary" onClick={handleSave} disabled={saving || !!saved}>
                {saving ? '保存中...' : '楽天商品マスタに反映して保存'}
              </button>
            </div>
          </div>
          <div style={{ marginBottom: 12, fontSize: 13, color: '#555' }}>
            仕入合計: {calculated.total_cny?.toLocaleString()}元 ／
            送料合計: {calculated.total_freight_cny?.toLocaleString()}元 ／
            輸入税: ¥{(calculated.import_tax_jpy || 0).toLocaleString()} ／
            総原価: ¥{calculated.grand_total_jpy?.toLocaleString()}
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
                        ? <span style={{ background: '#fef08a', border: '1px solid #ca8a04', borderRadius: 4, padding: '2px 6px', fontSize: 11, fontWeight: 600 }}>⚠️ {item.asin_memo}</span>
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
                      ¥{item.cost_jpy?.toLocaleString()}
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
