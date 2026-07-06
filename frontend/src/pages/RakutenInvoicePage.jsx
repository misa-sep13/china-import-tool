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
  const [products, setProducts]     = useState([])

  function updateItemSku(index, sku) {
    setParsed(p => {
      const items = [...p.items]
      const prod = products.find(x => x.sku === sku)
      items[index] = { ...items[index], sku, name_jp: prod?.name || items[index].name_jp }
      return { ...p, items }
    })
    setCalculated(null); setSaved(null)
  }

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
      // SKU手動選択用に商品マスタを取得
      try {
        const pRes = await api.get('/rakuten/products')
        setProducts(pRes.data || [])
      } catch { /* SKU候補が出ないだけなので続行 */ }
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

  const blankSkuCount = parsed?.items?.filter(item => !(item.sku || '').trim()).length || 0
  const matchedSkuCount = parsed?.items?.length ? parsed.items.length - blankSkuCount : 0

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

      {/* 明細（SKU照合） */}
      {parsed && validation?.ok && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h3 style={{ marginBottom: 4 }}>明細（SKU照合）</h3>
          <div style={{ fontSize: 12, color: '#64748b', marginBottom: 12 }}>
            商品リンクURLで自動照合済み。楽天商品はSKUを選択してください。
            <span style={{ color: '#d97706', fontWeight: 600 }}> Amazon品など対象外の行は空欄のままでOK</span>です。計算・保存時にスキップされます。
            <span style={{ marginLeft: 8, color: '#475569' }}>反映対象 {matchedSkuCount}件 / スキップ {blankSkuCount}件</span>
          </div>
          <datalist id="rakuten-sku-options">
            {products.map(p => (
              <option key={p.sku} value={p.sku}>{p.name}</option>
            ))}
          </datalist>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ background: '#f0f2f8', borderBottom: '2px solid #e2e8f0' }}>
                  <th style={{ padding: '8px 12px', textAlign: 'left' }}>SKU</th>
                  <th style={{ padding: '8px 12px', textAlign: 'left' }}>品名</th>
                  <th style={{ padding: '8px 12px', textAlign: 'right' }}>数量</th>
                  <th style={{ padding: '8px 12px', textAlign: 'right' }}>単価(元)</th>
                  <th style={{ padding: '8px 12px', textAlign: 'left' }}>仕入先注文</th>
                  <th style={{ padding: '8px 12px', textAlign: 'left' }}>URL</th>
                </tr>
              </thead>
              <tbody>
                {parsed.items.map((item, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid #e5e7eb', background: item.sku ? undefined : '#fffbeb' }}>
                    <td style={{ padding: '4px 12px' }}>
                      <input list="rakuten-sku-options" value={item.sku || ''}
                        placeholder="空欄=対象外"
                        style={{ width: 150, fontFamily: 'monospace', fontSize: 12, padding: '4px 6px',
                                 border: `1px solid ${item.sku ? '#cbd5e1' : '#f59e0b'}`, borderRadius: 4 }}
                        onChange={e => updateItemSku(i, e.target.value.trim())} />
                      {!item.sku && (
                        <div style={{ fontSize: 10, color: '#d97706', marginTop: 2 }}>対象外としてスキップ</div>
                      )}
                    </td>
                    <td style={{ padding: '8px 12px', fontSize: 12 }}>{item.name_jp || '—'}</td>
                    <td style={{ padding: '8px 12px', textAlign: 'right' }}>{item.qty}</td>
                    <td style={{ padding: '8px 12px', textAlign: 'right' }}>{item.unit_price_cny}</td>
                    <td style={{ padding: '8px 12px', fontSize: 12 }}>{item.asin_memo || '—'}</td>
                    <td style={{ padding: '8px 12px', fontSize: 11 }}>
                      {item.buy_url ? <a href={item.buy_url} target="_blank" rel="noreferrer">リンク</a> : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ marginTop: 16, display: 'flex', alignItems: 'center', gap: 12, justifyContent: 'flex-end' }}>
            <span style={{ fontSize: 12, color: '#64748b' }}>
              {blankSkuCount > 0 ? `SKU空欄 ${blankSkuCount}件はスキップして計算します` : '全行を楽天商品として計算します'}
            </span>
            <button className="btn btn-primary" onClick={handleCalculate}>
              原価を計算へ進む
            </button>
          </div>
        </div>
      )}

      {/* 計算結果 */}
      {calculated && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <h3>計算結果</h3>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              {saved && <span style={{ color: '#16a34a', fontSize: 13 }}>保存済み（{saved.updated}件の商品マスタを更新 / {saved.skipped || 0}件スキップ）</span>}
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
            {calculated.skipped ? ` ／ スキップ: ${calculated.skipped}件` : ''}
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
                        : item.customer_memo
                          ? <span style={{ color: '#64748b', fontSize: 11 }}>{item.customer_memo}</span>
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
