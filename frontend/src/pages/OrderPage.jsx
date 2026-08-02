import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'
import { normalizeSearch } from '../searchUtil'

const POLL_INTERVAL = 3000 // 3秒ごとにポーリング

export default function OrderPage() {
  const qc = useQueryClient()
  const [tab, setTab] = useState('order')
  const [selected, setSelected] = useState(null)
  const [exporting, setExporting] = useState(false)
  const [error, setError] = useState('')
  const [qtyOverrides, setQtyOverrides] = useState({})
  const [ordering, setOrdering] = useState(null)
  const [justOrdered, setJustOrdered] = useState(new Set())
  const [search, setSearch] = useState('')
  const [onlyRecommended, setOnlyRecommended] = useState(true)

  // バックグラウンドジョブ管理
  const [jobId, setJobId] = useState(null)
  const [jobStatus, setJobStatus] = useState('idle') // idle | running | done | error
  const [jobElapsed, setJobElapsed] = useState(0)
  const [rawItems, setRawItems] = useState([])
  const pollRef = useRef(null)

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  const startFetch = async (force = false) => {
    if (force) sessionStorage.removeItem('order_items')
    setJobStatus('running')
    setError('')
    setRawItems([])
    setSelected(null)
    setQtyOverrides({})
    try {
      const res = await api.post(`/orders/preview/start?force=${force}`)
      const id = res.data.job_id
      setJobId(id)
      pollRef.current = setInterval(async () => {
        try {
          const status = await api.get(`/orders/preview/status/${id}`)
          setJobElapsed(status.data.elapsed)
          if (status.data.status === 'done') {
            stopPolling()
            const items = status.data.result || []
            setRawItems(items)
            sessionStorage.setItem('order_items', JSON.stringify(items))
            setJobStatus('done')
          } else if (status.data.status === 'error') {
            stopPolling()
            setError(status.data.error || 'SP-APIデータ取得に失敗しました')
            setJobStatus('error')
          }
        } catch {
          stopPolling()
          setError('ステータス取得に失敗しました')
          setJobStatus('error')
        }
      }, POLL_INTERVAL)
    } catch {
      setJobStatus('error')
      setError('データ取得の開始に失敗しました')
    }
  }

  // 機能追加でitemの項目が増えたら、古い形のキャッシュは捨てて取り直す。
  // sessionStorageはハードリロードでも残るため、これが無いと再計算を押すまで
  // 新しい列（成長率・作業中など）が空のままになる。
  const REQUIRED_FIELDS = ['growth_rate', 'processing', 'needs_order']

  // マウント時：sessionStorageにキャッシュがあれば即表示、なければ取得
  useEffect(() => {
    const cached = sessionStorage.getItem('order_items')
    if (cached) {
      try {
        const parsed = JSON.parse(cached)
        const isFresh = parsed.length === 0
          || REQUIRED_FIELDS.every(f => f in parsed[0])
        if (isFresh) {
          setRawItems(parsed)
          setJobStatus('done')
          return () => {}
        }
        sessionStorage.removeItem('order_items')
      } catch {
        sessionStorage.removeItem('order_items')
      }
    }
    startFetch()
    return () => stopPolling()
  }, [])

  const allItems = rawItems.map((item) => ({
    ...item,
    qty: qtyOverrides[item.product_id] ?? item.qty,
  }))

  // 発注推奨のみ / 全商品 の切替 ＋ SKU・商品名での絞り込み
  const items = allItems.filter(item => {
    if (onlyRecommended && !item.needs_order) return false
    if (!search) return true
    const q = normalizeSearch(search)
    return normalizeSearch(item.sku || '').includes(q) || normalizeSearch(item.name || '').includes(q)
  })

  const recommendedCount = allItems.filter(i => i.needs_order).length

  const { data: history = [] } = useQuery({
    queryKey: ['orderHistory'],
    queryFn: () => api.get('/orders/history').then(r => r.data),
    enabled: tab === 'history',
  })

  const deleteHistory = useMutation({
    mutationFn: (id) => api.delete(`/orders/history/${id}`),
    onSuccess: () => qc.invalidateQueries(['orderHistory']),
  })

  // FBA納品プランと突合した「納品済みとみなせる発注」の候補
  const [checking, setChecking] = useState(false)
  const [candidates, setCandidates] = useState(null)
  const [pickedIds, setPickedIds] = useState(new Set())
  const [marking, setMarking] = useState(false)

  const checkDelivered = async () => {
    setChecking(true)
    setError('')
    try {
      const res = await api.get('/orders/delivery-candidates')
      if (res.data.error) { setError(res.data.error); setCandidates(null) }
      else {
        setCandidates(res.data)
        // 発注数を満たしている分だけ初期チェック。部分一致は手動判断に委ねる
        setPickedIds(new Set(res.data.candidates.filter(c => c.full_match).map(c => c.id)))
      }
    } catch {
      setError('納品状況の確認に失敗しました')
    } finally {
      setChecking(false)
    }
  }

  const markShipped = async () => {
    if (!pickedIds.size) return
    setMarking(true)
    try {
      await api.post('/orders/mark-shipped', { ids: [...pickedIds] })
      setCandidates(null)
      setPickedIds(new Set())
      qc.invalidateQueries(['orderHistory'])
      sessionStorage.removeItem('order_items')  // 発注済の数が変わるので再取得させる
    } catch {
      setError('納品済みの記録に失敗しました')
    } finally {
      setMarking(false)
    }
  }

  const updateQty = (productId, val) => {
    setQtyOverrides(prev => ({ ...prev, [productId]: Number(val) }))
  }

  const currentSelected = selected ?? new Set()

  const toggleSelect = (productId) => {
    setSelected(prev => {
      const base = prev ?? new Set()
      const next = new Set(base)
      next.has(productId) ? next.delete(productId) : next.add(productId)
      return next
    })
  }

  // 全選択は「今表示されている行」に対して働く
  const allDisplayedChecked = items.length > 0 && items.every(it => currentSelected.has(it.product_id))

  const toggleAll = () => {
    setSelected(allDisplayedChecked ? new Set() : new Set(items.map(it => it.product_id)))
  }

  const handleExport = async () => {
    // フィルタ・検索で今は隠れている行も、チェック済みなら出力対象に含める
    const targets = allItems.filter(item => currentSelected.has(item.product_id) && item.qty > 0)
    if (!targets.length) { setError('選択された商品がないか、発注数が0です'); return }
    setExporting(true)
    try {
      const res = await api.post('/orders/export', { items: targets }, { responseType: 'blob' })
      const url = window.URL.createObjectURL(new Blob([res.data]))
      const a = document.createElement('a')
      a.href = url
      a.download = `${new Date().toISOString().slice(0,10).replace(/-/g,'')}_order.xlsx`
      a.click()
      window.URL.revokeObjectURL(url)
      qc.invalidateQueries(['orderHistory'])
      setQtyOverrides({})
      setSelected(null)
    } catch {
      setError('Excelの出力に失敗しました')
    } finally {
      setExporting(false)
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

  const handleRefetch = () => {
    stopPolling()
    startFetch(true)  // 再計算ボタンはキャッシュを強制クリア
  }

  const daysBadge = (days) => {
    if (days < 30) return <span className="badge badge-danger">{days}日</span>
    if (days < 60) return <span className="badge badge-warn">{days}日</span>
    return <span className="badge badge-ok">{days}日</span>
  }

  // 件数・合計も「表示中か否か」ではなくチェック状態を基準にする
  const selectedItems = allItems.filter(item => currentSelected.has(item.product_id) && item.qty > 0)
  const totalYuan = selectedItems.reduce((s, i) => s + i.qty * i.price, 0)
  const isLoading = jobStatus === 'running' || jobStatus === 'idle'

  const toggleBtn = (
    <button
      onClick={() => setOnlyRecommended(v => !v)}
      style={{
        padding: '8px 18px', fontSize: 14, fontWeight: 700, borderRadius: 24, border: 'none', cursor: 'pointer',
        background: onlyRecommended ? '#ea580c' : '#e2e8f0',
        color: onlyRecommended ? '#fff' : '#374151',
        boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
      }}
    >
      {onlyRecommended ? `発注推奨のみ（${recommendedCount}件）` : `全商品（${allItems.length}件）`}
    </button>
  )

  return (
    <div>
      <h1>📦 発注管理</h1>

      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        <button
          className={`btn ${tab === 'order' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setTab('order')}
        >発注推奨リスト</button>
        <button
          className={`btn ${tab === 'history' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setTab('history')}
        >発注済みリスト</button>
      </div>

      {tab === 'order' && (
        <>
          <div className="card">
            <p style={{ marginBottom: 14, color: '#555', fontSize: 13 }}>
              Amazon SP-APIから在庫・売上データを取得し、推奨発注数を自動計算します。<br />
              チェックを入れた商品だけExcelに出力され、発注済みリストに記録されます。<br />
              個別に発注する場合は各行の「<b>発注</b>」ボタンを押すと、その商品だけが発注済みリストに記録されます。
            </p>
            <div className="top-actions">
              <button className="btn btn-secondary" onClick={handleRefetch} disabled={isLoading}>
                {isLoading ? '取得中...' : '🔄 再計算'}
              </button>
              {items.length > 0 && (
                <button className="btn btn-success" onClick={handleExport} disabled={exporting}>
                  {exporting ? '生成中...' : `📥 Excelダウンロード（${selectedItems.length}件）`}
                </button>
              )}
            </div>
            {error && <p className="error-msg">{error}</p>}
          </div>

          {/* 表示切替＋検索 */}
          {!isLoading && jobStatus === 'done' && (
            <div style={{ display: 'flex', gap: 12, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
              {toggleBtn}
              <input
                type="text" placeholder="SKU・商品名で絞り込み"
                value={search} onChange={e => setSearch(e.target.value)}
                style={{ width: 280 }}
              />
            </div>
          )}

          {isLoading && (
            <div className="card" style={{ textAlign: 'center', color: '#555', padding: 40 }}>
              <div style={{ fontSize: 32, marginBottom: 12 }}>⏳</div>
              <p style={{ fontWeight: 600, marginBottom: 8 }}>SP-APIからデータを取得中...</p>
              <p style={{ fontSize: 13, color: '#888' }}>
                Amazon SP-APIから全商品の在庫・売上データを取得しています。<br />
                キャッシュがあれば数秒で終わりますが、期限切れの場合は<br />
                Amazon側のレート制限のため<b>7〜8分</b>かかります。このまま開いてお待ちください。
              </p>
              {jobElapsed > 0 && (
                <p style={{ fontSize: 13, color: '#aaa', marginTop: 8 }}>経過時間: {jobElapsed}秒</p>
              )}
            </div>
          )}

          {jobStatus === 'error' && !isLoading && (
            <div className="card" style={{ textAlign: 'center', color: '#c00', padding: 40 }}>
              <div style={{ fontSize: 32, marginBottom: 8 }}>⚠️</div>
              <p>データ取得に失敗しました。再計算ボタンで再試行してください。</p>
            </div>
          )}

          {!isLoading && jobStatus === 'done' && items.length > 0 && (
            <div className="card">
              <h2>{onlyRecommended ? '発注推奨リスト' : '全商品リスト'}（{items.length}件）</h2>
              {/* スクロールしても見出し行が残るよう、楽天(在庫・損益)と同じsticky-tableを使う */}
              <div className="sticky-table-wrap">
                <table className="sticky-table">
                  <thead>
                    <tr>
                      <th style={{ width: 36, cursor: 'pointer' }} onClick={toggleAll}>
                        <input type="checkbox"
                          checked={allDisplayedChecked}
                          onChange={toggleAll}
                          onClick={e => e.stopPropagation()}
                        />
                      </th>
                      <th>SKU</th>
                      <th>商品名</th>
                      <th>色/サイズ</th>
                      <th>残日数</th>
                      <th>販売可能</th>
                      <th>納品中</th>
                      <th title="Amazon倉庫で入出荷作業中。まだ販売可能になっていない在庫">作業中</th>
                      <th>全在庫</th>
                      <th>発注済</th>
                      <th>日販</th>
                      <th>成長率</th>
                      <th>発注数</th>
                      <th>単価(元)</th>
                      <th>小計(元)</th>
                      <th>発注</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((item) => {
                      const isChecked = currentSelected.has(item.product_id)
                      const rowBg = isChecked ? '#eff6ff' : item.needs_order ? '#fff7ed' : undefined
                      return (
                      <tr key={item.product_id} style={{ background: rowBg }}>
                        <td
                          style={{ textAlign: 'center', cursor: 'pointer' }}
                          onClick={() => toggleSelect(item.product_id)}
                        >
                          <input type="checkbox"
                            checked={isChecked}
                            onChange={() => toggleSelect(item.product_id)}
                            onClick={e => e.stopPropagation()}
                          />
                        </td>
                        <td style={{ fontFamily: 'monospace', fontSize: 12 }}>{item.sku}</td>
                        <td style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {item.name}
                        </td>
                        <td style={{ fontSize: 12, color: '#666' }}>{[item.color, item.size].filter(Boolean).join(' / ')}</td>
                        <td>{daysBadge(item.days_left)}</td>
                        <td style={{ textAlign: 'right', fontWeight: 600 }}>{item.available}</td>
                        <td style={{ textAlign: 'right', color: item.inbound > 0 ? '#2563eb' : '#bbb' }}>{item.inbound || '-'}</td>
                        <td
                          style={{ textAlign: 'right', color: item.processing > 0 ? '#d97706' : '#bbb' }}
                          title={item.processing > 0 ? 'Amazon倉庫で入出荷作業中。まだ販売できません' : undefined}
                        >{item.processing || '-'}</td>
                        <td style={{ textAlign: 'right', color: '#666' }}>{item.stock}</td>
                        <td style={{ textAlign: 'right', color: item.ordered > 0 ? '#e94560' : '#bbb', fontWeight: item.ordered > 0 ? 600 : 400 }}>
                          {item.ordered > 0 ? item.ordered : '-'}
                        </td>
                        <td style={{ textAlign: 'right' }}>{item.daily}</td>
                        <td style={{ textAlign: 'right' }}>
                          <span style={{
                            color: item.growth_rate > 0 ? '#16a34a' : item.growth_rate < 0 ? '#dc2626' : '#999',
                            fontWeight: 600,
                          }}>
                            {item.growth_rate ? `${item.growth_rate > 0 ? '+' : ''}${item.growth_rate}%` : '—'}
                          </span>
                        </td>
                        <td>
                          <input
                            type="number"
                            className="qty-input"
                            min={0}
                            value={item.qty}
                            onChange={e => updateQty(item.product_id, e.target.value)}
                          />
                        </td>
                        <td style={{ textAlign: 'right' }}>{item.price}</td>
                        <td style={{ textAlign: 'right', fontWeight: 600 }}>
                          {isChecked ? (item.qty * item.price).toFixed(0) : '-'}
                        </td>
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
                      </tr>
                      )
                    })}
                  </tbody>
                  <tfoot>
                    <tr>
                      <td colSpan={14} style={{ textAlign: 'right', fontWeight: 700, paddingTop: 12 }}>合計（選択分）</td>
                      <td style={{ textAlign: 'right', fontWeight: 700 }}>
                        {totalYuan.toFixed(0)} 元
                      </td>
                      <td></td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            </div>
          )}

          {!isLoading && jobStatus === 'done' && items.length === 0 && (
            <div className="card empty-state">
              <div style={{ fontSize: 40 }}>{search ? '🔍' : '✅'}</div>
              <p>
                {search
                  ? '検索条件に一致する商品はありません。'
                  : onlyRecommended
                  ? '現在、発注が必要な商品はありません。'
                  : '商品がありません。'}
              </p>
            </div>
          )}

          {!isLoading && jobStatus === 'done' && (
            <div style={{ fontSize: 12, color: '#999', marginTop: 8 }}>
              ※ <span style={{ color: '#ea580c', fontWeight: 700 }}>オレンジ行</span> = 推奨発注数が1以上 → 発注タイミング
            </div>
          )}
        </>
      )}

      {tab === 'history' && (
        <>
        <div className="card" style={{ marginBottom: 16 }}>
          <p style={{ marginBottom: 12, color: '#555', fontSize: 13 }}>
            FBAへの発送実績と照合し、すでに納品済みとみられる発注を探します。<br />
            納品済みにすると発注管理の「発注済」から外れ、在庫の二重計上がなくなります。
          </p>
          <button className="btn btn-secondary" onClick={checkDelivered} disabled={checking}>
            {checking ? '確認中...' : '🔍 納品済みの発注を確認'}
          </button>
          {error && <p className="error-msg">{error}</p>}

          {candidates && candidates.candidates.length === 0 && (
            <p style={{ marginTop: 12, color: '#666', fontSize: 13 }}>
              納品プランと一致する発注はありませんでした。
            </p>
          )}

          {candidates && candidates.candidates.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <div style={{ fontWeight: 700, marginBottom: 8 }}>
                納品済みとみられる発注（{candidates.candidates.length}件）
              </div>
              <table style={{ fontSize: 13 }}>
                <thead>
                  <tr>
                    <th style={{ width: 36 }}></th>
                    <th>SKU</th>
                    <th>発注日</th>
                    <th style={{ textAlign: 'right' }}>発注数</th>
                    <th style={{ textAlign: 'right' }}>充当数</th>
                    <th>対応する納品</th>
                    <th>判定</th>
                  </tr>
                </thead>
                <tbody>
                  {candidates.candidates.map(c => (
                    <tr key={c.id} style={{ background: pickedIds.has(c.id) ? '#eff6ff' : undefined }}>
                      <td style={{ textAlign: 'center' }}>
                        <input type="checkbox"
                          checked={pickedIds.has(c.id)}
                          onChange={() => setPickedIds(prev => {
                            const next = new Set(prev)
                            next.has(c.id) ? next.delete(c.id) : next.add(c.id)
                            return next
                          })}
                        />
                      </td>
                      <td style={{ fontFamily: 'monospace', fontSize: 12 }}>{c.sku}</td>
                      <td style={{ fontSize: 12, color: '#666' }}>{(c.ordered_at || '').slice(0, 10)}</td>
                      <td style={{ textAlign: 'right' }}>{c.qty}</td>
                      <td style={{ textAlign: 'right', fontWeight: 600 }}>{c.covered_qty}</td>
                      <td style={{ fontSize: 12, color: '#666' }}>
                        {(c.shipments || []).map((s, i) => (
                          <div key={i}>
                            {s.date} {s.qty}個
                            {s.received >= s.shipment_qty
                              ? <span style={{ color: '#16a34a', marginLeft: 4 }}>受領済</span>
                              : <span style={{ color: '#ea580c', marginLeft: 4 }}>受領待ち</span>}
                          </div>
                        ))}
                      </td>
                      <td style={{ fontSize: 12 }}>
                        {c.full_match
                          ? <span style={{ color: '#16a34a', fontWeight: 700 }}>一致</span>
                          : <span style={{ color: '#ea580c', fontWeight: 700 }}>一部のみ（{c.covered_qty}/{c.qty}）</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <div style={{ marginTop: 8, fontSize: 12, color: '#888' }}>
                ※ {candidates.match_since} 以降の納品のみを対象に、古い発注から順に割り当てています。<br />
                ※ <span style={{ color: '#ea580c' }}>受領待ち</span>はFBAへ発送済みですがAmazon側の受領がまだの分です。
                発注済から外すと、受領されるまでの間はどちらにも計上されません。
              </div>

              <div style={{ marginTop: 12 }}>
                <button className="btn btn-primary" onClick={markShipped} disabled={marking || pickedIds.size === 0}>
                  {marking ? '記録中...' : `チェックした${pickedIds.size}件を納品済みにする`}
                </button>
                <span style={{ marginLeft: 10, fontSize: 12, color: '#888' }}>
                  発注済みリストからは消えず、発注数の集計から外れます
                </span>
              </div>
            </div>
          )}
        </div>

        <div className="card">
          <h2>発注済みリスト（{history.length}件）</h2>
          {history.length === 0 ? (
            <div className="empty-state">
              <div style={{ fontSize: 40 }}>📋</div>
              <p>発注履歴がありません。</p>
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table>
                <thead>
                  <tr>
                    <th>発注日時</th>
                    <th>SKU</th>
                    <th>商品名</th>
                    <th>色/サイズ</th>
                    <th>発注数</th>
                    <th>単価(元)</th>
                    <th>小計(元)</th>
                    <th>状態</th>
                    <th>仕入URL</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {history.map(row => (
                    <tr key={row.id} style={{ opacity: row.status === 'shipped' ? 0.55 : 1 }}>
                      <td style={{ fontSize: 12, whiteSpace: 'nowrap', color: '#666' }}>
                        {new Date(row.ordered_at).toLocaleString('ja-JP', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
                      </td>
                      <td style={{ fontFamily: 'monospace', fontSize: 12 }}>{row.sku}</td>
                      <td style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{row.name}</td>
                      <td style={{ fontSize: 12, color: '#666' }}>{[row.color, row.size].filter(Boolean).join(' / ')}</td>
                      <td style={{ textAlign: 'right', fontWeight: 600 }}>{row.qty}</td>
                      <td style={{ textAlign: 'right' }}>{row.price}</td>
                      <td style={{ textAlign: 'right', fontWeight: 600 }}>{(row.qty * row.price).toFixed(0)}</td>
                      <td style={{ whiteSpace: 'nowrap', fontSize: 12 }}>
                        {row.status === 'shipped' ? (
                          <span style={{ color: '#16a34a', fontWeight: 700 }} title="発注数の集計から外れています">✓ 納品済</span>
                        ) : (
                          <span style={{ color: '#888' }}>未納品</span>
                        )}
                      </td>
                      <td>
                        {row.buy_url && (
                          <a href={row.buy_url} target="_blank" rel="noreferrer" style={{ color: '#e94560', fontSize: 12 }}>リンク</a>
                        )}
                      </td>
                      <td style={{ whiteSpace: 'nowrap' }}>
                        <button
                          className="btn btn-sm"
                          style={{ background: '#fee2e2', color: '#991b1b', whiteSpace: 'nowrap' }}
                          onClick={() => {
                            if (confirm(`${row.sku} を発注済みリストから外しますか？\n（入荷して納品済み、または誤発注・キャンセルの場合に押してください）`))
                              deleteHistory.mutate(row.id)
                          }}
                        >リストから外す</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <td colSpan={6} style={{ textAlign: 'right', fontWeight: 700, paddingTop: 12 }}>合計</td>
                    <td style={{ textAlign: 'right', fontWeight: 700 }}>
                      {history.reduce((s, r) => s + r.qty * r.price, 0).toFixed(0)} 元
                    </td>
                    <td></td>
                    <td></td>
                    <td></td>
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
        </div>
        </>
      )}
    </div>
  )
}
