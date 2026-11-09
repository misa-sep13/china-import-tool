import { useState, useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import api from '../api/client'
import { normalizeSearch } from '../searchUtil'
import PeriodInventoryPanel from '../components/PeriodInventoryPanel'

const POLL_INTERVAL = 3000
// これより古い覚えなら、開いたときに裏で取り直す
const STALE_MINUTES = 15

// 「3分前」のように出す。何時の数字か分からないと、古い在庫で発注してしまう
function ago(iso) {
  if (!iso) return ''
  const sec = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (sec < 60) return 'たった今'
  if (sec < 3600) return `${Math.floor(sec / 60)}分前`
  if (sec < 86400) return `${Math.floor(sec / 3600)}時間前`
  return `${Math.floor(sec / 86400)}日前`
}

function fmtTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

const yen = (v) => (v === null || v === undefined || v === '') ? '-' : `¥${Math.round(v).toLocaleString()}`

export default function StockPage() {
  const qc = useQueryClient()
  // idle: 何も無い / loading: 覚えも無く取得中 / done: 表示中 / error
  const [jobStatus, setJobStatus] = useState('idle')
  // 表を出したまま裏で取り直しているか
  const [refreshing, setRefreshing] = useState(false)
  const [jobElapsed, setJobElapsed] = useState(0)
  const [fetchedAt, setFetchedAt] = useState(null)
  const [rawItems, setRawItems] = useState([])
  const [selected, setSelected] = useState(null)
  const [qtyOverrides, setQtyOverrides] = useState({})
  const [exporting, setExporting] = useState(false)
  const [error, setError] = useState('')
  const [sortKey, setSortKey] = useState('days_left')
  const [sortAsc, setSortAsc] = useState(true)
  const [search, setSearch] = useState('')
  const [ordering, setOrdering] = useState(null)
  const [justOrdered, setJustOrdered] = useState(new Set())
  const [hiding, setHiding] = useState(null)
  const [, setTick] = useState(0)
  // 旧アカウントの商品の洗い出し（null=閉じている）
  const [oldAcc, setOldAcc] = useState(null)
  const [oldPick, setOldPick] = useState(new Set())
  const [oldBusy, setOldBusy] = useState(false)
  const pollRef = useRef(null)

  const stopPolling = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }

  // 新しい値を裏で取る。表が出ているときは出したまま、取れたら差し替える
  const startFetch = async (force = false, hasTable = false) => {
    stopPolling()
    setError('')
    setJobElapsed(0)
    if (hasTable) setRefreshing(true)
    else setJobStatus('loading')
    try {
      const res = await api.post(`/orders/stock/start?force=${force}`)
      const id = res.data.job_id
      pollRef.current = setInterval(async () => {
        try {
          const status = await api.get(`/orders/preview/status/${id}`)
          setJobElapsed(status.data.elapsed)
          if (status.data.status === 'done') {
            stopPolling()
            setRawItems(status.data.result || [])
            setFetchedAt(new Date().toISOString())
            setQtyOverrides({})
            setJobStatus('done')
            setRefreshing(false)
          } else if (status.data.status === 'error') {
            stopPolling()
            setError(status.data.error || 'SP-APIデータ取得に失敗しました')
            setRefreshing(false)
            if (!hasTable) setJobStatus('error')
          }
        } catch {
          stopPolling()
          setError('ステータス取得に失敗しました')
          setRefreshing(false)
          if (!hasTable) setJobStatus('error')
        }
      }, POLL_INTERVAL)
    } catch {
      setRefreshing(false)
      setError('データ取得の開始に失敗しました')
      if (!hasTable) setJobStatus('error')
    }
  }

  useEffect(() => {
    (async () => {
      // まず最後に取れた結果を出す（待たない）
      try {
        const r = await api.get('/orders/stock/snapshot')
        if (r.data && Array.isArray(r.data.items)) {
          setRawItems(r.data.items)
          setFetchedAt(r.data.fetched_at)
          setJobStatus('done')
          const age = r.data.fetched_at
            ? (Date.now() - new Date(r.data.fetched_at).getTime()) / 60000 : 9999
          if (age > STALE_MINUTES) startFetch(false, true)
          return
        }
      } catch { /* 覚えが読めなければ普通に取りに行く */ }
      startFetch(false, false)
    })()
    // 「○分前」を進める
    const t = setInterval(() => setTick(x => x + 1), 30000)
    return () => { stopPolling(); clearInterval(t) }
  }, [])

  const items = rawItems.map((item, i) => ({
    ...item,
    qty: qtyOverrides[item.product_id] ?? item.qty,
    _idx: i,
  }))

  const q = normalizeSearch(search.trim())
  const filtered = q
    ? items.filter(item =>
        normalizeSearch(item.sku).includes(q) ||
        normalizeSearch(item.name).includes(q) ||
        normalizeSearch(item.asin || '').includes(q) ||
        normalizeSearch(item.fnsku || '').includes(q) ||
        normalizeSearch(item.color).includes(q) ||
        normalizeSearch(item.size).includes(q)
      )
    : items

  const sorted = [...filtered].sort((a, b) => {
    let va = a[sortKey], vb = b[sortKey]
    // 値の無いもの（利益が出せない等）は常に下へ
    const na = va === null || va === undefined, nb = vb === null || vb === undefined
    if (na && nb) return 0
    if (na) return 1
    if (nb) return -1
    if (typeof va === 'string') va = va.toLowerCase()
    if (typeof vb === 'string') vb = vb.toLowerCase()
    if (va < vb) return sortAsc ? -1 : 1
    if (va > vb) return sortAsc ? 1 : -1
    return 0
  })

  const currentSelected = selected ?? new Set()

  const toggleSelect = (idx) => {
    setSelected(prev => {
      const next = new Set(prev ?? new Set())
      next.has(idx) ? next.delete(idx) : next.add(idx)
      return next
    })
  }

  const toggleAll = () => {
    const allIdx = sorted.map(item => item._idx)
    if (currentSelected.size === sorted.length && sorted.every(item => currentSelected.has(item._idx))) {
      setSelected(new Set())
    } else {
      setSelected(new Set(allIdx))
    }
  }

  const updateQty = (productId, val) => {
    setQtyOverrides(prev => ({ ...prev, [productId]: Number(val) }))
  }

  const handleSort = (key) => {
    if (sortKey === key) { setSortAsc(a => !a) } else { setSortKey(key); setSortAsc(true) }
  }
  const sortIcon = (key) => sortKey === key ? (sortAsc ? ' ▲' : ' ▼') : ''

  // 手元の1行だけ書き換える（取り直さずに画面へ反映する）
  const patchItem = (productId, patch) => {
    setRawItems(prev => prev.map(it => it.product_id === productId ? { ...it, ...patch } : it))
  }

  const hideProduct = async (item) => {
    if (!confirm(`${item.sku} を一覧から非表示にしますか？\n（商品マスタからも外れます。Amazonの出品には影響しません。後で復元可能）`)) return
    setHiding(item.product_id)
    setError('')
    try {
      await api.delete(`/products/${item.product_id}`)
      setRawItems(prev => prev.filter(it => it.product_id !== item.product_id))
    } catch {
      setError('非表示に失敗しました')
    } finally {
      setHiding(null)
    }
  }

  // 今後発注しない。一覧には残し、推奨発注だけ止める
  const toggleDiscontinued = async (item) => {
    const next = !item.discontinued
    if (next && !confirm(`${item.sku} を「今後発注しない」にしますか？\n推奨発注が0になり、発注管理にも出なくなります（いつでも戻せます）`)) return
    try {
      await api.put(`/products/${item.product_id}`, { discontinued: next })
      patchItem(item.product_id, next
        ? { discontinued: true, qty: 0, recommended_qty: 0,
            recommended_pieces: Math.min(0, item.recommended_pieces || 0) }
        : { discontinued: false })
      if (!next) setError('戻しました。推奨発注は「いますぐ更新」で計算し直されます')
    } catch {
      setError('保存に失敗しました')
    }
  }

  const editLot = async (item) => {
    const v = window.prompt(`${item.sku} の最小ロット（個）を入れてください。\n空か0で消します`, item.order_lot || '')
    if (v === null) return
    const n = parseInt(v, 10) || 0
    try {
      await api.put(`/products/${item.product_id}`, { order_lot: n })
      patchItem(item.product_id, { order_lot: n || null })
    } catch {
      setError('保存に失敗しました')
    }
  }

  // 新アカウントの在庫・このツールの出品のどちらにも無い商品を拾う。
  // 有効のままだと、定期実行がそのASINを新アカウントでAmazonに問い合わせてしまう
  const findOldAccount = async () => {
    setOldBusy(true)
    setError('')
    try {
      const r = await api.get('/products/old-account/candidates')
      const list = r.data.items || []
      setOldAcc(list)
      setOldPick(new Set(list.map(x => x.id)))
    } catch (e) {
      setError(e?.response?.data?.detail || '旧アカウントの商品を探せませんでした')
    } finally {
      setOldBusy(false)
    }
  }

  const hideOldAccount = async () => {
    const ids = [...oldPick]
    if (!ids.length) return
    if (!confirm(`${ids.length}件を非表示にします。
Amazonへの問い合わせ対象から外れます（消さないので、あとで戻せます）`)) return
    setOldBusy(true)
    try {
      await api.post('/products/old-account/hide', { ids })
      setRawItems(prev => prev.filter(it => !oldPick.has(it.product_id)))
      setOldAcc(null)
      setError(`${ids.length}件を非表示にしました`)
    } catch {
      setError('非表示にできませんでした')
    } finally {
      setOldBusy(false)
    }
  }

  // 旧アカウントとして非表示にした商品の、ASIN・FNSKUの記録を消す（元に戻せない）
  const clearOldIds = async () => {
    setOldBusy(true)
    setError('')
    try {
      const pre = await api.post('/products/old-account/clear-ids?dry_run=true')
      const n = pre.data.count || 0
      if (!n) { setError('消す対象はありません（ASIN・FNSKUはもう空です）'); return }
      const list = (pre.data.items || []).slice(0, 10).map(x => `${x.sku}  ${x.asin || ''}`).join('\n')
      const more = n > 10 ? `\n…ほか${n - 10}件` : ''
      if (!confirm(`旧アカウントとして非表示にした ${n}件 のASIN・FNSKUを空にします。\n元には戻せません（SKU・商品名・原価は残ります）。\n\n${list}${more}`)) return
      const r = await api.post('/products/old-account/clear-ids?dry_run=false')
      setError(`${r.data.count}件のASIN・FNSKUを空にしました`)
    } catch {
      setError('消せませんでした')
    } finally {
      setOldBusy(false)
    }
  }

  const recordOrder = async (item) => {
    if (!item.qty || item.qty <= 0) { setError('発注数が0です'); return }
    setOrdering(item.product_id)
    setError('')
    try {
      await api.post('/orders/order', { items: [{
        sku: item.sku, name: item.name, color: item.color, size: item.size,
        qty: item.qty, price: item.price, buy_url: item.buy_url,
        photo_url: item.photo_url, asin: item.asin, fnsku: item.fnsku, note: item.note,
      }] })
      setJustOrdered(prev => new Set(prev).add(item.product_id))
      qc.invalidateQueries(['orderHistory'])
    } catch {
      setError('発注の記録に失敗しました')
    } finally {
      setOrdering(null)
    }
  }

  const handleExport = async () => {
    const targets = sorted.filter(item => currentSelected.has(item._idx) && item.qty > 0)
    if (!targets.length) { setError('選択された商品がないか、発注数が0です'); return }
    setExporting(true)
    try {
      const res = await api.post('/orders/export', { items: targets }, { responseType: 'blob' })
      const url = window.URL.createObjectURL(new Blob([res.data]))
      const a = document.createElement('a')
      a.href = url
      a.download = `${new Date().toISOString().slice(0, 10).replace(/-/g, '')}_order.xlsx`
      a.click()
      window.URL.revokeObjectURL(url)
      qc.invalidateQueries(['orderHistory'])
      setQtyOverrides({})
      setSelected(new Set())
    } catch {
      setError('Excelの出力に失敗しました')
    } finally {
      setExporting(false)
    }
  }

  const checkedCount = sorted.filter(item => currentSelected.has(item._idx)).length
  const firstLoading = jobStatus === 'loading' || jobStatus === 'idle'

  const daysText = (days) => {
    if (days === null || days === undefined || days >= 9999) return null
    const color = days < 30 ? '#dc2626' : days < 60 ? '#d97706' : '#64748b'
    return <div style={{ fontSize: 11, color }}>({days}日)</div>
  }

  // 商品名の下に出す注意。開かなくても危ないものが分かるように
  const notes = (item) => {
    const out = []
    if (item.discontinued) out.push({ t: '🚫 今後発注しない', bg: '#f1f5f9', c: '#475569' })
    if (item.profit !== null && item.profit !== undefined && item.profit < 0) {
      out.push({ t: `赤字 ${yen(item.profit)}/個`, bg: '#fee2e2', c: '#b91c1c' })
    }
    if (item.margin !== null && item.margin !== undefined && item.margin >= 0 && item.margin < 10) {
      out.push({ t: `利益率 ${item.margin}%`, bg: '#fef3c7', c: '#92400e' })
    }
    if (item.order_lot && item.recommended_pieces > 0 && item.recommended_pieces < item.order_lot) {
      out.push({ t: `⚠ ロット${item.order_lot}まで あと${item.order_lot - item.recommended_pieces}個`, bg: '#fee2e2', c: '#b91c1c' })
    }
    if (item.components > 0) out.push({ t: `▶ 付属品${item.components}点`, bg: '#eef2ff', c: '#3730a3' })
    if (item.cost_jpy === null || item.cost_jpy === undefined) out.push({ t: '原価未設定', bg: '#fef3c7', c: '#92400e' })
    if (!item.selling_price) out.push({ t: '売価未設定', bg: '#fef3c7', c: '#92400e' })
    return out
  }

  const th = (key, label, extra = {}) => (
    <th
      onClick={key ? () => handleSort(key) : undefined}
      style={{
        cursor: key ? 'pointer' : 'default', userSelect: 'none', whiteSpace: 'nowrap',
        textAlign: 'right', fontSize: 12,
        background: sortKey === key ? '#e0e7ff' : extra.bg,
        ...extra.style,
      }}
    >{label}{key ? sortIcon(key) : ''}</th>
  )

  const num = (v, unit = '個', color) => (
    <span style={{ fontWeight: 600, color: v > 0 ? (color || '#1e293b') : '#cbd5e1' }}>
      {v || 0}<span style={{ fontSize: 10, color: '#94a3b8', marginLeft: 1 }}>{unit}</span>
    </span>
  )

  // 期間の販売数（日販×日数）と日販を並べる
  const salesCell = (rate, days) => (
    <td style={{ textAlign: 'right', whiteSpace: 'nowrap', fontSize: 12 }}>
      <div style={{ fontWeight: 600 }}>{Math.round((rate || 0) * days)}</div>
      <div style={{ fontSize: 10, color: '#94a3b8' }}>{(rate || 0).toFixed(1)}/日</div>
    </td>
  )

  const stockBg = '#f8fafc'
  const salesBg = '#f0fdf4'
  const moneyBg = '#fffbeb'

  return (
    <div>
      <h1>📊 全在庫一覧</h1>

      <PeriodInventoryPanel platform="amazon" title="📦 期末在庫金額（Amazon）" />

      <div className="card">
        {/* いつの数字か。古い在庫で発注しないよう、常に見えるところに出す */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 12px',
            borderRadius: 999, fontSize: 12, fontWeight: 600,
            background: refreshing ? '#fef3c7' : '#dcfce7',
            color: refreshing ? '#92400e' : '#166534',
          }}>
            <span style={{ width: 8, height: 8, borderRadius: 4, background: refreshing ? '#f59e0b' : '#22c55e' }} />
            Amazon在庫・販売 {fetchedAt ? `${ago(fetchedAt)}（${fmtTime(fetchedAt)}）` : 'まだありません'}
          </span>
          {refreshing && (
            <span style={{ fontSize: 12, color: '#92400e' }}>
              裏で最新を取得中… {jobElapsed > 0 ? `${jobElapsed}秒` : ''}（表はそのまま使えます）
            </span>
          )}
          <button
            className="btn btn-secondary"
            style={{ padding: '4px 12px', fontSize: 12 }}
            onClick={() => startFetch(true, jobStatus === 'done')}
            disabled={refreshing || firstLoading}
          >⚡ いますぐ更新</button>
        </div>
        <div className="top-actions">
          <button className="btn btn-success" onClick={handleExport} disabled={exporting || checkedCount === 0}>
            {exporting ? '生成中...' : `📥 Excelダウンロード（${checkedCount}件）`}
          </button>
          <input
            type="text" placeholder="SKU・商品名・ASIN・FNSKU・色/サイズで絞り込み"
            className="search-input-ja"
            value={search} onChange={e => setSearch(e.target.value)}
            style={{ width: 320, flex: '0 0 320px' }}
          />
          <button className="btn btn-secondary" style={{ fontSize: 12 }}
            onClick={findOldAccount} disabled={oldBusy}>
            {oldBusy && oldAcc === null ? '探しています…' : '🧹 旧アカウントの商品を探す'}
          </button>
          <button className="btn btn-secondary" style={{ fontSize: 12 }}
            onClick={clearOldIds} disabled={oldBusy}>
            🗑 非表示にした旧商品のASIN・FNSKUを消す
          </button>
        </div>
        {error && <p className="error-msg">{error}</p>}
        {oldAcc !== null && (
          <div style={{ marginTop: 12, padding: 12, border: '1px solid #fecaca', borderRadius: 8, background: '#fff7f7' }}>
            {oldAcc.length === 0 ? (
              <div style={{ fontSize: 13 }}>
                見つかりませんでした。有効な商品はすべて新アカウントにあります。
                <button className="btn btn-sm" style={{ marginLeft: 8 }} onClick={() => setOldAcc(null)}>閉じる</button>
              </div>
            ) : (
              <>
                <div style={{ fontSize: 13, marginBottom: 8 }}>
                  新アカウントのFBA在庫にも、このツールの出品にも無い商品が <b>{oldAcc.length}件</b> あります。
                  旧アカウントの商品なら、非表示にするとAmazonへの問い合わせ対象から外れます。
                  <b>新アカウントで出したばかりでFBAにまだ納品していない商品も混ざることがある</b>ので、チェックを外してから押してください。
                </div>
                <div style={{ maxHeight: 320, overflow: 'auto', background: '#fff', border: '1px solid #f1f5f9', borderRadius: 6 }}>
                  {oldAcc.map(x => (
                    <label key={x.id} style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '4px 8px', borderBottom: '1px solid #f8fafc', fontSize: 12 }}>
                      <input type="checkbox" checked={oldPick.has(x.id)}
                        onChange={() => setOldPick(prev => {
                          const n = new Set(prev); n.has(x.id) ? n.delete(x.id) : n.add(x.id); return n
                        })} />
                      {x.photo_url
                        ? <img src={x.photo_url} alt="" referrerPolicy="no-referrer" style={{ width: 32, height: 32, objectFit: 'cover', borderRadius: 4 }} />
                        : <span style={{ width: 32, height: 32, background: '#f1f5f9', borderRadius: 4, display: 'inline-block' }} />}
                      <span style={{ fontFamily: 'monospace', minWidth: 110 }}>{x.sku}</span>
                      <span style={{ fontFamily: 'monospace', color: '#64748b', minWidth: 110 }}>{x.asin}</span>
                      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {x.name}{(x.color || x.size) ? `（${[x.color, x.size].filter(Boolean).join(' / ')}）` : ''}
                      </span>
                    </label>
                  ))}
                </div>
                <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                  <button className="btn btn-danger" style={{ background: '#dc2626', color: '#fff' }}
                    onClick={hideOldAccount} disabled={oldBusy || oldPick.size === 0}>
                    {oldBusy ? '...' : `チェックした${oldPick.size}件を非表示にする`}
                  </button>
                  <button className="btn btn-sm" onClick={() => setOldAcc(null)}>閉じる</button>
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {firstLoading && (
        <div className="card" style={{ textAlign: 'center', color: '#555', padding: 40 }}>
          <div style={{ fontSize: 32, marginBottom: 12 }}>⏳</div>
          <p style={{ fontWeight: 600, marginBottom: 8 }}>SP-APIからデータを取得中...</p>
          <p style={{ fontSize: 13, color: '#888' }}>初回だけ待ちます。次からは前回の結果をすぐ出し、裏で更新します。</p>
          {jobElapsed > 0 && <p style={{ fontSize: 13, color: '#aaa', marginTop: 8 }}>経過時間: {jobElapsed}秒</p>}
        </div>
      )}

      {jobStatus === 'error' && (
        <div className="card" style={{ textAlign: 'center', color: '#c00', padding: 40 }}>
          <div style={{ fontSize: 32, marginBottom: 8 }}>⚠️</div>
          <p>データ取得に失敗しました。「いますぐ更新」で再試行してください。</p>
        </div>
      )}

      {jobStatus === 'done' && (
        <div className="card">
          <h2>全在庫（{sorted.length}件）</h2>
          <div className="sticky-table-wrap">
            <table className="sticky-table">
              <thead>
                <tr>
                  <th style={{ width: 36, cursor: 'pointer' }} onClick={toggleAll}>
                    <input
                      type="checkbox"
                      checked={sorted.length > 0 && sorted.every(item => currentSelected.has(item._idx))}
                      onChange={toggleAll}
                      onClick={e => e.stopPropagation()}
                    />
                  </th>
                  <th onClick={() => handleSort('sku')} style={{ cursor: 'pointer', whiteSpace: 'nowrap', fontSize: 12, minWidth: 340 }}>
                    商品{sortIcon('sku')}
                  </th>
                  {th('stock', <>在庫合計<br /><small>(日数)</small></>, { bg: stockBg })}
                  {th('available', <>FBA販売可<br /><small>(日数)</small></>, { bg: stockBg })}
                  {th('inbound', '輸送中', { bg: stockBg })}
                  {th('processing', '梱包中', { bg: stockBg })}
                  {th('ordered', '発注済', { bg: stockBg })}
                  {th('recommended_pieces', <>推奨発注<br /><small>(個)</small></>)}
                  {th(null, '発注数')}
                  {th('sales_7', '7日', { bg: salesBg })}
                  {th('sales_15', '15日', { bg: salesBg })}
                  {th('sales_30', '30日', { bg: salesBg })}
                  {th('sales_60', '60日', { bg: salesBg })}
                  {th('daily', '日販', { bg: salesBg })}
                  {th('selling_price', '売価', { bg: moneyBg })}
                  {th('cost_jpy', '原価', { bg: moneyBg })}
                  {th('profit', <>利益<br /><small>(1個)</small></>, { bg: moneyBg })}
                  {th('margin', '利益率', { bg: moneyBg })}
                  {th('price', <>仕入<br /><small>(元)</small></>)}
                  <th style={{ textAlign: 'center', fontSize: 12 }}>発注</th>
                  <th style={{ textAlign: 'center', fontSize: 12 }}>操作</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map(item => (
                  <tr
                    key={item.product_id}
                    style={{
                      background: item.discontinued ? '#f8fafc'
                        : item.recommended_pieces > 0 ? '#fff7ed' : undefined,
                      opacity: item.discontinued ? 0.75 : 1,
                    }}
                  >
                    <td style={{ textAlign: 'center', cursor: 'pointer' }} onClick={() => toggleSelect(item._idx)}>
                      <input
                        type="checkbox"
                        checked={currentSelected.has(item._idx)}
                        onChange={() => toggleSelect(item._idx)}
                        onClick={e => e.stopPropagation()}
                      />
                    </td>
                    <td style={{ minWidth: 340, maxWidth: 420 }}>
                      <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
                        {item.photo_url
                          ? <img src={item.photo_url} alt="" loading="lazy" referrerPolicy="no-referrer"
                              onError={e => { e.currentTarget.style.visibility = 'hidden' }}
                              style={{ width: 52, height: 52, objectFit: 'cover', borderRadius: 6, border: '1px solid #e2e8f0', flex: '0 0 52px' }} />
                          : <div style={{ width: 52, height: 52, borderRadius: 6, background: '#f1f5f9', flex: '0 0 52px' }} />}
                        <div style={{ minWidth: 0 }}>
                          <a href={item.amazon_url || undefined} target="_blank" rel="noreferrer"
                            title={item.name}
                            style={{
                              color: '#1e293b', fontSize: 12, fontWeight: 600, lineHeight: 1.4,
                              display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
                              overflow: 'hidden', textDecoration: 'none',
                            }}>{item.name}</a>
                          <div style={{ fontSize: 10, color: '#64748b', marginTop: 2, fontFamily: 'monospace' }}>
                            {item.sku}　{item.asin}　{item.fnsku}
                            {(item.color || item.size) && <span style={{ fontFamily: 'inherit' }}>　{[item.color, item.size].filter(Boolean).join(' / ')}</span>}
                            {item.buy_url && <> <a href={item.buy_url} target="_blank" rel="noreferrer"
                              style={{ fontSize: 10, padding: '0 4px', border: '1px solid #fdba74', color: '#c2410c', borderRadius: 3, textDecoration: 'none' }}>仕入先</a></>}
                          </div>
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
                            {notes(item).map((n, i) => (
                              <span key={i} style={{ fontSize: 10, padding: '1px 6px', borderRadius: 4, background: n.bg, color: n.c, fontWeight: 600 }}>{n.t}</span>
                            ))}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td style={{ textAlign: 'right', background: stockBg }}>
                      {num(item.stock)}{daysText(item.days_left)}
                    </td>
                    <td style={{ textAlign: 'right', background: stockBg }}>
                      {num(item.available)}{daysText(item.fba_days)}
                    </td>
                    <td style={{ textAlign: 'right', background: stockBg }}>{num(item.inbound, '個', '#2563eb')}</td>
                    <td style={{ textAlign: 'right', background: stockBg }}>{num(item.processing, '個', '#7c3aed')}</td>
                    <td style={{ textAlign: 'right', background: stockBg }}>{num(item.ordered, '個', '#e11d48')}</td>
                    <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                      {item.recommended_pieces > 0
                        ? <span style={{ color: '#e11d48', fontWeight: 700 }}>+{item.recommended_pieces}</span>
                        : <span style={{ color: '#16a34a' }}>{item.recommended_pieces || 0}</span>}
                      {item.set_size > 1 && <div style={{ fontSize: 10, color: '#94a3b8' }}>{item.set_size}個/セット</div>}
                    </td>
                    <td>
                      <input
                        type="number" className="qty-input" min={0}
                        value={item.qty}
                        onChange={e => updateQty(item.product_id, e.target.value)}
                        style={{ width: 64 }}
                      />
                    </td>
                    {salesCell(item.sales_7, 7)}
                    {salesCell(item.sales_15, 15)}
                    {salesCell(item.sales_30, 30)}
                    {salesCell(item.sales_60, 60)}
                    <td style={{ textAlign: 'right', fontWeight: 700, background: salesBg }}>{item.daily}</td>
                    <td style={{ textAlign: 'right', fontSize: 12, background: moneyBg }}>{yen(item.selling_price)}</td>
                    <td style={{ textAlign: 'right', fontSize: 12, background: moneyBg }}>{yen(item.cost_jpy)}</td>
                    <td style={{ textAlign: 'right', fontSize: 12, fontWeight: 600, background: moneyBg,
                      color: item.profit < 0 ? '#dc2626' : '#1e293b' }}>{yen(item.profit)}</td>
                    <td style={{ textAlign: 'right', fontSize: 12, fontWeight: 600, background: moneyBg,
                      color: item.margin === null || item.margin === undefined ? '#cbd5e1'
                        : item.margin < 0 ? '#dc2626' : item.margin < 15 ? '#d97706' : '#15803d' }}>
                      {item.margin === null || item.margin === undefined ? '-' : `${item.margin}%`}
                    </td>
                    <td style={{ textAlign: 'right', color: '#555', fontSize: 12 }}>{item.price}</td>
                    <td style={{ textAlign: 'center', whiteSpace: 'nowrap' }}>
                      {justOrdered.has(item.product_id) ? (
                        <span style={{ color: '#16a34a', fontWeight: 700, fontSize: 12 }}>✓ 発注済</span>
                      ) : (
                        <button
                          className="btn btn-primary"
                          style={{ padding: '4px 12px', fontSize: 12 }}
                          disabled={ordering === item.product_id || item.qty <= 0}
                          onClick={() => recordOrder(item)}
                        >
                          {ordering === item.product_id ? '...' : '発注'}
                        </button>
                      )}
                    </td>
                    <td style={{ whiteSpace: 'nowrap' }}>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                        <button className="btn btn-sm" style={{ fontSize: 11, padding: '2px 8px' }}
                          onClick={() => editLot(item)}>
                          {item.order_lot ? `ロット ${item.order_lot}` : 'ロット設定'}
                        </button>
                        <button className="btn btn-sm"
                          style={{ fontSize: 11, padding: '2px 8px',
                            background: item.discontinued ? '#e2e8f0' : '#fff', color: '#475569' }}
                          onClick={() => toggleDiscontinued(item)}>
                          {item.discontinued ? '発注を再開' : '今後発注しない'}
                        </button>
                        <button
                          className="btn btn-sm"
                          style={{ background: '#fee2e2', color: '#991b1b', fontSize: 11, padding: '2px 8px' }}
                          disabled={hiding === item.product_id}
                          onClick={() => hideProduct(item)}
                        >
                          {hiding === item.product_id ? '...' : '非表示'}
                        </button>
                      </div>
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
