import { useEffect, useState } from 'react'
import api from '../api/client'

const COL_COLORS = ['#3b82f6', '#f59e0b', '#10b981', '#ef4444', '#8b5cf6', '#ec4899']

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
  const [useTariff, setUseTariff]   = useState(true)
  // 通関料は船便のみ一律2000円（航空便は無し）。許可書に載らないので手動で選ぶ
  const [shippingMethod, setShippingMethod] = useState('sea')

  function updateItemSku(index, sku) {
    setParsed(p => {
      const items = [...p.items]
      const prod = products.find(x => x.sku === sku)
      items[index] = { ...items[index], sku, name_jp: prod?.name || items[index].name_jp }
      return { ...p, items }
    })
    setCalculated(null); setSaved(null)
  }

  function updateItemCol(index, colNo) {
    setParsed(p => {
      const items = [...p.items]
      items[index] = { ...items[index], permit_col: colNo || null }
      return { ...p, items }
    })
    setCalculated(null); setSaved(null)
  }

  function reset() {
    setValidation(null); setParsed(null); setPdfResult(null); setCalculated(null); setSaved(null)
    setForm({ invoice_no: '', invoice_date: '', exchange_rate: 20.0, domestic_freight: 0, international_freight: 0, import_tax_jpy: 0 })
  }

  // ---- ファイルを使わない取り込み ----
  // インボイスはタオタロウのAPI、許可書は保管してあるものを使う。
  // 中身は同じ形にしてあるので、このあとの計算・保存はExcel経路と同じ道を通る。
  const [filePermitId, setFilePermitId] = useState('')
  const [apiSid, setApiSid] = useState('')
  const [apiPermitId, setApiPermitId] = useState('')
  const [apiLoading, setApiLoading] = useState(false)
  const [apiInfo, setApiInfo] = useState(null)
  const [sendOrders, setSendOrders] = useState([])
  const [storedPermits, setStoredPermits] = useState([])

  useEffect(() => {
    // どちらも無ければカードは出るが選べないだけ。エラーにはしない
    api.get('/taotaro/send-orders', { params: { page: 1, limit: 20 } })
      .then(r => setSendOrders(r.data.items || [])).catch(() => {})
    api.get('/import-permits/', { params: { kind: 'permit' } })
      .then(r => setStoredPermits(r.data.items || [])).catch(() => {})
  }, [])

  async function handleApiLoad() {
    if (!apiSid || !apiPermitId) return
    setApiLoading(true)
    reset()
    setApiInfo(null)
    try {
      const invRes = await api.post('/rakuten/invoices/from-taotaro', { sid: Number(apiSid) })
      setParsed(invRes.data)
      setApiInfo(invRes.data.taotaro || null)
      if (invRes.data.shipping_method) setShippingMethod(invRes.data.shipping_method)
      try {
        const pRes = await api.get('/rakuten/products')
        setProducts(pRes.data || [])
      } catch { /* SKU候補が出ないだけなので続行 */ }

      const pdfRes = await api.get(`/rakuten/invoices/stored-permit/${apiPermitId}`)
      setPdfResult(pdfRes.data)
      setUseTariff((pdfRes.data.permit_columns || []).length > 0)
      setForm(f => ({
        ...f,
        invoice_no: invRes.data.invoice_no || '',
        domestic_freight: invRes.data.domestic_freight || 0,
        international_freight: invRes.data.international_freight || 0,
        import_tax_jpy: pdfRes.data.import_tax_jpy || 0,
        ...(pdfRes.data.exchange_rate ? { exchange_rate: pdfRes.data.exchange_rate } : {}),
      }))

      // Excel経路の「整合性チェック」と同じ確認を、こちらでも必ず出す。
      // 別の便の許可書を選ぶ事故がいちばん怖いので、金額で突き合わせる
      const invCny = (invRes.data.items || [])
        .reduce((a, i) => a + Number(i.total_price_cny || 0), 0)
      const permitCny = Number(pdfRes.data.permit_cny || 0)
      const diff = Math.round(Math.abs(invCny - permitCny) * 100) / 100
      setValidation({
        ok: permitCny > 0 ? diff <= 1 : true,
        invoice_cny: Math.round(invCny * 100) / 100,
        permit_cny: permitCny,
        diff,
        message: permitCny > 0
          ? '金額が合いません。便と許可書の組み合わせをご確認ください'
          : '許可書からCNY金額を読めなかったので、突き合わせは省略しました',
      })
    } catch (err) {
      alert('読み込みエラー: ' + (err.response?.data?.detail || err.message))
    } finally {
      setApiLoading(false)
    }
  }

  async function handleValidate() {
    if (!invoiceFile || (!permitFile && !filePermitId)) {
      alert('インボイスと輸入許可書の両方を選んでください')
      return
    }
    setValidating(true)
    reset()
    try {
      const fd1 = new FormData()
      fd1.append('invoice_file', invoiceFile)
      if (permitFile) fd1.append('permit_file', permitFile)
      else fd1.append('permit_id', filePermitId)
      const vRes = await api.post('/rakuten/invoices/validate-pair', fd1)
      setValidation(vRes.data)
      if (!vRes.data.ok) return

      const fd2 = new FormData()
      fd2.append('file', invoiceFile)
      const invRes = await api.post('/rakuten/invoices/parse-excel', fd2)
      setParsed(invRes.data)
      // シート構成から推測した配送方法を初期値にする（確実ではないので変更可）
      if (invRes.data.shipping_method) setShippingMethod(invRes.data.shipping_method)
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

      let pdfRes
      if (permitFile) {
        const fd3 = new FormData()
        fd3.append('file', permitFile)
        pdfRes = await api.post('/rakuten/invoices/parse-pdf', fd3)
      } else {
        pdfRes = await api.get(`/rakuten/invoices/stored-permit/${filePermitId}`)
      }
      setPdfResult(pdfRes.data)
      setForm(f => ({
        ...f,
        import_tax_jpy: pdfRes.data.import_tax_jpy || 0,
        ...(pdfRes.data.exchange_rate ? { exchange_rate: pdfRes.data.exchange_rate } : {}),
      }))
      setUseTariff(pdfRes.data.permit_columns?.length > 0)
    } catch (err) {
      alert('エラー: ' + (err.response?.data?.detail || err.message))
    } finally {
      setValidating(false)
    }
  }

  function buildPayload() {
    const cols = pdfResult?.permit_columns || []
    return {
      ...form,
      exchange_rate: parseFloat(form.exchange_rate),
      domestic_freight: parseFloat(form.domestic_freight || 0),
      international_freight: parseFloat(form.international_freight || 0),
      import_tax_jpy: parseFloat(form.import_tax_jpy || 0),
      items: parsed.items,
      permit_columns: useTariff ? cols : [],
      // 箱シートがあれば送料を実測重量で配る。無ければサーバ側で金額比に落ちる
      box_data: parsed.box_data || null,
      // 通関料は船便のみ一律。許可書には載らないので画面の選択から渡す
      customs_fee_jpy: shippingMethod === 'sea'
        ? (parsed.customs_fee_sea_jpy ?? 2000)
        : 0,
    }
  }

  async function handleCalculate() {
    if (!parsed) return
    try {
      const res = await api.post('/rakuten/invoices/calculate', buildPayload())
      setCalculated(res.data)
    } catch (err) {
      alert('計算エラー: ' + (err.response?.data?.detail || err.message))
    }
  }

  async function handleSave() {
    if (!calculated) return
    setSaving(true)
    try {
      const res = await api.post('/rakuten/invoices/save', buildPayload())
      setSaved(res.data)
    } catch (err) {
      const d = err.response?.data?.detail
      // 検算NGのときは detail がオブジェクトで返る。何が合わないかを出す
      if (d && typeof d === 'object' && d.failed) {
        const lines = d.failed.map(c => `・${c.name}: ${c.detail}`).join('\n')
        alert(`${d.message}\n\n${lines}\n\n原因を直してから計算し直してください。`)
      } else {
        alert('保存エラー: ' + (typeof d === 'string' ? d : err.message))
      }
    } finally {
      setSaving(false)
    }
  }

  const blankSkuCount = parsed?.items?.filter(item => !(item.sku || '').trim()).length || 0
  const matchedSkuCount = parsed?.items?.length ? parsed.items.length - blankSkuCount : 0
  const permitColumns = pdfResult?.permit_columns || []
  const hasMultipleCols = permitColumns.length > 1

  return (
    <div>
      <h2 style={{ marginBottom: 24 }}>楽天 仕入管理（原価計算）</h2>

      {/* ファイルを使わない取り込み。
          インボイスはタオタロウのAPIから、許可書は保管してあるものから選ぶ。
          Excelの経路は「箱ごとの重量で国際送料を配りたいとき」に残してある */}
      <div className="card" style={{ marginBottom: 16 }}>
        <h3 style={{ marginBottom: 6 }}>タオタロウ＋保管済みの許可書から取り込む</h3>
        <div style={{ fontSize: 12, color: '#64748b', marginBottom: 12 }}>
          ファイルの用意は要りません。便と許可書を選んで「読み込む」を押してください。
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <div className="form-group">
            <label>配送依頼（インボイスの代わり）</label>
            <select value={apiSid} onChange={e => { setApiSid(e.target.value); reset() }}
              style={{ width: '100%', padding: '6px 8px' }}>
              <option value="">選んでください</option>
              {sendOrders.map(x => (
                <option key={x.sid} value={x.sid}>
                  {x.sn || x.sid}　{x.state_label}　{x.total_send_fee}元
                  {x.count_weight ? `　${x.count_weight}kg` : ''}
                </option>
              ))}
            </select>
          </div>
          <div className="form-group">
            <label>輸入許可書（保管済み）</label>
            <select value={apiPermitId} onChange={e => { setApiPermitId(e.target.value); reset() }}
              style={{ width: '100%', padding: '6px 8px' }}>
              <option value="">選んでください</option>
              {storedPermits.map(p => (
                <option key={p.id} value={p.id}>
                  {p.permit_date || p.mail_date || '日付なし'}
                  {p.permit_no || '(番号なし)'}　¥{(p.total_tax || 0).toLocaleString()}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div style={{ marginTop: 12, display: 'flex', gap: 10, alignItems: 'center' }}>
          <button className="btn btn-primary" onClick={handleApiLoad}
            disabled={apiLoading || !apiSid || !apiPermitId}>
            {apiLoading ? '読み込み中…' : '読み込む'}
          </button>
          {storedPermits.length === 0 && (
            <span style={{ fontSize: 12, color: '#b45309' }}>
              保管された許可書がありません。「輸入許可書」の画面で先に取り込んでください
            </span>
          )}
        </div>
        {apiInfo && (
          <div style={{ marginTop: 12, fontSize: 13, color: '#475569' }}>
            <div>
              <b>{apiInfo.sn}</b>　{apiInfo.state_label}　{apiInfo.delivery_name || ''}
              {apiInfo.count_weight ? `　課金重量 ${apiInfo.count_weight}kg` : ''}
            </div>
            <div style={{ fontSize: 12, marginTop: 4 }}>
              中国国内 {apiInfo.fees?.send_price}元／代行 {apiInfo.fees?.server_fee}元／
              国際 {apiInfo.fees?.freight}元／通関 {apiInfo.fees?.customs_fee}元／
              遠隔地 {apiInfo.fees?.remote_fee}元
              <b>合計 {apiInfo.fees?.total_send_fee}元</b>
            </div>
            {/* Excelの箱シートが無いので重量按分ができない。黙って金額比にすると
                同じ便でも経路によって原価が変わるため、はっきり出す */}
            <div style={{ fontSize: 12, marginTop: 4, color: '#b45309' }}>
              ※国際送料は金額比で配ります（箱ごとの重量はAPIから取れないため）。
              重量で配りたいときは、下のExcelの経路をお使いください。
            </div>
          </div>
        )}
      </div>

      {/* ファイル選択 */}
      <div className="card" style={{ marginBottom: 16 }}>
        <h3 style={{ marginBottom: 6 }}>ファイルから取り込む（箱ごとの重量で配りたいとき）</h3>
        <div style={{ fontSize: 12, color: '#64748b', marginBottom: 12 }}>
          インボイスに箱シートが付いていれば、国際送料を実測重量で配れます。
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <div className="form-group">
            <label>インボイス（.xlsx）</label>
            <input type="file" accept=".xlsx,.xls"
              onChange={e => { setInvoiceFile(e.target.files[0]); reset() }} />
          </div>
          <div className="form-group">
            <label>輸入許可書</label>
            {/* メールから自動で貯めているので、ふだんは選ぶだけでよい。
                まだ保管されていない便のためにアップロードも残す */}
            <select value={filePermitId}
              onChange={e => { setFilePermitId(e.target.value); setPermitFile(null); reset() }}
              style={{ width: '100%', padding: '6px 8px', marginBottom: 6 }}>
              <option value="">保管済みから選ぶ…</option>
              {storedPermits.map(p => (
                <option key={p.id} value={p.id}>
                  {p.permit_date || p.mail_date || '日付なし'}　{p.permit_no || '(番号なし)'}
                  　¥{(p.total_tax || 0).toLocaleString()}
                </option>
              ))}
            </select>
            <input type="file" accept=".pdf"
              onChange={e => { setPermitFile(e.target.files[0]); setFilePermitId(''); reset() }} />
            <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 4 }}>
              保管済みを選んだときはファイルの選択は要りません
            </div>
          </div>
        </div>
        <div style={{ marginTop: 16 }}>
          <button className="btn btn-primary" onClick={handleValidate}
            disabled={validating || !invoiceFile || (!permitFile && !filePermitId)}>
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

      {/* 輸入許可書情報 + 申告欄 */}
      {pdfResult && validation?.ok && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h3 style={{ marginBottom: 12 }}>輸入許可書情報</h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, fontSize: 13 }}>
            <div><b>為替レート:</b> {pdfResult.exchange_rate}円/元</div>
            <div><b>輸入税合計（関税+消費税+地方消費税）:</b> ¥{pdfResult.import_tax_jpy?.toLocaleString()}</div>
            <div><b>申告欄数:</b> {permitColumns.length}欄</div>
          </div>

          {/* 申告欄ごとの関税率 */}
          {permitColumns.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
                <b style={{ fontSize: 13 }}>申告欄（税関分類）</b>
                {hasMultipleCols && (
                  <label style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                    <input type="checkbox" checked={useTariff}
                      onChange={e => { setUseTariff(e.target.checked); setCalculated(null); setSaved(null) }} />
                    欄ごとの税率で計算（OFF=従来の一律按分）
                  </label>
                )}
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: `repeat(${Math.min(permitColumns.length, 3)}, 1fr)`, gap: 8 }}>
                {permitColumns.map((col, i) => (
                  <div key={col.col_no} style={{
                    padding: '10px 14px', borderRadius: 6, fontSize: 12,
                    border: `2px solid ${COL_COLORS[i % COL_COLORS.length]}`,
                    background: `${COL_COLORS[i % COL_COLORS.length]}10`,
                  }}>
                    <div style={{ fontWeight: 700, marginBottom: 4, color: COL_COLORS[i % COL_COLORS.length] }}>
                      {col.col_no}欄: {col.tariff_rate_str || 'FREE'}
                    </div>
                    <div style={{ color: '#475569' }}>{col.item_name}</div>
                    <div style={{ color: '#94a3b8', marginTop: 2 }}>
                      HS: {col.hs_code} / CIF: ¥{col.cif_jpy?.toLocaleString()} / BPR: {col.bpr_coeff}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
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
                <span style={{ fontSize: 11, color: '#94a3b8', marginLeft: 6 }}>
                  {useTariff && hasMultipleCols ? '税率別計算時は参考値' : '関税+消費税+地方消費税'}
                </span>
              </label>
              <input value={form.import_tax_jpy ?? 0} type="number" step="1"
                style={{ borderColor: form.import_tax_jpy > 0 ? '#16a34a' : undefined }}
                onChange={e => setForm(f => ({ ...f, import_tax_jpy: e.target.value }))} />
            </div>
            {/* 通関料は許可書に載らないので、配送方法から決める */}
            <div className="form-group">
              <label>
                配送方法
                <span style={{ fontSize: 11, color: '#94a3b8', marginLeft: 6 }}>
                  通関料（船便のみ ¥{(parsed?.customs_fee_sea_jpy ?? 2000).toLocaleString()}）
                </span>
              </label>
              <select
                value={shippingMethod}
                onChange={e => { setShippingMethod(e.target.value); setCalculated(null); setSaved(null) }}
              >
                <option value="sea">船便（通関料 ¥{(parsed?.customs_fee_sea_jpy ?? 2000).toLocaleString()}）</option>
                <option value="air">航空便（通関料なし）</option>
              </select>
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
          {/* インボイスの商品名が英語名だけの行は、同じ便の明細から埋めている。
              勝手に決まったように見えると不安なので、何件そうしたかを出す */}
          {parsed.filled_from_taotaro > 0 && (
            <div style={{ fontSize: 12, color: '#166534', marginBottom: 6 }}>
              うち{parsed.filled_from_taotaro}件は、インボイスだけでは決められなかったため
              同じ便のタオタロウ明細から当てました（商品名の右に「便の明細から」と出ます）。
              念のためご確認ください。
            </div>
          )}
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
                  {useTariff && hasMultipleCols && (
                    <th style={{ padding: '8px 12px', textAlign: 'center' }}>申告欄</th>
                  )}
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
                    {useTariff && hasMultipleCols && (
                      <td style={{ padding: '4px 8px', textAlign: 'center' }}>
                        <select value={item.permit_col || ''}
                          style={{ fontSize: 11, padding: '2px 4px', borderRadius: 4,
                                   border: '1px solid #cbd5e1', background: '#fff', minWidth: 60 }}
                          onChange={e => updateItemCol(i, e.target.value ? parseInt(e.target.value) : null)}>
                          <option value="">自動</option>
                          {permitColumns.map(c => (
                            <option key={c.col_no} value={c.col_no}>{c.col_no}欄 ({c.tariff_rate_str})</option>
                          ))}
                        </select>
                      </td>
                    )}
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
            <div>
              <h3 style={{ display: 'inline' }}>計算結果</h3>
              {calculated.use_tariff && (
                <span style={{ marginLeft: 12, fontSize: 12, background: '#dbeafe', color: '#1e40af',
                               padding: '2px 8px', borderRadius: 4, fontWeight: 600 }}>
                  税率別計算
                </span>
              )}
              {!calculated.use_tariff && hasMultipleCols && (
                <span style={{ marginLeft: 12, fontSize: 12, background: '#fef3c7', color: '#92400e',
                               padding: '2px 8px', borderRadius: 4, fontWeight: 600 }}>
                  一律按分（従来方式）
                </span>
              )}
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              {saved && (
                <span style={{ color: '#16a34a', fontSize: 13 }}>
                  保存済み（{saved.updated}件の商品マスタを更新 / {saved.skipped || 0}件スキップ）
                </span>
              )}
              <button className="btn btn-primary" onClick={handleSave} disabled={saving || !!saved}>
                {saving ? '保存中...' : '楽天商品マスタに反映して保存'}
              </button>
            </div>
          </div>
          <div style={{ marginBottom: 12, fontSize: 13, color: '#555' }}>
            仕入合計: {calculated.total_cny?.toLocaleString()}元 ／
            送料合計: {calculated.total_freight_cny?.toLocaleString()}元 ／
            輸入税: ¥{(calculated.import_tax_jpy || 0).toLocaleString()} ／
            通関料: ¥{(calculated.customs_fee_jpy || 0).toLocaleString()} ／
            総原価: ¥{calculated.grand_total_jpy?.toLocaleString()}
            {calculated.skipped ? ` ／ スキップ: ${calculated.skipped}件` : ''}
          </div>

          {/* 送料の配り方。黙って金額比に落ちているのが一番危ないので必ず出す */}
          {calculated.freight_method && (
            <div style={{
              marginBottom: 12, padding: '8px 14px', borderRadius: 6, fontSize: 13,
              background: calculated.freight_method.fallback ? '#fffbeb' : '#f0fdf4',
              border: `1px solid ${calculated.freight_method.fallback ? '#fcd34d' : '#86efac'}`,
              color: calculated.freight_method.fallback ? '#92400e' : '#166534',
            }}>
              {calculated.freight_method.fallback ? '⚠' : '✓'} 送料の配分: {calculated.freight_method.reason}
              {calculated.freight_method.fallback && (
                <div style={{ marginTop: 4, fontSize: 12 }}>
                  金額比だと、安くて嵩張るものが送料をほとんど負担しません。
                  箱シート（箱规・箱单）付きのインボイスなら実測重量で配れます。
                </div>
              )}
            </div>
          )}

          {/* 検算。総額が合っていても配り方が偏っていることはあるので、
              配り切れたか・どこへ配ったかを毎回チェックする。
              NGのまま保存すると誤った原価が値付けに使われるため保存を止める */}
          {calculated.verification && (() => {
            const v = calculated.verification
            const ngs = v.checks.filter(c => !c.ok)
            if (v.ok && ngs.length === 0) {
              return (
                <div style={{
                  marginBottom: 12, padding: '8px 14px', borderRadius: 6, fontSize: 13,
                  background: '#f0fdf4', border: '1px solid #86efac', color: '#166534',
                }}>
                  ✓ 検算 {v.checks.length}項目すべて一致（送料・税を配り切れています）
                </div>
              )
            }
            return (
              <div style={{
                marginBottom: 12, padding: '10px 14px', borderRadius: 6, fontSize: 13,
                background: v.ok ? '#fffbeb' : '#fef2f2',
                border: `1px solid ${v.ok ? '#fcd34d' : '#fca5a5'}`,
                color: v.ok ? '#92400e' : '#991b1b',
              }}>
                <b>{v.ok ? '⚠ 検算に警告があります' : '✕ 検算NG — このままでは保存できません'}</b>
                <div style={{ marginTop: 6 }}>
                  {ngs.map((c, i) => (
                    <div key={i} style={{ marginTop: 3, fontSize: 12 }}>
                      ・<b>{c.name}</b>: {c.detail}
                    </div>
                  ))}
                </div>
                {!v.ok && (
                  <div style={{ marginTop: 6, fontSize: 12 }}>
                    誤った原価が値付け・発注判断に使われるのを防ぐため保存を止めています。
                    原因を直してから計算し直してください。
                  </div>
                )}
              </div>
            )
          })()}

          {/* 未登録の明細があると、その分の送料・税がどの原価にもならず消える。
              新しい発送資材を登録し忘れたときもここで気づけるようにする */}
          {calculated.coverage && calculated.coverage.unknown_count > 0 && (
            <div style={{
              marginBottom: 12, padding: '10px 14px', borderRadius: 6, fontSize: 13,
              background: calculated.coverage.level === 'critical' ? '#fef2f2' : '#fffbeb',
              border: `1px solid ${calculated.coverage.level === 'critical' ? '#fca5a5' : '#fcd34d'}`,
              color: calculated.coverage.level === 'critical' ? '#991b1b' : '#92400e',
            }}>
              <b>⚠ 商品マスタに無い明細が {calculated.coverage.unknown_count} 件あります</b>
              （カバー率 {calculated.coverage.coverage_rate}%）
              <div style={{ marginTop: 4, fontSize: 12 }}>
                未登録の明細に按分された送料・輸入税は、どの商品の原価にもなりません。
                発送資材（宅配袋など）の場合は、商品マスタに登録して
                「発送資材」にチェックを入れると資材費として計上されます。
              </div>
              {calculated.coverage.unknown_indexes?.length > 0 && (
                <div style={{ marginTop: 6, fontSize: 12 }}>
                  該当行: {calculated.coverage.unknown_indexes.map(i => {
                    const it = parsed?.items?.[i]
                    return it ? (it.name_jp || it.sku || `${i + 1}行目`) : `${i + 1}行目`
                  }).join(' / ')}
                </div>
              )}
            </div>
          )}

          {calculated.materials?.length > 0 && (
            <div style={{
              marginBottom: 12, padding: '10px 14px', borderRadius: 6, fontSize: 13,
              background: '#eff6ff', border: '1px solid #bfdbfe', color: '#1e40af',
            }}>
              <b>📦 発送資材 {calculated.materials.length} 件</b>
              （合計 ¥{(calculated.material_total_jpy || 0).toLocaleString()}）
              <div style={{ marginTop: 4, fontSize: 12 }}>
                商品原価には含めず、資材費として月次で集計します。
              </div>
              <div style={{ marginTop: 6, fontSize: 12 }}>
                {calculated.materials.map(m => `${m.name || m.sku}（¥${Math.round(m.total_cost_jpy).toLocaleString()}）`).join(' / ')}
              </div>
            </div>
          )}
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ background: '#f0f2f8', borderBottom: '2px solid #e2e8f0' }}>
                  {[
                    'SKU', '品名', '商品内訳', '数量', '単価(元)', '小計(元)', '按分送料(元)',
                    ...(calculated.use_tariff ? ['欄', '税率', '関税(円)'] : []),
                    '按分税(円)', '1個原価(円)',
                  ].map(h => (
                    <th key={h} style={{ padding: '8px 12px', textAlign: ['SKU', '品名', '商品内訳', '欄'].includes(h) ? 'left' : 'right', whiteSpace: 'nowrap' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {calculated.items.map((item, i) => {
                  const isLinked = !!item.matched_sku
                  const colIdx = item.col_no ? permitColumns.findIndex(c => c.col_no === item.col_no) : -1
                  const colColor = colIdx >= 0 ? COL_COLORS[colIdx % COL_COLORS.length] : '#94a3b8'
                  return (
                    <tr key={i} style={{ borderBottom: '1px solid #e5e7eb', background: isLinked ? '#f0fdf4' : item.asin_memo ? '#fffbeb' : undefined }}>
                      <td style={{ padding: '8px 12px', fontFamily: 'monospace', fontSize: 12 }}>{item.sku}</td>
                      <td style={{ padding: '8px 12px', fontSize: 12 }}>{item.name_jp || '—'}</td>
                      <td style={{ padding: '8px 12px', fontSize: 12 }}>
                        {item.asin_memo
                          ? isLinked
                            ? <span style={{ background: '#dcfce7', border: '1px solid #22c55e', color: '#166534', borderRadius: 4, padding: '2px 6px', fontSize: 11, fontWeight: 700 }}>紐づき {item.asin_memo}</span>
                            : <span style={{ background: '#fef08a', border: '1px solid #ca8a04', borderRadius: 4, padding: '2px 6px', fontSize: 11, fontWeight: 600 }}>注意 {item.asin_memo}</span>
                          : item.customer_memo
                            ? <span style={{ color: '#64748b', fontSize: 11 }}>{item.customer_memo}</span>
                            : '—'}
                      </td>
                      <td style={{ padding: '8px 12px', textAlign: 'right' }}>{item.qty}</td>
                      <td style={{ padding: '8px 12px', textAlign: 'right' }}>{item.unit_price_cny}</td>
                      <td style={{ padding: '8px 12px', textAlign: 'right' }}>{item.total_price_cny}</td>
                      <td style={{ padding: '8px 12px', textAlign: 'right' }}>{item.freight_alloc_cny}</td>
                      {calculated.use_tariff && (
                        <>
                          <td style={{ padding: '8px 6px', fontSize: 11 }}>
                            {item.col_no != null && (
                              <span style={{ background: `${colColor}18`, color: colColor, border: `1px solid ${colColor}`,
                                             borderRadius: 4, padding: '1px 6px', fontWeight: 600, whiteSpace: 'nowrap' }}>
                                {item.col_no}欄
                              </span>
                            )}
                          </td>
                          <td style={{ padding: '8px 12px', textAlign: 'right', fontWeight: 600, color: colColor }}>
                            {item.tariff_rate_str || '—'}
                          </td>
                          <td style={{ padding: '8px 12px', textAlign: 'right' }}>
                            {item.duty_jpy != null ? `¥${item.duty_jpy.toLocaleString()}` : '—'}
                          </td>
                        </>
                      )}
                      <td style={{ padding: '8px 12px', textAlign: 'right', color: '#7c3aed' }}>
                        {item.tax_alloc_jpy ? `¥${item.tax_alloc_jpy.toLocaleString()}` : '—'}
                      </td>
                      <td style={{ padding: '8px 12px', textAlign: 'right', color: '#e94560', fontWeight: 700 }}>
                        ¥{item.cost_jpy?.toLocaleString()}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
