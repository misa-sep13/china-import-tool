import { useState, useEffect } from 'react'
import axios from 'axios'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000/api'

export default function InvoicePage() {
  const [tab, setTab] = useState('list')

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>仕入管理（原価計算）</h2>
      <div style={{ display: 'flex', borderBottom: '1px solid #ddd', marginBottom: 24 }}>
        {[
          ['list',    '一覧'],
          ['invoice', 'インボイス＋輸入許可書を登録'],
        ].map(([key, label]) => (
          <button key={key} onClick={() => setTab(key)} style={{
            padding: '8px 20px', cursor: 'pointer', background: 'none', border: 'none',
            borderBottom: tab === key ? '2px solid #3b82f6' : '2px solid transparent',
            fontWeight: tab === key ? 700 : 400,
            color: tab === key ? '#3b82f6' : '#555',
            fontSize: 14,
          }}>{label}</button>
        ))}
      </div>

      {tab === 'list'    && <InvoiceList />}
      {tab === 'invoice' && <InvoiceTab />}
    </div>
  )
}

/* ===================== 一覧 ===================== */
function InvoiceList() {
  const [invoices, setInvoices] = useState([])
  const [detail, setDetail] = useState(null)
  const [detailItems, setDetailItems] = useState([])

  useEffect(() => {
    axios.get(`${API}/invoices/`).then(r => setInvoices(r.data))
  }, [])

  async function showDetail(inv) {
    setDetail(inv)
    const res = await axios.get(`${API}/invoices/${inv.id}/items`)
    setDetailItems(res.data)
  }

  if (detail) return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <button className="btn-secondary" onClick={() => setDetail(null)}>一覧に戻る</button>
        <h3 style={{ margin: 0 }}>{detail.invoice_no}</h3>
        <span style={{ fontSize: 13, color: '#888' }}>{detail.invoice_date} ／ 為替: {detail.exchange_rate}円/元</span>
      </div>
      {detail.total_tax > 0 && (
        <div className="card" style={{ marginBottom: 16, fontSize: 13 }}>
          <b>輸入許可書情報　</b>
          関税: ¥{detail.customs_duty?.toLocaleString()} ／
          消費税: ¥{detail.consumption_tax?.toLocaleString()} ／
          地方消費税: ¥{detail.local_consumption_tax?.toLocaleString()} ／
          納税合計: ¥{detail.total_tax?.toLocaleString()}
          {detail.bl_number && <span>　B/L: {detail.bl_number}</span>}
        </div>
      )}
      <table>
        <thead>
          <tr>
            <th>TAO SKU</th><th>品名</th>
            <th style={{ textAlign: 'right' }}>数量</th>
            <th style={{ textAlign: 'right' }}>単価(元)</th>
            <th style={{ textAlign: 'right', color: '#e94560' }}>1個原価(円)</th>
          </tr>
        </thead>
        <tbody>
          {detailItems.map((item, i) => (
            <tr key={i}>
              <td style={{ fontFamily: 'monospace', fontSize: 12 }}>{item.sku}</td>
              <td style={{ fontSize: 12 }}>{item.name_jp || item.name_cn}</td>
              <td style={{ textAlign: 'right' }}>{item.qty}</td>
              <td style={{ textAlign: 'right' }}>{item.unit_price_cny}</td>
              <td style={{ textAlign: 'right', color: '#e94560', fontWeight: 700 }}>¥{item.cost_per_unit_jpy?.toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )

  return invoices.length === 0
    ? <p style={{ color: '#888' }}>まだインボイスがありません。</p>
    : (
      <table>
        <thead>
          <tr>
            <th>インボイス番号</th><th>仕入日</th>
            <th style={{ textAlign: 'right' }}>為替(円/元)</th>
            <th style={{ textAlign: 'right' }}>納税合計</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {invoices.map(inv => (
            <tr key={inv.id}>
              <td style={{ fontFamily: 'monospace', fontSize: 12 }}>{inv.invoice_no}</td>
              <td style={{ fontSize: 12 }}>{inv.invoice_date}</td>
              <td style={{ textAlign: 'right', fontSize: 12 }}>{inv.exchange_rate}円</td>
              <td style={{ textAlign: 'right', fontSize: 12 }}>
                {inv.total_tax ? `¥${inv.total_tax?.toLocaleString()}` : '—'}
              </td>
              <td><button className="btn-secondary" style={{ fontSize: 12, padding: '3px 8px' }} onClick={() => showDetail(inv)}>詳細</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    )
}

/* ===================== インボイス＋輸入許可書登録 ===================== */
function InvoiceTab() {
  const [invoiceFile, setInvoiceFile] = useState(null)
  const [permitFile, setPermitFile] = useState(null)
  const [validating, setValidating] = useState(false)
  const [validation, setValidation] = useState(null)
  const [parsed, setParsed] = useState(null)
  const [permit, setPermit] = useState(null)
  const [form, setForm] = useState({ invoice_date: '', exchange_rate: '' })
  const [calculated, setCalculated] = useState(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(null)

  async function handleValidate() {
    if (!invoiceFile || !permitFile) {
      alert('インボイスと輸入許可書の両方を選択してください')
      return
    }
    setValidating(true)
    setValidation(null); setParsed(null); setPermit(null); setCalculated(null); setSaved(null)
    try {
      const fd1 = new FormData()
      fd1.append('invoice_file', invoiceFile)
      fd1.append('permit_file', permitFile)
      const vRes = await axios.post(`${API}/invoices/validate-pair`, fd1)
      setValidation(vRes.data)
      if (!vRes.data.ok) return

      const fd2 = new FormData()
      fd2.append('file', invoiceFile)
      const invRes = await axios.post(`${API}/invoices/parse-excel`, fd2)
      setParsed(invRes.data)
      setForm(f => ({
        ...f,
        invoice_no: invRes.data.invoice_no,
        domestic_freight: invRes.data.domestic_freight,
        international_freight: invRes.data.international_freight,
        total_weight: invRes.data.total_weight,
        total_volume: invRes.data.total_volume,
      }))

      const fd3 = new FormData()
      fd3.append('file', permitFile)
      const permitRes = await axios.post(`${API}/invoices/parse-import-permit`, fd3)
      setPermit(permitRes.data)
      if (permitRes.data.exchange_rate > 0) {
        setForm(f => ({ ...f, exchange_rate: permitRes.data.exchange_rate }))
      }
    } catch (e) {
      alert('エラー: ' + (e.response?.data?.detail || e.message))
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
        customs_duty: permit?.customs_duty || 0,
        consumption_tax: permit?.consumption_tax || 0,
        local_consumption_tax: permit?.local_consumption_tax || 0,
        total_tax: permit?.total_tax || 0,
        bl_number: permit?.bl_number || '',
        declaration_no: permit?.declaration_no || '',
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
      <div className="card" style={{ marginBottom: 16 }}>
        <h3 style={{ marginBottom: 16 }}>ファイル選択（2つセットでアップロード）</h3>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <div className="form-group">
            <label>インボイス（.xlsx）</label>
            <input type="file" accept=".xlsx,.xls"
              onChange={e => { setInvoiceFile(e.target.files[0]); setValidation(null); setParsed(null) }} />
          </div>
          <div className="form-group">
            <label>輸入許可書（.pdf）</label>
            <input type="file" accept=".pdf"
              onChange={e => { setPermitFile(e.target.files[0]); setValidation(null); setParsed(null) }} />
          </div>
        </div>
        <div style={{ marginTop: 16 }}>
          <button className="btn-primary" onClick={handleValidate}
            disabled={validating || !invoiceFile || !permitFile}>
            {validating ? '照合中...' : '整合性チェック＆読み込み'}
          </button>
        </div>
      </div>

      {validation && (
        <div className="card" style={{ marginBottom: 16, borderLeft: `4px solid ${validation.ok ? '#22c55e' : '#e94560'}` }}>
          <div style={{ fontWeight: 700, color: validation.ok ? '#166534' : '#e94560' }}>
            {validation.ok ? '照合OK — 同じ便のファイルです' : '照合NG — ファイルが対応していません'}
          </div>
          <div style={{ fontSize: 13, marginTop: 4, color: '#555' }}>
            インボイスCNY合計: {validation.invoice_cny}元　／　輸入許可書CNY: {validation.permit_cny}元　／　差額: {validation.diff}元
          </div>
          {!validation.ok && <div style={{ fontSize: 13, color: '#e94560', marginTop: 4 }}>{validation.message}</div>}
        </div>
      )}

      {permit && validation?.ok && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h3 style={{ marginBottom: 12 }}>輸入許可書情報</h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, fontSize: 13 }}>
            <div><b>為替レート:</b> {permit.exchange_rate}円/元</div>
            <div><b>関税:</b> ¥{permit.customs_duty?.toLocaleString()}</div>
            <div><b>消費税:</b> ¥{permit.consumption_tax?.toLocaleString()}</div>
            <div><b>地方消費税:</b> ¥{permit.local_consumption_tax?.toLocaleString()}</div>
            <div><b>納税合計:</b> ¥{permit.total_tax?.toLocaleString()}</div>
            <div><b>B/L番号:</b> {permit.bl_number}</div>
            <div style={{ gridColumn: 'span 2' }}><b>申告番号:</b> {permit.declaration_no}</div>
          </div>
        </div>
      )}

      {parsed && validation?.ok && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h3 style={{ marginBottom: 16 }}>基本情報</h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
            {[
              ['インボイス番号', 'invoice_no', 'text'],
              ['仕入日', 'invoice_date', 'text'],
              ['為替レート（円/元）', 'exchange_rate', 'number'],
              ['国内運費（元）', 'domestic_freight', 'number'],
              ['国際運費（元）', 'international_freight', 'number'],
              ['総重量（kg）', 'total_weight', 'number'],
              ['総容積（m3）', 'total_volume', 'number'],
            ].map(([label, key, type]) => (
              <div key={key} className="form-group">
                <label>{label}</label>
                <input value={form[key] ?? ''} type={type} step="0.01"
                  onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))} />
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
              {saved && <span style={{ color: 'green', fontSize: 13 }}>保存済み（{saved.updated_products}件更新）</span>}
              <button className="btn-primary" onClick={handleSave} disabled={saving || !!saved}>
                {saving ? '保存中...' : '商品マスタに反映して保存'}
              </button>
            </div>
          </div>
          <div style={{ marginBottom: 12, fontSize: 13, color: '#555' }}>
            合計数量: {calculated.total_qty}個 ／ 仕入合計: {calculated.total_cny}元 ／
            送料合計: {calculated.total_freight_cny}元 ／ 総原価: ¥{calculated.grand_total_jpy?.toLocaleString()}
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th>TAO SKU</th><th>品名</th>
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
                    <td style={{ textAlign: 'right', color: '#e94560', fontWeight: 'bold' }}>¥{item.cost_per_unit_jpy?.toLocaleString()}</td>
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
