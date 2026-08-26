import { useState, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'
import { normalizeSearch } from '../searchUtil'

const EMPTY = {
  sku: '', name: '', jan_code: '', spec: '', buy_url: '', price: '',
  set_size: 1, supplier_spec: '', rakuten_item_url: '', rakuten_sku_id: '', supplier: '',
  standard_stock: 0, stock: 0, inbound: 0,
  sales_30_recent: 0, sales_30_prev: 0,
  cost_jpy: null, selling_price: null, shipping_fee: 180,
  customer_memo: '', notes: '', memo: '',
  set_components: '', purchase_components: '', is_component: false, is_material: false, is_promo: false, is_active: true,
  packing_set_qty: null, packing_unit_price: null, packing_material: '', packing_method: '',
}

const BASE_URL = api.defaults.baseURL || ''

export default function RakutenProductsPage() {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState(EMPTY)
  const [search, setSearch] = useState('')
  const [supplierFilter, setSupplierFilter] = useState('')
  const [showComponents, setShowComponents] = useState(false)
  const [importResult, setImportResult] = useState(null)
  const [importing, setImporting] = useState(false)
  const [syncingPrices, setSyncingPrices] = useState(false)
  const [syncPriceResult, setSyncPriceResult] = useState(null)
  const [compTab, setCompTab] = useState({})  // {id: bool} セット構成展開
  const fileRef = useRef(null)

  const { data: products = [], isLoading } = useQuery({
    queryKey: ['rakuten-products'],
    queryFn: () => api.get('/rakuten/products').then(r => r.data),
  })

  const { data: settings } = useQuery({
    queryKey: ['rakuten-settings'],
    queryFn: () => api.get('/rakuten/settings').then(r => r.data),
  })
  const commissionRate = settings?.commission_rate ?? 0.09

  // タオタロウ取り込みで読めない仕様形式を検出する。
  // 正しい形式: 1688の選択肢の「値」を属性の表示順に「、」で区切る（例: 燕麦色、S 建议75-95斤）
  const specFormatWarning = (spec) => {
    const s = (spec || '').trim()
    if (!s) return null
    if (/握笔器六代【(?:蓝色|粉色)彩盒装】/.test(s)) {
      return '1688側の実選択肢は青が「握笔器第六代」、ピンクが「握笔器六代代」です。「六代」だけに直すとタオタロウで読めない可能性があります。無規格は発注Excel出力時に自動で補います'
    }
    if (/[；;]/.test(s) || /(颜色|规格|尺码|款式)[：:]/.test(s)) {
      return '「颜色：」などのラベルや「；」はタオタロウで読み込めません。選択肢の値だけを表示順に「、」で区切ってください（例: 燕麦色、S 建议75-95斤）'
    }
    return null
  }

  const saveMutation = useMutation({
    mutationFn: (d) => editing === 'new'
      ? api.post('/rakuten/products', d)
      : api.put(`/rakuten/products/${editing.id}`, d),
    onSuccess: () => {
      qc.invalidateQueries(['rakuten-products'])
      qc.invalidateQueries(['rakuten-stock'])
      qc.invalidateQueries(['rakuten-recommendations'])
      setEditing(null)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id) => api.delete(`/rakuten/products/${id}`),
    onSuccess: () => {
      qc.invalidateQueries(['rakuten-products'])
      qc.invalidateQueries(['rakuten-stock'])
      qc.invalidateQueries(['rakuten-recommendations'])
    },
  })

  const [syncingSkuMap, setSyncingSkuMap] = useState(false)
  const [syncSkuMapResult, setSyncSkuMapResult] = useState(null)

  const handleSyncSkuMapping = async () => {
    if (!window.confirm('RMSから商品管理番号・SKU番号を一括取得してDBに保存します。よろしいですか？')) return
    setSyncingSkuMap(true)
    setSyncSkuMapResult(null)
    try {
      const res = await api.post('/rakuten/rms/sync-sku-mapping')
      setSyncSkuMapResult(res.data)
      qc.invalidateQueries(['rakuten-products'])
    } catch (err) {
      setSyncSkuMapResult({ error: err.response?.data?.detail || 'エラーが発生しました' })
    } finally {
      setSyncingSkuMap(false)
    }
  }

  const [initialForm, setInitialForm] = useState(null)

  const openNew = () => { setForm(EMPTY); setInitialForm(EMPTY); setEditing('new') }
  const openEdit = (p) => { setForm({ ...p }); setInitialForm({ ...p }); setEditing(p) }

  const trySave = () => {
    const warn = specFormatWarning(form.supplier_spec)
    if (warn && !window.confirm('⚠ 仕様（中国語）の形式警告\n' + warn + '\n\nこのまま保存しますか？')) return
    saveMutation.mutate(form)
  }

  const handleModalClose = () => {
    const isDirty = JSON.stringify(form) !== JSON.stringify(initialForm)
    if (isDirty) {
      if (window.confirm('変更が保存されていません。保存しますか？')) {
        trySave()
      } else {
        setEditing(null)
      }
    } else {
      setEditing(null)
    }
  }

  const f = (k, type = 'text') => ({
    value: form[k] ?? '',
    onChange: e => setForm(prev => ({ ...prev, [k]: type === 'number' ? Number(e.target.value) : e.target.value }))
  })

  const handleSyncPrices = async () => {
    if (!window.confirm('RMS APIから売価を取得して更新します。よろしいですか？')) return
    setSyncingPrices(true)
    setSyncPriceResult(null)
    try {
      const res = await api.post('/rakuten/rms/sync-prices')
      // statusエンドポイントがある場合はポーリング、ない場合は即完了扱い
      if (res.data?.message?.includes('バックグラウンド')) {
        for (let i = 0; i < 60; i++) {
          await new Promise(r => setTimeout(r, 2000))
          try {
            const status = await api.get('/rakuten/rms/sync-prices/status')
            if (!status.data.running && status.data.result) {
              setSyncPriceResult(status.data.result)
              qc.invalidateQueries(['rakuten-products'])
              return
            }
          } catch { /* statusエンドポイントがない古いバージョンは無視 */ }
        }
        setSyncPriceResult({ error: 'タイムアウト' })
      } else {
        setSyncPriceResult(res.data)
        qc.invalidateQueries(['rakuten-products'])
      }
    } catch (err) {
      setSyncPriceResult({ error: err.response?.data?.detail || '売価同期エラーが発生しました' })
    } finally {
      setSyncingPrices(false)
    }
  }

  const handleImport = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setImporting(true)
    setImportResult(null)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await api.post('/rakuten/products/csv/import', fd, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      setImportResult(res.data)
      qc.invalidateQueries(['rakuten-products'])
      qc.invalidateQueries(['rakuten-stock'])
      qc.invalidateQueries(['rakuten-recommendations'])
    } catch (err) {
      setImportResult({ error: err.response?.data?.detail || 'インポートエラーが発生しました' })
    } finally {
      setImporting(false)
      e.target.value = ''
    }
  }

  // セット構成をパース
  const parseComponents = (json) => {
    try { return JSON.parse(json || '[]') } catch { return [] }
  }

  // 内部管理SKU（is_component=True）: 袋・パーツ等、一覧非表示
  const internalSkus = new Set(products.filter(p => p.is_component).map(p => p.sku))

  const parseComps = (p) => { try { return JSON.parse(p.set_components || '[]') } catch { return [] } }
  const compSkus = (p) => parseComps(p).map(c => c.sku).filter(Boolean)

  // set_componentsを持ち、かつ中身が全て内部管理SKU → セット販売商品（親として表示）
  const isSetParent = (p) => {
    if (p.is_component) return false
    const skus = compSkus(p)
    return skus.length > 0 && skus.every(s => internalSkus.has(s))
  }

  // set_componentsを持ち、中身に通常SKU（非内部）が含まれる → バリエーション子商品
  const isVariantChild = (p) => {
    if (p.is_component) return false
    return compSkus(p).some(s => !internalSkus.has(s))
  }

  // バリエーション子から参照されている親SKU集合（y76_black等）
  const variantParentSkus = new Set(
    products.filter(isVariantChild).flatMap(p => compSkus(p).filter(s => !internalSkus.has(s)))
  )

  // バリエーション親の子一覧
  const getVariantChildren = (sku) =>
    products.filter(p => isVariantChild(p) && compSkus(p).includes(sku))

  // 親の子一覧（セット販売 or バリエーション）
  const getChildren = (p) => {
    if (isSetParent(p)) return products.filter(c => internalSkus.has(c.sku) && compSkus(p).includes(c.sku))
    return getVariantChildren(p.sku)
  }

  // 分類
  const singles  = products.filter(p => p.is_component)
  // parents = バリエーション親のみ（内部管理SKUのみのセット親は展開不要なのでstandaloneへ）
  const parents  = products.filter(p =>
    !p.is_component && variantParentSkus.has(p.sku)
  )
  const standalone = products.filter(p =>
    !p.is_component && !variantParentSkus.has(p.sku) && !isVariantChild(p)
  )

  const suppliers = [...new Set(products.map(p => p.supplier).filter(Boolean))].sort()

  const searchMatch = (p) => {
    if (supplierFilter && (p.supplier || '') !== supplierFilter) return false
    if (!search) return true
    const q = normalizeSearch(search)
    return (
      normalizeSearch(p.sku).includes(q) ||
      normalizeSearch(p.name).includes(q) ||
      (p.jan_code || '').includes(search) ||
      normalizeSearch(p.rakuten_sku_id).includes(q) ||
      normalizeSearch(p.rakuten_item_url || '').includes(q)
    )
  }

  const filteredSingles    = singles.filter(searchMatch)
  const filteredParents    = parents.filter(searchMatch)
  const filteredStandalone = standalone.filter(searchMatch)

  if (isLoading) return <div className="loading">読み込み中...</div>

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24, flexWrap: 'wrap' }}>
        <h1>🛒 楽天 商品マスタ</h1>
        <button className="btn btn-primary" onClick={openNew}>+ 商品追加</button>
        <a href={`${BASE_URL}/rakuten/products/csv/template`} download className="btn" style={{ fontSize: 13, textDecoration: 'none' }}>
          📥 CSVテンプレート
        </a>
        <button className="btn" style={{ fontSize: 13 }} onClick={() => fileRef.current?.click()} disabled={importing}>
          {importing ? '取り込み中...' : '📤 CSVインポート'}
        </button>
        <input ref={fileRef} type="file" accept=".csv" style={{ display: 'none' }} onChange={handleImport} />
        <a href={`${BASE_URL}/rakuten/products/csv/export`} download className="btn" style={{ fontSize: 13, textDecoration: 'none' }}>
          📊 CSV書き出し
        </a>
        <button className="btn" style={{ fontSize: 13 }} onClick={handleSyncPrices} disabled={syncingPrices}>
          {syncingPrices ? '取得中...' : '💰 売価同期(RMS)'}
        </button>
        {syncPriceResult && (
          <span style={{ fontSize: 12, color: syncPriceResult.error ? '#e53e3e' : '#38a169' }}>
            {syncPriceResult.error || `${syncPriceResult.updated_products}件更新`}
          </span>
        )}
        <button className="btn" style={{ fontSize: 13 }} onClick={handleSyncSkuMapping} disabled={syncingSkuMap}>
          {syncingSkuMap ? '取得中...' : '🔗 管理番号同期(RMS)'}
        </button>
        {syncSkuMapResult && (
          <span style={{ fontSize: 12, color: syncSkuMapResult.error ? '#e53e3e' : '#38a169' }}>
            {syncSkuMapResult.error || `${syncSkuMapResult.updated}件更新`}
          </span>
        )}
      </div>

      {importResult && (
        <div style={{
          background: importResult.error ? '#2d1b1b' : '#1b2d1b',
          border: `1px solid ${importResult.error ? '#f87171' : '#4ade80'}`,
          borderRadius: 8, padding: '12px 16px', marginBottom: 16, fontSize: 13,
        }}>
          {importResult.error ? (
            <span style={{ color: '#f87171' }}>❌ {importResult.error}</span>
          ) : (
            <div>
              <span style={{ color: '#4ade80', fontWeight: 700 }}>
                ✅ 新規追加: {importResult.created}件　更新: {importResult.updated}件　スキップ: {importResult.skipped}件
              </span>
              {importResult.errors?.length > 0 && (
                <ul style={{ color: '#fcd34d', margin: '8px 0 0', paddingLeft: 16 }}>
                  {importResult.errors.map((e, i) => <li key={i}>{e}</li>)}
                </ul>
              )}
            </div>
          )}
        </div>
      )}

      {/* 検索 */}
      <div className="card" style={{ padding: '12px 16px', marginBottom: 16, display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <input
          type="text" placeholder="SKU・商品名・JANコード・楽天SKU・管理番号で絞り込み"
          className="search-input-ja"
          value={search} onChange={e => setSearch(e.target.value)}
          style={{ width: 260, flex: '0 0 260px' }}
        />
        <select value={supplierFilter} onChange={e => setSupplierFilter(e.target.value)} style={{ width: 160, flex: '0 0 160px' }}>
          <option value="">仕入れ先: すべて</option>
          {suppliers.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <label style={{ fontSize: 12, color: '#6b7280', display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
          <input type="checkbox" checked={showComponents} onChange={e => setShowComponents(e.target.checked)} style={{ width: 'auto' }} />
          内部管理SKUを表示（{filteredSingles.length}件）
        </label>
        <span style={{ fontSize: 12, color: '#6b7280' }}>
          通常商品 {filteredStandalone.length}件 / バリエーション親 {filteredParents.length}件
        </span>
      </div>

      {/* 商品テーブル */}
      <div className="card" style={{ padding: 0 }}>
        <div className="sticky-table-wrap">
          <table className="sticky-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ background: '#f0f2f8', borderBottom: '2px solid #e2e8f0' }}>
                {[
                  ['SKU管理番号', null], ['商品名 / 仕様', null], ['お客様専用メモ', 90],
                  ['仕入原価(円)', null], ['販売価格(円)', null], ['手数料率', null],
                  ['利益額', null], ['利益率', null], ['備考', 90], ['操作', null]
                ].map(([h, w]) => (
                  <th key={h} style={{ padding: '10px 12px', textAlign: 'center', color: '#333', whiteSpace: 'nowrap', fontWeight: 700, ...(w ? { width: w, maxWidth: w } : {}) }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filteredParents.length === 0 && filteredStandalone.length === 0 && (!showComponents || filteredSingles.length === 0) && (
                <tr><td colSpan={10} style={{ textAlign: 'center', padding: 32, color: '#999' }}>商品がありません</td></tr>
              )}

            {/* ① バリエーション親（単品）→ クリックでセット商品を展開 */}
            {filteredParents.map(p => {
              const expanded = !!compTab[p.id]
              const children = getChildren(p)
              return (
                <ProductRow
                  key={p.id}
                  p={p}
                  commissionRate={commissionRate}
                  expanded={expanded}
                  childCount={children.length}
                  onToggle={() => setCompTab(prev => ({ ...prev, [p.id]: !prev[p.id] }))}
                  onEdit={openEdit}
                  onDelete={(p) => { if (confirm(`${p.name || p.sku} を削除しますか？`)) deleteMutation.mutate(p.id) }}
                  isSingle={true}
                >
                  {expanded && children.map(child => (
                    <ProductRow
                      key={child.id}
                      p={child}
                      commissionRate={commissionRate}
                      onEdit={openEdit}
                      onDelete={(p) => { if (confirm(`${p.name || p.sku} を削除しますか？`)) deleteMutation.mutate(p.id) }}
                      isChild={true}
                    />
                  ))}
                </ProductRow>
              )
            })}

            {/* ② 通常商品（単品・セット問わず、バリエーション構造なし） */}
            {filteredStandalone.map(p => (
              <ProductRow
                key={p.id}
                p={p}
                commissionRate={commissionRate}
                onEdit={openEdit}
                onDelete={(p) => { if (confirm(`${p.name || p.sku} を削除しますか？`)) deleteMutation.mutate(p.id) }}
              />
            ))}

            {/* ③ 内部管理SKU（is_component=True）→ チェック時のみ表示 */}
              {showComponents && filteredSingles.map(p => (
                <ProductRow
                  key={p.id}
                  p={p}
                  commissionRate={commissionRate}
                  onEdit={openEdit}
                  onDelete={(p) => { if (confirm(`${p.name || p.sku} を削除しますか？`)) deleteMutation.mutate(p.id) }}
                />
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* 編集モーダル */}
      {editing && (
        <div onClick={handleModalClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
          <div onClick={e => e.stopPropagation()} style={{ background: '#fff', color: '#1a1a2e', borderRadius: 12, padding: 32, width: 620, maxHeight: '90vh', overflowY: 'auto', boxShadow: '0 8px 40px rgba(0,0,0,0.25)' }}>
            <h2 style={{ marginBottom: 20 }}>{editing === 'new' ? '商品追加' : '商品編集'}</h2>

            {/* 基本情報 */}
            <h3 style={{ fontSize: 13, color: '#64748b', marginBottom: 10 }}>基本情報</h3>
            <div className="form-grid" style={{ gridTemplateColumns: '1fr 1fr' }}>
              <div className="form-group" style={{ gridColumn: '1 / -1' }}>
                <label>SKU管理番号<span style={{ color: '#f87171' }}> *</span></label>
                <input {...f('sku')} placeholder="例: y76_b-b" />
              </div>
              <div className="form-group" style={{ gridColumn: '1 / -1' }}>
                <label>商品名</label>
                <input {...f('name')} placeholder="例: ○○ポーチ" />
              </div>
              <div className="form-group">
                <label>システム連携用SKU番号（全角48文字）</label>
                <input {...f('spec')} placeholder="例: 厚手4足セット　ブラック" />
              </div>
              <div className="form-group">
                <label>JANコード</label>
                <input {...f('jan_code')} placeholder="例: 4900000000000" />
              </div>
              <div className="form-group">
                <label>
                  セット入数
                  <span title="インボイスの1個が楽天で売る何個分か。&#13;&#10;例) set_size=1：普通の単品（デフォルト）&#13;&#10;例) set_size=4：1枚仕入れ→4枚セットで販売（クロスふきんなど）在庫はセット数で入力&#13;&#10;例) set_size=18：1袋仕入れ→単品18枚分（母乳パッド袋）&#13;&#10;※set_componentsで構成管理する場合はset_size=1のまま"
                    style={{ marginLeft: 6, color: '#94a3b8', cursor: 'help', fontSize: 14 }}>ⓘ</span>
                </label>
                <input type="number" min={1} {...f('set_size', 'number')} />
                <div style={{ fontSize: 11, color: '#64748b', marginTop: 3 }}>
                  {form.set_components && form.set_components !== '[]'
                    ? 'セット構成あり → 通常は1のまま'
                    : form.set_size > 1
                      ? `インボイス1行 = ${form.set_size}個分（原価÷${form.set_size}）`
                      : 'インボイス1行 = 1個分（通常）'}
                </div>
              </div>
              <div className="form-group">
                <label>仕入先</label>
                <input {...f('supplier')} placeholder="例: タオタロウ" />
              </div>
              <div className="form-group" style={{ gridColumn: '1 / -1' }}>
                <label>仕入れURL（複数ある場合は1行に1URL）</label>
                <textarea {...f('buy_url')} placeholder="https://..." rows={3} style={{ fontFamily: 'monospace', fontSize: 12 }} />
              </div>
              <div className="form-group" style={{ gridColumn: '1 / -1' }}>
                <label>仕様（中国語）<span style={{ fontSize: 11, color: '#94a3b8', marginLeft: 6 }}>タオタロウB列・発注書に反映 ／ 1688の選択肢の値を表示順に「、」区切り</span></label>
                <input {...f('supplier_spec')} placeholder="例: 燕麦色、S 建议75-95斤（1属性なら値そのまま）" />
                {specFormatWarning(form.supplier_spec) && (
                  <div style={{ color: '#e94560', fontSize: 11, marginTop: 4 }}>
                    ⚠ {specFormatWarning(form.supplier_spec)}
                  </div>
                )}
              </div>
              <div className="form-group">
                <label>単価（元）</label>
                <input type="number" step="0.01" {...f('price', 'number')} />
              </div>
              <div className="form-group">
                <label>仕入原価（円）</label>
                <input type="number" step="1" {...f('cost_jpy', 'number')} placeholder="インボイス取込で自動入力" />
              </div>
              <div className="form-group">
                <label>販売価格（円）</label>
                <input type="number" step="1" {...f('selling_price', 'number')} />
              </div>
              <div className="form-group">
                <label>送料（円）</label>
                <input type="number" step="1" {...f('shipping_fee', 'number')} placeholder="180" />
              </div>
              <div className="form-group">
                <label>
                  お客様専用メモ（タオタロウG列）
                  <span style={{ fontSize: 11, color: '#94a3b8', marginLeft: 6 }}>インボイス振り分け確認用・TAO太郎E列に出力</span>
                </label>
                <textarea value={form.customer_memo || ''} onChange={e => setForm(p => ({ ...p, customer_memo: e.target.value }))} rows={2} placeholder="例：4色セット（咖啡色・乳白色・灰色・浅灰色 各1枚）" />
              </div>
              <div className="form-group">
                <label>備考（タオタロウH列）</label>
                <textarea value={form.notes || ''} onChange={e => setForm(p => ({ ...p, notes: e.target.value }))} rows={2} />
              </div>
            </div>

            {/* 楽天管理情報 */}
            <div style={{ borderTop: '1px solid #e2e8f0', margin: '16px 0', paddingTop: 14 }}>
              <h3 style={{ fontSize: 13, color: '#64748b', marginBottom: 10 }}>🛒 楽天管理情報</h3>
              <div className="form-grid" style={{ gridTemplateColumns: '1fr 1fr' }}>
                <div className="form-group">
                  <label>楽天商品管理番号（商品URL）</label>
                  <input {...f('rakuten_item_url')} placeholder="例: s08-2" />
                </div>
                <div className="form-group">
                  <label>発注済2</label>
                  <input type="number" min={0} {...f('standard_stock', 'number')} />
                </div>
              </div>
            </div>

            {/* 在庫・販売実績 */}
            <div style={{ borderTop: '1px solid #e2e8f0', margin: '0 0 16px', paddingTop: 14 }}>
              <h3 style={{ fontSize: 13, color: '#64748b', marginBottom: 10 }}>📦 在庫 / 販売実績</h3>
              <div className="form-grid" style={{ gridTemplateColumns: '1fr 1fr' }}>
                <div className="form-group">
                  <label>実在庫（手持ち）</label>
                  <input type="number" min={0} {...f('stock', 'number')} />
                </div>
                <div className="form-group">
                  <label>発注済1</label>
                  <input type="number" min={0} {...f('inbound', 'number')} />
                </div>
                <div className="form-group">
                  <label>直近30日の販売数</label>
                  <input type="number" min={0} {...f('sales_30_recent', 'number')} />
                </div>
                <div className="form-group">
                  <label>60日前〜31日前の販売数</label>
                  <input type="number" min={0} {...f('sales_30_prev', 'number')} />
                </div>
              </div>
            </div>

            {/* 内部メモ */}
            <div style={{ borderTop: '1px solid #e2e8f0', margin: '0 0 16px', paddingTop: 14 }}>
              <div className="form-group">
                <label>内部メモ</label>
                <textarea value={form.memo || ''} onChange={e => setForm(p => ({ ...p, memo: e.target.value }))} rows={2} />
              </div>
              <div style={{ marginTop: 12 }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13 }}>
                  <input
                    type="checkbox"
                    checked={!!form.is_component}
                    onChange={e => setForm(p => ({ ...p, is_component: e.target.checked }))}
                    style={{ width: 'auto', accentColor: '#f59e0b' }}
                  />
                  <span>🔩 単品フラグ（セット構成用の内部管理商品 — 一覧では非表示）</span>
                </label>
              </div>
              <div style={{ marginTop: 8 }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13 }}>
                  <input
                    type="checkbox"
                    checked={!!form.is_material}
                    onChange={e => setForm(p => ({ ...p, is_material: e.target.checked }))}
                    style={{ width: 'auto', accentColor: '#3b82f6' }}
                  />
                  <span>📦 発送資材（宅配袋・ダンボール等 — 商品原価に含めず資材費として集計）</span>
                </label>
                <div style={{ fontSize: 11, color: '#64748b', marginLeft: 26, marginTop: 2 }}>
                  仕入時に送料・税の按分は受けますが、商品原価にはなりません。発注・在庫一覧にも表示されません。
                </div>
              </div>
              <div style={{ marginTop: 8 }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13 }}>
                  <input
                    type="checkbox"
                    checked={!!form.is_promo}
                    onChange={e => setForm(p => ({ ...p, is_promo: e.target.checked }))}
                    style={{ width: 'auto', accentColor: '#3b82f6' }}
                  />
                  <span>🎁 販促品（レビューキャンペーン特典等 — 楽天には出品していない）</span>
                </label>
                <div style={{ fontSize: 11, color: '#64748b', marginLeft: 26, marginTop: 2 }}>
                  楽天RMSへのpush対象外・発注推奨や在庫一覧にも表示されません。就労支援在庫で数量だけ把握したい商品用です。
                </div>
              </div>
            </div>

            {/* 再梱包の作業依頼で使う設定。商品ごとに毎回同じなのでここに持たせ、
                依頼を作るたびに入力し直さなくてよいようにする */}
            <div style={{ borderTop: '1px solid #e2e8f0', margin: '0 0 16px', paddingTop: 14 }}>
              <h3 style={{ fontSize: 13, color: '#64748b', marginBottom: 4 }}>再梱包の作業依頼（就労支援さん向け）</h3>
              <p style={{ fontSize: 12, color: '#475569', marginBottom: 10 }}>
                ここに入れておくと、作業依頼を作るときに自動で入ります。金額は「セット数 × 単価」で計算されます。
              </p>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 10 }}>
                <div className="form-group" style={{ margin: 0 }}>
                  <label>1セットに入れる数</label>
                  <input type="number" value={form.packing_set_qty ?? ''} placeholder="12"
                    onChange={e => setForm(p => ({ ...p, packing_set_qty: e.target.value === '' ? null : Number(e.target.value) }))} />
                </div>
                <div className="form-group" style={{ margin: 0 }}>
                  <label>1セットあたりの単価（円）</label>
                  <input type="number" step="0.1" value={form.packing_unit_price ?? ''} placeholder="3"
                    onChange={e => setForm(p => ({ ...p, packing_unit_price: e.target.value === '' ? null : Number(e.target.value) }))} />
                </div>
                <div className="form-group" style={{ margin: 0 }}>
                  <label>梱包材の種類</label>
                  <input value={form.packing_material || ''} placeholder="OPP大・サンクスシール"
                    onChange={e => setForm(p => ({ ...p, packing_material: e.target.value }))} />
                </div>
              </div>
              <div className="form-group" style={{ marginTop: 10, marginBottom: 0 }}>
                <label>梱包方法（作業内容）</label>
                <textarea rows={2} value={form.packing_method || ''}
                  placeholder="4カラーを1枚ずつOPP大に入れる（厚くなりすぎないように）"
                  onChange={e => setForm(p => ({ ...p, packing_method: e.target.value }))} />
              </div>
            </div>

            {/* セット構成（在庫連動用） */}
            <div style={{ borderTop: '1px solid #e2e8f0', margin: '0 0 16px', paddingTop: 14 }}>
              <h3 style={{ fontSize: 13, color: '#64748b', marginBottom: 4 }}>セット構成（在庫連動用）</h3>
              <p style={{ fontSize: 12, color: '#475569', marginBottom: 10 }}>
                在庫連動用。受注時に構成品在庫を増減し、RMS在庫再計算に使われます。
              </p>
              <SetComponentsEditor
                value={form.set_components || ''}
                onChange={v => setForm(p => ({ ...p, set_components: v }))}
                allProducts={products}
              />
            </div>

            {/* 発注用付属品（在庫連動しない） */}
            <div style={{ borderTop: '1px solid #e2e8f0', margin: '0 0 16px', paddingTop: 14 }}>
              <h3 style={{ fontSize: 13, color: '#64748b', marginBottom: 4 }}>発注用付属品（在庫連動しない）</h3>
              <p style={{ fontSize: 12, color: '#475569', marginBottom: 10 }}>
                発注・仕入れ用メモ。RMS在庫連動には使われません。
              </p>
              <SetComponentsEditor
                value={form.purchase_components || ''}
                onChange={v => setForm(p => ({ ...p, purchase_components: v }))}
                allProducts={products}
              />
            </div>

            <div style={{ display: 'flex', gap: 12, marginTop: 8 }}>
              <button
                className="btn btn-primary"
                disabled={!form.sku || saveMutation.isPending}
                onClick={trySave}
              >
                {saveMutation.isPending ? '保存中...' : '💾 保存'}
              </button>
              <button className="btn" onClick={() => setEditing(null)}>キャンセル</button>
            </div>
            {saveMutation.isError && (
              <div style={{ color: '#f87171', fontSize: 13, marginTop: 8 }}>
                {saveMutation.error?.response?.data?.detail || 'エラーが発生しました'}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// 仕入れURL複数対応：改行区切りで複数URLを保持。nameをクリッカブルにする
function BuyUrlLinks({ buyUrl, name }) {
  const urls = (buyUrl || '').split('\n').map(u => u.trim()).filter(Boolean)

  if (urls.length === 0) {
    return <span style={{ color: '#1a1a2e', fontWeight: 500 }}>{name}</span>
  }

  const openAll = () => urls.forEach(url => window.open(url, '_blank'))

  if (urls.length === 1) {
    return (
      <a href={urls[0]} target="_blank" rel="noreferrer"
        style={{ color: '#1a1a2e', fontWeight: 500, textDecoration: 'none', borderBottom: '1px dashed #94a3b8' }}>
        {name}
      </a>
    )
  }

  return (
    <span
      onClick={openAll}
      style={{ color: '#1a1a2e', fontWeight: 500, cursor: 'pointer', borderBottom: '1px dashed #94a3b8' }}>
      {name}
    </span>
  )
}

// 商品行コンポーネント
function ProductRow({ p, commissionRate = 0.09, expanded, childCount, onToggle, onEdit, onDelete, isSingle, isChild, children }) {
  const rowBg = isChild ? '#f8faff' : '#ffffff'
  const indent = isChild ? 32 : 0

  const shippingFee = p.shipping_fee ?? 180
  const commission = p.selling_price ? p.selling_price * commissionRate : null
  const profit = (p.selling_price != null && p.cost_jpy != null) ? p.selling_price - p.cost_jpy - (p.selling_price * commissionRate) - shippingFee : null
  const profitRate = (profit != null && p.selling_price) ? profit / p.selling_price : null

  return (
    <>
      <tr style={{ borderBottom: '1px solid #e5e7eb', background: rowBg }}>
        <td style={{ padding: `10px 12px 10px ${12 + indent}px`, fontFamily: 'monospace', whiteSpace: 'nowrap', fontSize: 12, color: '#666' }}>
          {isChild && <span style={{ color: '#ccc', marginRight: 6 }}>└</span>}
          {p.sku}
        </td>
        <td style={{ padding: '10px 12px', minWidth: 140 }}>
          <BuyUrlLinks buyUrl={p.buy_url} name={p.name || '—'} />
          {p.spec && <div style={{ color: '#888', fontSize: 11 }}>{p.spec}</div>}
        </td>
        <td style={{ padding: '10px 12px', width: 90, maxWidth: 90, overflow: 'hidden', fontSize: 12, color: '#475569' }}>
          {p.customer_memo
            ? <span title={p.customer_memo} style={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', cursor: 'default' }}>{p.customer_memo}</span>
            : '—'}
        </td>
        <td style={{ padding: '10px 12px', textAlign: 'right', color: '#1a1a2e' }}>
          {p.cost_jpy != null ? `¥${p.cost_jpy.toLocaleString()}` : '—'}
        </td>
        <td style={{ padding: '10px 12px', textAlign: 'right', color: '#1a1a2e', fontWeight: 600 }}>
          {p.selling_price ? `¥${p.selling_price.toLocaleString()}` : '—'}
        </td>
        <td style={{ padding: '10px 12px', textAlign: 'center', color: '#666' }}>
          {(commissionRate * 100).toFixed(0)}%
        </td>
        <td style={{ padding: '10px 12px', textAlign: 'right', color: profit != null ? (profit >= 0 ? '#16a34a' : '#dc2626') : '#999', fontWeight: 600 }}>
          {profit != null ? `¥${Math.round(profit).toLocaleString()}` : '—'}
        </td>
        <td style={{ padding: '10px 12px', textAlign: 'right', color: profitRate != null ? (profitRate >= 0.15 ? '#16a34a' : profitRate >= 0 ? '#ca8a04' : '#dc2626') : '#999' }}>
          {profitRate != null ? `${(profitRate * 100).toFixed(1)}%` : '—'}
        </td>
        <td style={{ padding: '10px 12px', width: 90, maxWidth: 90, overflow: 'hidden', fontSize: 12, color: '#475569' }}>
          {p.notes
            ? <span title={p.notes} style={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', cursor: 'default' }}>{p.notes}</span>
            : '—'}
        </td>
        <td style={{ padding: '10px 12px', whiteSpace: 'nowrap' }}>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            {isSingle && childCount > 0 && (
              <button
                className="btn"
                style={{ fontSize: 11, padding: '3px 8px', background: expanded ? '#dbeafe' : '#f1f5f9', color: '#1e40af', border: `1px solid ${expanded ? '#93c5fd' : '#e2e8f0'}`, whiteSpace: 'nowrap' }}
                onClick={onToggle}
              >
                {expanded ? '▲' : '▼'} {childCount}件
              </button>
            )}
            <button className="btn" style={{ fontSize: 12, padding: '3px 10px' }} onClick={() => onEdit(p)}>編集</button>
            <button
              className="btn" style={{ fontSize: 12, padding: '3px 10px', color: '#dc2626' }}
              onClick={() => onDelete(p)}
            >削除</button>
          </div>
        </td>
      </tr>
      {children}
    </>
  )
}

// セット構成エディタコンポーネント
function SetComponentsEditor({ value, onChange, allProducts }) {
  const parse = (v) => { try { return JSON.parse(v || '[]') } catch { return [] } }
  const items = parse(value)

  const update = (newItems) => onChange(newItems.length > 0 ? JSON.stringify(newItems) : '')

  const addRow = () => update([...items, { sku: '', qty: 1, buy_url: '', supplier_spec: '', price: '', customer_memo: '', notes: '' }])
  const removeRow = (i) => update(items.filter((_, idx) => idx !== i))
  const updateRow = (i, field, val) => {
    const next = items.map((item, idx) => idx === i ? { ...item, [field]: val } : item)
    update(next)
  }

  const labelStyle = { fontSize: 11, color: '#94a3b8', marginBottom: 2 }
  const inputStyle = { padding: '5px 8px', fontSize: 12, background: '#0f172a', color: '#e2e8f0', border: '1px solid #374151', borderRadius: 6, width: '100%' }

  return (
    <div>
      {items.map((item, i) => (
        <div key={i} style={{ border: '1px solid #1e293b', borderRadius: 8, padding: '10px 12px', marginBottom: 10, background: '#0a0f1e' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <span style={{ fontSize: 12, color: '#94a3b8' }}>構成 {i + 1}</span>
            <button className="btn" style={{ fontSize: 11, padding: '2px 8px', color: '#f87171' }} onClick={() => removeRow(i)}>✕ 削除</button>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 8 }}>
            <div style={{ gridColumn: '1 / -1' }}>
              <div style={labelStyle}>SKU（商品マスタから選択 — 空欄でも可）</div>
              <select
                value={item.sku || ''}
                onChange={e => updateRow(i, 'sku', e.target.value)}
                style={{ ...inputStyle }}
              >
                <option value="">— 選択しない（URL直接入力）—</option>
                {allProducts.map(p => (
                  <option key={p.id} value={p.sku}>
                    {p.sku}{p.name ? ` - ${p.name}` : ''}
                  </option>
                ))}
              </select>
            </div>
            <div style={{ gridColumn: '1 / -1' }}>
              <div style={labelStyle}>発注先URL</div>
              <input
                value={item.buy_url || ''}
                onChange={e => updateRow(i, 'buy_url', e.target.value)}
                style={inputStyle}
                placeholder="https://detail.1688.com/..."
              />
            </div>
            <div>
              <div style={labelStyle}>仕様（中国語）</div>
              <input
                value={item.supplier_spec || ''}
                onChange={e => updateRow(i, 'supplier_spec', e.target.value)}
                style={inputStyle}
                placeholder="例: 水色"
              />
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <div style={{ flex: 1 }}>
                <div style={labelStyle}>単価（元）</div>
                <input
                  type="text"
                  value={item.price ?? ''}
                  onChange={e => {
                    const v = e.target.value
                    updateRow(i, 'price', v === '' ? '' : isNaN(Number(v)) ? item.price : v)
                  }}
                  onBlur={e => {
                    const v = parseFloat(e.target.value)
                    if (!isNaN(v)) updateRow(i, 'price', v)
                  }}
                  style={inputStyle}
                  placeholder="0.19"
                />
              </div>
              <div style={{ width: 70 }}>
                <div style={labelStyle}>数量</div>
                <input
                  type="number" min={1}
                  value={item.qty || 1}
                  onChange={e => updateRow(i, 'qty', Number(e.target.value))}
                  style={{ ...inputStyle, textAlign: 'center' }}
                />
              </div>
            </div>
            <div style={{ gridColumn: '1 / -1' }}>
              <div style={labelStyle}>お客様専用メモ（タオタロウG列）</div>
              <input
                value={item.customer_memo || ''}
                onChange={e => updateRow(i, 'customer_memo', e.target.value)}
                style={inputStyle}
                placeholder="例: 4色セット（咖啡色・乳白色・灰色・浅灰色 各1枚）"
              />
            </div>
            <div style={{ gridColumn: '1 / -1' }}>
              <div style={labelStyle}>備考（タオタロウH列）</div>
              <input
                value={item.notes || ''}
                onChange={e => updateRow(i, 'notes', e.target.value)}
                style={inputStyle}
                placeholder="例: チャック袋に入っているものをお願いします"
              />
            </div>
          </div>
        </div>
      ))}
      <button className="btn" style={{ fontSize: 12, marginTop: 4 }} onClick={addRow}>+ 構成を追加</button>
    </div>
  )
}
