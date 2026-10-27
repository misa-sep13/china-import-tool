import { useState, useEffect, useMemo } from 'react'
import api from '../api/client'

const STATUS_LABELS = { ordered: '発注済', arrived: '到着済', shipped: '配送依頼済' }
const STATUS_COLORS = { ordered: '#f59e0b', arrived: '#22c55e', shipped: '#6b7280' }
const SHIP_LABELS = { air: '航空便', sea: '船便', hold: '保留' }
const SHIP_COLORS = { air: '#ef4444', sea: '#3b82f6', hold: '#9ca3af' }

export default function FbaPlanPage() {
  const [orders, setOrders] = useState([])
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState('all')
  const [importing, setImporting] = useState(false)
  const [importResult, setImportResult] = useState(null)

  // FBA plan state
  const [planStatus, setPlanStatus] = useState('idle')
  const [planItems, setPlanItems] = useState([])
  const [planSettings, setPlanSettings] = useState(null)
  const [meta, setMeta] = useState({})
  const [planQtys, setPlanQtys] = useState({})
  const [excludes, setExcludes] = useState({})
  const [exporting, setExporting] = useState(false)
  const [creatingPlan, setCreatingPlan] = useState(false)
  const [createResult, setCreateResult] = useState(null)
  const [elapsed, setElapsed] = useState(0)
  // SKU順を既定にする。残日数順だと同じ商品の色違いが
  // 離れた行に出て、a07_black が見つからないということが起きた
  const [sortKey, setSortKey] = useState('sku')
  const [sortAsc, setSortAsc] = useState(true)

  const fetchOrders = async () => {
    setLoading(true)
    try {
      const { data } = await api.get('/fba-plan/orders')
      setOrders(data)
    } catch (e) {
      console.error(e)
    }
    setLoading(false)
  }

  useEffect(() => { fetchOrders() }, [])

  // 入庫済みの取り込み。もとはタオタロウのサイトでExcelを落として
  // ここへ上げ直していた。APIで同じものが取れるのでボタン1つにした
  const handleSyncArrived = async () => {
    setImporting(true)
    setImportResult(null)
    try {
      const { data } = await api.post('/fba-plan/sync-arrived')
      setImportResult(data)
      fetchOrders()
    } catch (err) {
      setImportResult({ error: err.response?.data?.detail || '取り込めませんでした' })
    }
    setImporting(false)
  }

  const handleStatusChange = async (id, newStatus) => {
    try {
      await api.post(`/fba-plan/orders/${id}/status`, { status: newStatus })
      fetchOrders()
    } catch (e) {
      console.error(e)
    }
  }

  const filteredOrders = useMemo(() => {
    if (tab === 'all') return orders
    return orders.filter(o => o.status === tab)
  }, [orders, tab])

  const statusCounts = useMemo(() => {
    const c = { ordered: 0, arrived: 0, shipped: 0 }
    for (const o of orders) c[o.status] = (c[o.status] || 0) + 1
    return c
  }, [orders])

  // ---- FBA Plan (配送依頼を出した商品の納品プラン) ----
  // 到着済はタオタロウの倉庫に届いただけで、FBAへ送るかどうかとは別。
  // 何を送るかは配送依頼を出した時点で決まっているので、そちらで絞る
  const arrivedOrders = useMemo(() => orders.filter(o => o.status === 'arrived'), [orders])
  const [planSid, setPlanSid] = useState(null)
  const [planSkus, setPlanSkus] = useState(null)
  const [sendQty, setSendQty] = useState({})
  const [skuMsg, setSkuMsg] = useState('')
  const [allItems, setAllItems] = useState([])
  // 入数で割り切れなかった行。切り上げているので注意を促す
  const [oddQty, setOddQty] = useState([])

  const pickPlanSendOrder = async (sid) => {
    setSkuMsg('配送依頼を読んでいます…')
    try {
      const { data } = await api.get(`/fba-plan/send-order/${sid}/skus`)
      setPlanSid(data.sid)
      setPlanSkus(data.skus)
      setSendQty(data.qty || {})
      setOddQty(data.odd || [])
      setSkuMsg(`便 ${data.sn || data.sid}　${data.skus.length}商品`
        + (data.unknown.length
          ? `（${data.unknown.length}件はSKUが分かりませんでした）` : ''))
    } catch (e) {
      setSkuMsg('読めませんでした：' + (e.response?.data?.detail || e.message))
    }
  }

  // 便を選び直したら、取得済みの在庫データをそのまま絞り直す
  useEffect(() => {
    if (!allItems.length) return
    const keep = planSkus ? new Set(planSkus)
      : new Set(arrivedOrders.map(o => o.sku))
    const filtered = allItems.filter(it => keep.has(it.sku))
    setPlanItems(filtered)
    const q = {}
    // 何を何個送るかは配送依頼を出した時点で決まっている。
    // 推奨ではなく、その数を最初から入れておく
    for (const it of filtered) q[it.sku] = sendQty[it.sku] ?? it.plan_qty
    setPlanQtys(q)
  }, [planSkus, allItems])

  const [planErr, setPlanErr] = useState('')
  const startPlanFetch = async (force = false) => {
    setPlanStatus('loading')
    setPlanErr('')
    setElapsed(0)
    try {
      const q = planSkus && planSkus.length
        ? `&skus=${encodeURIComponent(planSkus.join(','))}` : ''
      const { data } = await api.post(`/fba-plan/start?force=${force}${q}`)
      const jobId = data.job_id
      const timer = setInterval(async () => {
        try {
          const { data: st } = await api.get(`/fba-plan/status/${jobId}`)
          setElapsed(st.elapsed || 0)
          if (st.status === 'done' && st.result) {
            clearInterval(timer)
            const all = st.result.items || []
            setAllItems(all)
            const keep = planSkus ? new Set(planSkus)
              : new Set(arrivedOrders.map(o => o.sku))
            const filtered = all.filter(it => keep.has(it.sku))
            setPlanItems(filtered)
            setPlanSettings(st.result.settings || null)
            setMeta({
              sale_extra_days: st.result.sale_extra_days,
              target_stock_days: st.result.target_stock_days,
              lt_sea_total: st.result.lt_sea_total,
              lt_air_total: st.result.lt_air_total,
            })
            const initQtys = {}
            for (const it of filtered) initQtys[it.sku] = sendQty[it.sku] ?? it.plan_qty
            setPlanQtys(initQtys)
            setExcludes({})
            setPlanStatus('done')
          } else if (st.status === 'error') {
            clearInterval(timer)
            setPlanErr(st.error || 'Amazonから取れませんでした')
            setPlanStatus('error')
          } else if (st.status === 'not_found') {
            // 処理はサーバーのメモリに置いてあるので、デプロイで
            // 作り直されると消える。これを拾わないと、終わらない
            // 取得を延々と見ることになる
            clearInterval(timer)
            setPlanErr('取得が途中で消えました（デプロイなどでサーバーが入れ替わったとき）。もう一度押してください')
            setPlanStatus('error')
          } else if ((st.elapsed || 0) > 600) {
            clearInterval(timer)
            setPlanErr('10分たっても終わりませんでした。もう一度押してください')
            setPlanStatus('error')
          }
        } catch {
          clearInterval(timer)
          setPlanErr('通信が切れました。もう一度押してください')
          setPlanStatus('error')
        }
      }, 1500)
    } catch (e) {
      setPlanErr(e.response?.data?.detail || '取得を始められませんでした')
      setPlanStatus('error')
    }
  }

  const handleSort = (key) => {
    if (sortKey === key) setSortAsc(!sortAsc)
    else { setSortKey(key); setSortAsc(true) }
  }

  const sortedPlanItems = useMemo(() => {
    const list = planItems.filter(it => !excludes[it.sku])
    list.sort((a, b) => {
      let va = a[sortKey], vb = b[sortKey]
      if (sortKey === 'sku') {
        // a05 → a07 → a010 の順になるよう、数字は数字として比べる。
        // 文字だけで並べると a010 が a05 の前に来てしまう
        const r = String(va || '').localeCompare(String(vb || ''), 'ja',
          { numeric: true, sensitivity: 'base' })
        return sortAsc ? r : -r
      }
      if (typeof va === 'string') va = va.toLowerCase()
      if (typeof vb === 'string') vb = vb.toLowerCase()
      if (va < vb) return sortAsc ? -1 : 1
      if (va > vb) return sortAsc ? 1 : -1
      return 0
    })
    return list
  }, [planItems, excludes, sortKey, sortAsc])

  const totalPlanPieces = useMemo(() => {
    return sortedPlanItems.reduce((sum, it) => {
      if (it.ship_method === 'hold' || excludes[it.sku]) return sum
      return sum + (planQtys[it.sku] || 0) * it.set_size
    }, 0)
  }, [sortedPlanItems, planQtys, excludes])

  // Amazonへの納品プラン作成。作れるのはSKUと数量まで（箱詰めはタオタロウが決める）
  const handleCreateInboundPlan = async () => {
    const targets = sortedPlanItems
      .filter(it => (planQtys[it.sku] || 0) > 0 && it.ship_method !== 'hold')
      .map(it => ({
        sku: it.sku,
        fnsku: it.fnsku,
        plan_qty: planQtys[it.sku] || 0,
        set_size: it.set_size,
      }))
    if (!targets.length) {
      alert('納品数が1以上の商品がありません')
      return
    }
    const pieces = targets.reduce((s, t) => s + t.plan_qty * t.set_size, 0)
    const sets = targets.reduce((s, t) => s + t.plan_qty, 0)
    // 画面はセット数で扱うので、確認もセット数で出す。
    // バラの数と違う商品だけ、何個になるかをそえる
    const detail = targets.map(t => (
      t.set_size > 1
        ? `  ${t.sku}: ${t.plan_qty}セット（${t.plan_qty * t.set_size}個）`
        : `  ${t.sku}: ${t.plan_qty}セット`
    )).join('\n')
    if (!confirm(
      `Amazonに納品プランを作成します。\n\n${detail}\n\n` +
      `計 ${targets.length}SKU / ${sets}セット（${pieces}個）\n\n` +
      `作成後はセラーセントラルで商品ラベルをダウンロードしてください。`
    )) return

    setCreatingPlan(true)
    setCreateResult(null)
    try {
      const { data } = await api.post('/fba-plan/create-inbound-plan', { items: targets })
      setCreateResult(data)
    } catch (e) {
      setCreateResult({ error: e.response?.data?.detail || '納品プランの作成に失敗しました' })
    }
    setCreatingPlan(false)
  }

  const handleExport = async () => {
    const exportItems = sortedPlanItems
      .filter(it => (planQtys[it.sku] || 0) > 0 && it.ship_method !== 'hold')
      .map(it => ({
        sku: it.sku,
        fnsku: it.fnsku,
        plan_qty: planQtys[it.sku] || 0,
        set_size: it.set_size,
      }))
    if (!exportItems.length) {
      alert('納品数が1以上の商品がありません')
      return
    }
    setExporting(true)
    try {
      const res = await api.post('/fba-plan/export-excel', { items: exportItems }, { responseType: 'blob' })
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = `fba_plan_${new Date().toISOString().slice(0, 10).replace(/-/g, '')}.xlsx`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      alert('Excel出力に失敗しました')
    }
    setExporting(false)
  }

  // ---- 梱包情報（箱ごとの中身）----
  //
  // Amazonの納品プランは「何箱か」「各箱の3辺と重量」「どの箱に何が
  // 何個入っているか」が要る。配送依頼APIには箱の項目が無いが、
  // タオタロウのインボイスの箱シートに全部入っているので、そこから読む。
  const [sendOrders, setSendOrders] = useState(null)
  const [loadingSo, setLoadingSo] = useState(false)
  const [packing, setPacking] = useState(null)
  // 納品先（placement）。Amazonの新しい流れでは、箱の中身より
  // 先に「どのFCに分けて送るか」を決めないと先へ進めない
  const [placeOpts, setPlaceOpts] = useState([])
  const [placeMsg, setPlaceMsg] = useState('')
  const [placeResult, setPlaceResult] = useState(null)
  const [loadingPlace, setLoadingPlace] = useState(false)

  const loadPlacement = async () => {
    const planId = createResult?.inbound_plan_id
    if (!planId) return
    setLoadingPlace(true)
    setPlaceMsg('納品先の候補を出しています…（1分ほどかかります）')
    try {
      const { data } = await api.get(`/fba-plan/placement/${planId}`)
      const opts = data.options || []
      setPlaceOpts(opts)
      setPlaceMsg(opts.length ? '' : '候補がありませんでした')
    } catch (e) {
      setPlaceOpts([])
      setPlaceMsg(e.response?.data?.detail || '候補が取れませんでした')
    } finally {
      setLoadingPlace(false)
    }
  }

  const confirmPlacement = async (optId) => {
    if (!confirm('この納品先で確定します。確定すると変更できません。')) return
    setLoadingPlace(true)
    setPlaceMsg('確定しています…')
    try {
      const { data } = await api.post('/fba-plan/placement/confirm', {
        plan_id: createResult.inbound_plan_id, placement_option_id: optId,
      })
      setPlaceResult(data)
      setPlaceMsg('')
    } catch (e) {
      setPlaceMsg(e.response?.data?.detail || '確定できませんでした')
    } finally {
      setLoadingPlace(false)
    }
  }
  const [packErr, setPackErr] = useState('')
  const [loadingPack, setLoadingPack] = useState(false)

  // タオタロウのFBA指示書の備考を、マスタの「納品時の備考」で置き換える
  const [filling, setFilling] = useState(false)
  const [fillMsg, setFillMsg] = useState('')
  const fillNote = async (file) => {
    if (!file) return
    setFilling(true); setFillMsg('読み込んでいます…')
    try {
      const fd = new FormData()
      fd.append('file', file)
      const r = await api.post('/fba-plan/fill-taotaro-note', fd, {
        responseType: 'blob',
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      const url = URL.createObjectURL(r.data)
      const a = document.createElement('a')
      a.href = url
      a.download = file.name.replace(/\.xlsx?$/i, '') + '_note.xlsx'
      a.click()
      URL.revokeObjectURL(url)
      let rep = null
      try {
        rep = JSON.parse(decodeURIComponent(r.headers['x-fill-report'] || ''))
      } catch (e) { rep = null }
      setFillMsg(rep
        ? `備考を入れた ${rep['入れた'].length}件`
          + ` / 空にした ${rep['空にした'].length}件`
          + (rep['当たらなかった'].length
            ? ['', '当たらなかった行（触っていません）：']
              .concat(rep['当たらなかった']).join('\n') : '')
        : '書き換えたファイルを保存しました')
    } catch (e) {
      setFillMsg('うまくいきませんでした：'
        + (e.response?.data?.detail || e.message))
    } finally { setFilling(false) }
  }

  // 便から指示書を取ってきて、そのまま備考を入れ替える。
  // 手で落として選ぶ手間が消える（タオタロウの画面と同じ入口を使う）
  const fetchInstruction = async () => {
    if (!planSid) { setFillMsg('上で便を選んでください'); return }
    setFilling(true); setFillMsg('タオタロウから取ってきています…')
    try {
      const r = await api.get(`/fba-plan/send-order/${planSid}/instruction`,
        { responseType: 'blob' })
      const url = URL.createObjectURL(r.data)
      const a = document.createElement('a')
      a.href = url
      a.download = `FBA_${planSid}_note.xlsx`
      a.click()
      URL.revokeObjectURL(url)
      let rep = null
      try {
        rep = JSON.parse(decodeURIComponent(r.headers['x-fill-report'] || ''))
      } catch (e) { rep = null }
      setFillMsg(rep && rep['入れた']
        ? `備考を入れた ${rep['入れた'].length}件`
          + ` / 空にした ${rep['空にした'].length}件`
          + (rep['当たらなかった'].length
            ? ['', '当たらなかった行（触っていません）：']
              .concat(rep['当たらなかった']).join('\n') : '')
        : '指示書を保存しました')
    } catch (e) {
      let detail = e.response?.data?.detail
      if (e.response?.data instanceof Blob) {
        try { detail = JSON.parse(await e.response.data.text()).detail } catch (x) {}
      }
      setFillMsg('うまくいきませんでした：' + (detail || e.message))
    }
    setFilling(false)
  }

  // 逆向き。Excelに手で書いた備考を、マスタの「納品時の備考」に覚えさせる
  const readNote = async (file) => {
    if (!file) return
    setFilling(true); setFillMsg('読み込んでいます…')
    try {
      const fd = new FormData()
      fd.append('file', file)
      const { data } = await api.post('/fba-plan/read-taotaro-note', fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setFillMsg([
        `マスタに入れた ${data['入れた'].length}件`
          + ` / 元から同じ ${data['元から同じ'].length}件`,
      ].concat(data['入れた'].map(x => '　' + x))
        .concat(data['当たらなかった'].length
          ? ['', '当たらなかった行：'].concat(
            data['当たらなかった'].map(x => '　' + x)) : [])
        .join('\n'))
    } catch (e) {
      setFillMsg('うまくいきませんでした：'
        + (e.response?.data?.detail || e.message))
    } finally { setFilling(false) }
  }

  const loadSendOrders = async () => {
    setLoadingSo(true); setPackErr('')
    try {
      const { data } = await api.get('/taotaro/send-orders', { params: { limit: 30 } })
      setSendOrders(data.items || [])
    } catch (e) {
      setPackErr(e.response?.data?.detail || '配送依頼を取れませんでした')
    }
    setLoadingSo(false)
  }

  // 箱の中身をAmazonへ直接入れる。CSVをセラーセントラルに貼る代わり
  const [sendingPack, setSendingPack] = useState(false)
  const [sendPackMsg, setSendPackMsg] = useState('')
  const sendPacking = async () => {
    const planId = createResult?.inbound_plan_id
    if (!planId) { setSendPackMsg('先に納品プランを作ってください'); return }
    setSendingPack(true); setSendPackMsg('Amazonへ入れています…')
    try {
      const { data } = await api.post('/fba-plan/packing/send',
        { plan_id: planId, sid: packing.sid })
      if (data.ok) {
        setSendPackMsg(`${data.sent_boxes}箱を入れました`
          + (data.skipped_boxes
            ? `（${data.skipped_boxes}箱は今回の納品プランに無いので飛ばしました）` : ''))
      } else {
        const lines = []
        if (data.split?.length) {
          lines.push('1箱に別グループの商品が混ざっています（Amazonが受け付けません）：')
          data.split.forEach(x => lines.push(`　${x.box_no}番 ${x.skus.join('、')}`))
        }
        if (data.unknown?.length) {
          lines.push('納品プランに無い商品が入っています：')
          data.unknown.forEach(x => lines.push(`　${x.box_no}番 ${x.skus.join('、')}`))
        }
        setSendPackMsg(lines.join('\n'))
      }
    } catch (e) {
      setSendPackMsg('うまくいきませんでした：'
        + (e.response?.data?.detail || e.message))
    }
    setSendingPack(false)
  }

  // 配送依頼をかける前の計算し直し。発注時に必要だった数と、
  // いま必要な数は違う。倉庫の在庫を航空便・船便・倉庫に振り分ける
  const [split, setSplit] = useState(null)
  const [splitting, setSplitting] = useState(false)
  const [splitErr, setSplitErr] = useState('')
  const loadSplit = async () => {
    setSplitting(true); setSplitErr(''); setSplit(null)
    try {
      const { data } = await api.get('/fba-plan/restock-split')
      setSplit(data)
    } catch (e) {
      setSplitErr(e.response?.data?.detail || e.message)
    }
    setSplitting(false)
  }

  // 商品ラベル。納品プランが無くても刷れる（FNSKUはSKUごとに決まっている）
  const [labelSkip, setLabelSkip] = useState(0)
  const [labelMsg, setLabelMsg] = useState('')
  const [labeling, setLabeling] = useState(false)
  const makeLabels = async () => {
    if (!planSid) { setLabelMsg('上で便を選んでください'); return }
    setLabeling(true); setLabelMsg('作っています…')
    try {
      const r = await api.get(
        `/fba-plan/send-order/${planSid}/labels?skip=${labelSkip || 0}`,
        { responseType: 'blob' })
      const url = URL.createObjectURL(r.data)
      const a = document.createElement('a')
      a.href = url
      a.download = `labels_${planSid}.pdf`
      a.click()
      URL.revokeObjectURL(url)
      let rep = null
      try {
        rep = JSON.parse(decodeURIComponent(r.headers['x-fill-report'] || ''))
      } catch (e) { rep = null }
      setLabelMsg(rep
        ? ['刷りました：'].concat(rep['刷った'].map(x => '　' + x))
          .concat(rep['刷れなかった'].length
            ? ['', '刷れなかったもの：'].concat(
              rep['刷れなかった'].map(x => '　' + x)) : []).join('\n')
        : 'PDFを保存しました')
    } catch (e) {
      let detail = e.response?.data?.detail
      if (e.response?.data instanceof Blob) {
        try { detail = JSON.parse(await e.response.data.text()).detail } catch (x) {}
      }
      setLabelMsg('うまくいきませんでした：' + (detail || e.message))
    }
    setLabeling(false)
  }

  const loadPacking = async (sid) => {
    setLoadingPack(true); setPackErr(''); setPacking(null)
    try {
      const { data } = await api.get(`/fba-plan/packing/${sid}`)
      setPacking(data)
    } catch (e) {
      setPackErr(e.response?.data?.detail || '梱包情報を読めませんでした')
    }
    setLoadingPack(false)
  }

  // Amazonの梱包情報CSV。1行＝「箱番号・SKU・個数」。
  // 箱の寸法と重量は箱の先頭行にだけ入れる（Amazonの様式に合わせる）
  const downloadPackingCsv = () => {
    if (!packing) return
    const head = ['箱番号', 'SKU', 'FNSKU', '個数', '長さcm', '幅cm', '高さcm', '重量kg', '商品名']
    const lines = [head.join(',')]
    packing.boxes.forEach(b => {
      b.items.forEach((it, i) => {
        lines.push([
          b.box_no, it.sku || '', it.fnsku || '', it.qty,
          i === 0 ? (b.length_cm ?? '') : '',
          i === 0 ? (b.width_cm ?? '') : '',
          i === 0 ? (b.height_cm ?? '') : '',
          i === 0 ? (b.weight_kg ?? '') : '',
          `"${String(it.name || '').replace(/"/g, '""')}"`,
        ].join(','))
      })
    })
    // Excelで開くとUTF-8が化けるのでBOMを付ける
    const blob = new Blob(['﻿' + lines.join('\r\n')], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `packing_${packing.sid}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  const SortHeader = ({ label, field, style }) => (
    <th style={{ ...thStyle, cursor: 'pointer', userSelect: 'none', ...style }}
      onClick={() => handleSort(field)}>
      {label} {sortKey === field ? (sortAsc ? '▲' : '▼') : ''}
    </th>
  )

  return (
    <div>
      <h1>🚢 FBA納品プラン</h1>

      {/* やること。番号は下のカードと合わせる。
          タオタロウ側は手作業、Amazon側はこのツールで完結させる */}
      <div className="card" style={{ marginBottom: 16, background: '#f8fafc' }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: '#0f172a', marginBottom: 10 }}>
          やること（上から順に）
        </div>
        <ol style={{ margin: 0, paddingLeft: 20, fontSize: 13, lineHeight: 2 }}>
          <li>
            タオタロウで<b>配送依頼を出す</b>
            <span style={{ color: '#64748b' }}>　（FBA送付先は未定のままでOK）</span>
          </li>
          <li>この画面の上で<b>その便を選ぶ</b>　→ 以下はすべてその便が対象</li>
          <li><b>① 商品ラベル</b>を刷る</li>
          <li>
            タオタロウから<b>FBA指示書</b>を落として<b>② 備考を入れる</b>
            <span style={{ color: '#64748b' }}>　→ 買付の指示が消え、納品の指示だけが入る</span>
          </li>
          <li><b>ラベルと指示書を一緒に</b><b>WeChat</b>へ送る</li>
          <li>下の表で納品数を決めて<b>③ Amazonに納品プランを作成</b></li>
          <li>インボイス作成完了のお知らせ → <b>支払い</b></li>
          <li>配送ラベル（納品先FCの住所）を<b>WeChat</b>へ送る</li>
          <li>
            梱包が終わったら<b>④ 箱の中身をAmazonに入れる</b>
            <span style={{ color: '#64748b' }}>　→ セラーセントラルに貼る作業は要りません</span>
          </li>
        </ol>
        <div style={{ marginTop: 10, padding: '8px 12px', background: '#fffbeb',
          border: '1px solid #fde68a', borderRadius: 6, fontSize: 12,
          color: '#92400e', lineHeight: 1.8 }}>
          <b>なぜ送付先を未定で出すか：</b>
          配送依頼にFBA送付先が要るが、納品先FCはAmazonで納品プランを作らないと
          決まらない。先に知ろうとしてセラーセントラルの梱包を飛ばすと、
          配送モードがパレット輸送（LTL）かトラック配送（FTL）に限定され、
          船便・航空便が選べなくなる。
          <br />
          <b>④だけ後になるのは：</b>箱に詰める前は箱の中身が無いためです。
          インボイスができるまで待ちます。
        </div>
      </div>

      {/* 配送依頼をかける前に、いまの売れ行きで計算し直す。
          発注時に必要だった数より減っていることがある */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center',
          flexWrap: 'wrap' }}>
          <b style={{ fontSize: 15 }}>⓪ 何を何個送るか計算し直す</b>
          <span style={{ fontSize: 12, color: '#64748b' }}>
            タオタロウの倉庫にある在庫を、いまの売れ行きで振り分けます
          </span>
          <button className="btn btn-primary" style={{ marginLeft: 'auto', fontSize: 13 }}
            onClick={loadSplit} disabled={splitting}>
            {splitting ? '計算中…' : '🧮 計算する'}
          </button>
        </div>
        <div style={{ fontSize: 12, color: '#64748b', marginTop: 8, lineHeight: 1.8 }}>
          <b>航空便</b>は船便が届く日までに欠品する分だけ、
          <b>船便</b>は目標在庫日数に足りない残り、
          のこりは<b>倉庫に残します</b>。
          同じSKUで<b>楽天にも出している商品</b>は、中国の在庫が1つの山なので、
          先に楽天ぶんを取り置いてから残りを振り分けます。
          FNSKUもASINも無い商品は、楽天ぶんとして発注したものなので<b>出しません</b>。
          無料保管は入庫から90日なので、期限が近いものには印を付けます。
          <b>配送依頼を出す前</b>に使ってください。
        </div>
        {splitErr && (
          <div style={{ fontSize: 12, color: '#b91c1c', marginTop: 8 }}>{splitErr}</div>
        )}
        {split && split.items?.length === 0 && (
          <div style={{ fontSize: 13, color: '#92400e', marginTop: 10 }}>
            {split.note || '振り分ける在庫がありません'}
          </div>
        )}
        {split && split.items?.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <div style={{ fontSize: 12, color: '#64748b', marginBottom: 6 }}>
              目標 {split.target_days}日分　／　船便 {split.lt_sea}日　航空便 {split.lt_air}日
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', fontSize: 13, borderCollapse: 'collapse' }}>
                <thead><tr style={{ background: '#f8fafc' }}>
                  {['SKU', '商品名', '日販', 'FBA', '残日数', '中国在庫',
                    '楽天に取り置き', '航空便', '船便', '倉庫に残す',
                    '入庫から'].map(h => (
                    <th key={h} style={{ ...thStyle, textAlign: 'left' }}>{h}</th>
                  ))}
                </tr></thead>
                <tbody>
                  {split.items.map(x => (
                    <tr key={x.sku} style={{ borderBottom: '1px solid #f1f5f9',
                      background: x.warn_storage ? '#fffbeb' : 'transparent' }}>
                      <td style={{ ...tdStyle, fontFamily: 'monospace', fontSize: 12 }}>
                        {x.sku}
                      </td>
                      <td style={{ ...tdStyle, maxWidth: 240, overflow: 'hidden',
                        textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={x.name}>
                        {x.name}
                      </td>
                      <td style={{ ...tdStyle, textAlign: 'right' }}>{x.daily}</td>
                      <td style={{ ...tdStyle, textAlign: 'right' }}>{x.fba_available}</td>
                      <td style={{ ...tdStyle, textAlign: 'right' }}>
                        {x.fba_days === null ? '—' : `${x.fba_days}日`}
                      </td>
                      <td style={{ ...tdStyle, textAlign: 'right' }}>{x.china_pieces}</td>
                      <td style={{ ...tdStyle, textAlign: 'right',
                        color: x.rakuten_reserve ? '#9d174d' : '#cbd5e1' }}
                        title={x.rakuten_daily !== null && x.rakuten_daily !== undefined
                          ? `楽天 日販${x.rakuten_daily} / 在庫${x.rakuten_stock}`
                          : '楽天には出していません'}>
                        {x.rakuten_daily === null || x.rakuten_daily === undefined
                          ? '—' : x.rakuten_reserve}
                      </td>
                      <td style={{ ...tdStyle, textAlign: 'right', fontWeight: 700,
                        color: x.air_pieces ? '#b91c1c' : '#cbd5e1' }}>{x.air_pieces}</td>
                      <td style={{ ...tdStyle, textAlign: 'right', fontWeight: 700,
                        color: x.sea_pieces ? '#1d4ed8' : '#cbd5e1' }}>{x.sea_pieces}</td>
                      <td style={{ ...tdStyle, textAlign: 'right', fontWeight: 700,
                        color: x.keep_pieces ? '#334155' : '#cbd5e1' }}>{x.keep_pieces}</td>
                      <td style={{ ...tdStyle, textAlign: 'right',
                        color: x.warn_storage ? '#b45309' : '#64748b' }}>
                        {x.oldest_days === null ? '—' : `${x.oldest_days}日`}
                        {x.warn_storage && (
                          <span title="無料保管が切れます。残すなら保管料がかかります">
                            　⚠ 残り{x.free_days_left}日
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* 便はここで1回だけ選ぶ。以前はカードごとに選び直していた */}
      <div className="card" style={{ marginBottom: 16, background: '#eff6ff',
        border: '1px solid #bfdbfe' }}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center',
          flexWrap: 'wrap' }}>
          <b style={{ fontSize: 15, color: '#1e40af' }}>どの便を納品しますか</b>
          <button className="btn btn-secondary" style={{ fontSize: 13 }}
            onClick={loadSendOrders} disabled={loadingSo}>
            {loadingSo ? '読み込み中…' : '便を読み込む'}
          </button>
          {sendOrders && (
            <select style={{ fontSize: 13, padding: '4px 8px', minWidth: 220 }}
              value={planSid || ''}
              onChange={e => e.target.value && pickPlanSendOrder(Number(e.target.value))}>
              <option value="">— 便を選ぶ —</option>
              {sendOrders.map(so => (
                <option key={so.sid} value={so.sid}>
                  {so.sn || so.sid}　{so.state_label || ''}
                  {so.count_weight ? `　${so.count_weight}kg` : ''}
                </option>
              ))}
            </select>
          )}
          {skuMsg && (
            <span style={{ fontSize: 12, color: '#1e40af' }}>{skuMsg}</span>
          )}
        </div>
        {!planSid && (
          <div style={{ fontSize: 12, color: '#64748b', marginTop: 8 }}>
            便を選ぶと、①ラベル・③納品プラン・④箱の中身が、その便の商品だけになります。
          </div>
        )}
      </div>

      {/* 商品ラベル。セラーセントラルで納品プランを作らないと落とせなかったが、
          FNSKUは納品プランと関係ないので、ここで刷って代行会社へ早く渡す */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center',
          flexWrap: 'wrap' }}>
          <b style={{ fontSize: 15 }}>① 商品ラベル（FNSKU）</b>
          <span style={{ fontSize: 12, color: '#64748b' }}>
            配送依頼に載っている商品ぶんを、数量どおり刷ります
          </span>
        </div>
        {planSid && (
          <div style={{ display: 'flex', gap: 10, alignItems: 'center',
            flexWrap: 'wrap', marginTop: 10 }}>
            <label style={{ fontSize: 12, color: '#64748b' }}>
              シートの使いかけ
              <input type="number" min="0" max="23" value={labelSkip}
                onChange={e => setLabelSkip(Number(e.target.value))}
                style={{ width: 56, marginLeft: 6, fontSize: 13, padding: '2px 6px' }} />
              <span style={{ marginLeft: 4 }}>枚ぶん空ける</span>
            </label>
            <button className="btn btn-primary" style={{ fontSize: 13 }}
              onClick={makeLabels} disabled={labeling}>
              {labeling ? '作っています…' : '⬇ ラベルPDFを作る'}
            </button>
          </div>
        )}
        <div style={{ fontSize: 12, color: '#64748b', marginTop: 8, lineHeight: 1.8 }}>
          用紙はA4 24面（66×33.9mm、エーワン28362など）。
          1枚にFNSKUのバーコード・FNSKU・自社SKU・商品名・新品が入ります。
          <b>納品プランを作る前に刷れます。</b>
        </div>
        {labelMsg && (
          <div style={{ fontSize: 12, marginTop: 8, whiteSpace: 'pre-wrap',
            color: labelMsg.startsWith('うまく') ? '#b91c1c' : '#334155' }}>
            {labelMsg}
          </div>
        )}
      </div>


      {/* タオタロウのFBA指示書。備考に買付のときの指示が残っていて、
          納品の段階では終わっている作業なので現場が迷う。
          商品マスタの「納品時の備考」で置き換える */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center',
          flexWrap: 'wrap' }}>
          <b style={{ fontSize: 15 }}>② FBA指示書に備考を入れる</b>
          <span style={{ fontSize: 12, color: '#64748b' }}>
            選んだ便の指示書をタオタロウから取ってきて、備考を入れ替えて返します
          </span>
          <button className="btn btn-primary" style={{ marginLeft: 'auto', fontSize: 13 }}
            onClick={fetchInstruction} disabled={filling || !planSid}>
            {filling ? '取得中…' : '📄 便から指示書を取ってくる'}
          </button>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center',
          flexWrap: 'wrap', marginTop: 10 }}>
          <span style={{ fontSize: 12, color: '#64748b' }}>
            取ってこれないときは、手で落とした指示書を選んでください
          </span>
          <input type="file" accept=".xlsx,.xlsm" disabled={filling}
            onChange={e => { fillNote(e.target.files?.[0]); e.target.value = '' }}
            style={{ marginLeft: 'auto', fontSize: 12 }} />
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center',
          flexWrap: 'wrap', marginTop: 10, paddingTop: 10,
          borderTop: '1px solid #e2e8f0' }}>
          <b style={{ fontSize: 13 }}>逆に、書いてある備考をマスタに覚えさせる</b>
          <span style={{ fontSize: 12, color: '#64748b' }}>
            手で書き込んだ依頼書を選ぶと、備考を「納品時の備考」に入れます
          </span>
          <input type="file" accept=".xlsx,.xlsm" disabled={filling}
            onChange={e => { readNote(e.target.files?.[0]); e.target.value = '' }}
            style={{ marginLeft: 'auto', fontSize: 12 }} />
        </div>
        <div style={{ fontSize: 12, color: '#64748b', marginTop: 8,
          lineHeight: 1.8 }}>
          買付のときの指示（全量開封検品・写真撮影など）は消して、
          商品マスタの<b>「納品時の備考」</b>だけを入れます。
          突き合わせはタオタロウの商品IDで行い、無ければ商品情報（仕様）で当てます。
          当たらなかった行は<b>触りません</b>。
        </div>
        {fillMsg && (
          <div style={{ fontSize: 12, marginTop: 8, whiteSpace: 'pre-wrap',
            color: fillMsg.startsWith('うまく') ? '#b91c1c' : '#334155' }}>
            {fillMsg}
          </div>
        )}
      </div>


      {/* 配送依頼を出した商品のFBA納品プラン。
          到着済が1件も無くても、便を選べるように常に出す */}
      {true && (
        <div style={{ borderTop: '2px solid #e2e8f0', paddingTop: 24 }}>
          <h2 style={{ marginBottom: 12 }}>③ Amazonに納品プランを作成</h2>

          <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 16, flexWrap: 'wrap' }}>
            {!planSid && (
              <span style={{ fontSize: 12, color: '#b45309' }}>
                上で便を選ぶと押せます
              </span>
            )}
            {planStatus === 'loading' && (
              <button className="btn btn-secondary" style={{ fontSize: 12 }}
                onClick={() => { setPlanStatus('idle'); setPlanErr('') }}>
                やめる
              </button>
            )}
            {planErr && (
              <span style={{ fontSize: 12, color: '#b91c1c' }}>{planErr}</span>
            )}
            <button className="btn btn-primary" onClick={() => startPlanFetch(true)} disabled={planStatus === 'loading' || !planSid}>
              {planStatus === 'loading' ? `取得中... (${elapsed.toFixed(0)}秒)` : '🔄 SP-APIから在庫取得'}
            </button>
            {planStatus === 'done' && (
              <>
                <button className="btn" onClick={handleCreateInboundPlan} disabled={creatingPlan}
                  style={{ background: '#ea580c', color: '#fff', fontWeight: 700 }}
                  title="この内容でAmazonに納品プランを作成します">
                  {creatingPlan ? '作成中...' : '③ Amazonに納品プランを作成'}
                </button>
                <button className="btn" onClick={handleExport} disabled={exporting}
                  style={{ background: '#059669', color: '#fff' }}>
                  {exporting ? '出力中...' : '📥 納品プランExcel出力'}
                </button>
                <span style={{ fontSize: 13, color: '#6b7280' }}>
                  合計出荷数: <strong style={{ color: '#1e40af' }}>{totalPlanPieces}個</strong>
                </span>
              </>
            )}
          </div>

          {oddQty.length > 0 && (
            <div style={{ marginTop: 10, padding: '10px 14px', background: '#fffbeb',
              border: '1px solid #fcd34d', borderRadius: 6, fontSize: 13,
              color: '#92400e', lineHeight: 1.9 }}>
              <b>⚠ 入数で割り切れないものがあります</b>
              <span style={{ marginLeft: 8, fontSize: 12 }}>
                実際に作れるセット数を入れてあります。余りは次の便へ
              </span>
              {oddQty.map(o => (
                <div key={o.sku} style={{ fontSize: 12, marginTop: 3 }}>
                  <b>{o.sku}</b>：{o.units}個 ÷ {o.set_size}個1セット
                  → <b>{o.sets}セット</b>（{o.left}個余ります）
                </div>
              ))}
            </div>
          )}

          {planStatus === 'done' && planItems.length === 0 && (
            <div style={{ padding: '10px 14px', background: '#fffbeb',
              border: '1px solid #fde68a', borderRadius: 6, fontSize: 13,
              color: '#92400e', marginBottom: 16 }}>
              在庫は取れましたが、表に出す商品がありません。
              {planSkus
                ? 'この便の商品が、Amazonの在庫（SP-API）に見つかりませんでした。SKUの表記が違う可能性があります。'
                : '上で便を選んでください。便を選ばないときは「到着済」の印が付いた商品だけが出ます。'}
            </div>
          )}

          {/* 納品プラン作成の結果。作成後にやることを続けて示す */}
          {createResult && (
            <div className="card" style={{
              marginBottom: 16,
              borderLeft: `4px solid ${createResult.error ? '#ef4444' : '#16a34a'}`,
            }}>
              {createResult.error ? (
                <div style={{ color: '#dc2626', fontSize: 13 }}>{createResult.error}</div>
              ) : (
                <>
                  <div style={{ fontWeight: 700, color: '#166534', marginBottom: 8 }}>
                    納品プランを作成しました（{createResult.sku_count}SKU / {createResult.total_pieces}個）
                  </div>
                  <div style={{ fontSize: 12, color: '#475569', marginBottom: 10 }}>
                    プランID: <span style={{ fontFamily: 'monospace' }}>{createResult.inbound_plan_id}</span>
                  </div>
                  <div style={{ fontSize: 13, color: '#334155', marginBottom: 10 }}>
                    この段階ではまだ納品（FBA番号）はできていません。
                    次の<b>納品先を決める</b>を済ませると納品ができ、
                    セラーセントラルにも出てきます。
                  </div>

                  <div style={{ borderTop: '1px solid #e2e8f0', paddingTop: 12 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
                      <b style={{ fontSize: 14 }}>③-2 納品先を決める</b>
                      <span style={{ fontSize: 12, color: '#64748b' }}>
                        どのFCに、いくつの納品に分けて送るか
                      </span>
                      <button className="btn" onClick={loadPlacement} disabled={loadingPlace}
                        style={{ marginLeft: 'auto' }}>
                        {loadingPlace ? '処理中…' : '候補を出す'}
                      </button>
                    </div>

                    {placeMsg && (
                      <div style={{ fontSize: 12, color: '#b45309', marginBottom: 8,
                        whiteSpace: 'pre-wrap' }}>{placeMsg}</div>
                    )}

                    {!placeResult && placeOpts.map(o => (
                      <div key={o.placement_option_id} style={{
                        display: 'flex', alignItems: 'center', gap: 12,
                        padding: '8px 10px', border: '1px solid #e2e8f0',
                        borderRadius: 6, marginBottom: 6, fontSize: 13,
                      }}>
                        <span><b>{o.shipment_count}</b>納品に分かれます</span>
                        <span style={{ color: '#475569' }}>
                          手数料: {o.fee ? `${o.fee} ${o.currency}` : 'なし'}
                        </span>
                        <button className="btn btn-primary" style={{ marginLeft: 'auto' }}
                          disabled={loadingPlace}
                          onClick={() => confirmPlacement(o.placement_option_id)}>
                          これで確定
                        </button>
                      </div>
                    ))}

                    {placeResult && (
                      <div style={{ fontSize: 13 }}>
                        <div style={{ color: '#166534', fontWeight: 700, marginBottom: 6 }}>
                          納品先を確定しました（{placeResult.shipments?.length || 0}納品）
                        </div>
                        {(placeResult.shipments || []).map(sh => (
                          <div key={sh.shipment_id} style={{ color: '#334155' }}>
                            {sh.confirmation_id || sh.shipment_id}
                            {sh.destination ? `（${sh.destination}）` : ''}
                          </div>
                        ))}
                        <div style={{ marginTop: 8, color: '#475569' }}>
                          このあと④（箱の中身）に進めます。
                        </div>
                      </div>
                    )}
                  </div>

                  <a href={createResult.seller_central_url} target="_blank" rel="noreferrer"
                    style={{
                      display: 'inline-block', marginTop: 12,
                      padding: '8px 16px', background: '#1e40af',
                      color: '#fff', borderRadius: 6, fontSize: 13, fontWeight: 600,
                      textDecoration: 'none',
                    }}>
                    セラーセントラルで開く →
                  </a>
                </>
              )}
            </div>
          )}

          {planStatus === 'loading' && (
            <div className="card" style={{ textAlign: 'center', padding: 40, color: '#6b7280' }}>
              SP-APIからデータ取得中... ({elapsed.toFixed(0)}秒)
            </div>
          )}

          {planStatus === 'error' && (
            <div className="card" style={{ textAlign: 'center', padding: 40, color: '#ef4444' }}>
              データ取得に失敗しました。もう一度お試しください。
            </div>
          )}

          {planStatus === 'done' && (
            <>
              {planSettings && (
                <div className="card" style={{ marginBottom: 16 }}>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 24, fontSize: 13 }}>
                    <div>
                      <span style={{ color: '#6b7280' }}>目標在庫: </span>
                      <strong>{meta.target_stock_days}日</strong>
                    </div>
                    <div>
                      <span style={{ color: '#6b7280' }}>船便合計: </span>
                      <strong>{meta.lt_sea_total}日</strong>
                    </div>
                    <div>
                      <span style={{ color: '#6b7280' }}>航空便合計: </span>
                      <strong>{meta.lt_air_total}日</strong>
                    </div>
                    <div>
                      <span style={{ color: '#6b7280' }}>航空便閾値: </span>
                      <strong>≤{planSettings.air_threshold_days}日</strong>
                    </div>
                  </div>
                </div>
              )}

              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                  <thead>
                    <tr style={{ background: '#f8fafc', borderBottom: '2px solid #e2e8f0' }}>
                      <SortHeader label="SKU" field="sku" />
                      <th style={thStyle}>商品名</th>
                      <SortHeader label="日販" field="daily" style={{ textAlign: 'right' }} />
                      <SortHeader label="FBA" field="fba_available" style={{ textAlign: 'right' }} />
                      <th style={{ ...thStyle, textAlign: 'right' }}>パイプライン</th>
                      <SortHeader label="全体残日数" field="pipeline_days" style={{ textAlign: 'right' }} />
                      <th style={{ ...thStyle, textAlign: 'center' }}>判定</th>
                      <th style={{ ...thStyle, textAlign: 'right' }}>推奨(セット)</th>
                      <th style={{ ...thStyle, textAlign: 'right' }}>配送依頼(セット)</th>
                      <th style={{ ...thStyle, textAlign: 'right' }}>納品数(セット)</th>
                      <th style={{ ...thStyle, textAlign: 'center' }}>除外</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortedPlanItems.map(it => {
                      const daysColor = it.pipeline_days <= (planSettings?.air_threshold_days || 18)
                        ? '#ef4444'
                        : it.pipeline_days <= 30 ? '#f59e0b' : '#374151'
                      return (
                        <tr key={it.sku} style={{ borderBottom: '1px solid #f1f5f9' }}>
                          <td style={tdStyle}>
                            <span style={{ fontFamily: 'monospace', fontSize: 12 }}>{it.sku}</span>
                          </td>
                          <td style={{ ...tdStyle, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {it.name}
                          </td>
                          <td style={{ ...tdStyle, textAlign: 'right', fontFamily: 'monospace' }}>
                            {it.daily.toFixed(2)}
                          </td>
                          <td style={{ ...tdStyle, textAlign: 'right' }}>{it.fba_available}</td>
                          <td style={{ ...tdStyle, textAlign: 'right', fontWeight: 600 }}>{it.pipeline_stock}</td>
                          <td style={{ ...tdStyle, textAlign: 'right', color: daysColor, fontWeight: 600 }}>
                            {it.pipeline_days > 9000 ? '∞' : `${it.pipeline_days}日`}
                          </td>
                          <td style={{ ...tdStyle, textAlign: 'center' }}>
                            <span style={{
                              display: 'inline-block', padding: '2px 8px', borderRadius: 4, fontSize: 11,
                              fontWeight: 700, color: '#fff',
                              background: SHIP_COLORS[it.ship_method] || '#9ca3af',
                            }}>
                              {SHIP_LABELS[it.ship_method] || it.ship_method}
                            </span>
                          </td>
                          <td style={{ ...tdStyle, textAlign: 'right', color: '#6b7280' }}>
                            {it.recommended_sets}
                          </td>
                          <td style={{ ...tdStyle, textAlign: 'right', fontWeight: 600 }}>
                            {sendQty[it.sku] ?? '-'}
                          </td>
                          <td style={{ ...tdStyle, textAlign: 'right' }}>
                            <input type="number" min={0}
                              value={planQtys[it.sku] ?? it.plan_qty}
                              onChange={e => setPlanQtys(p => ({ ...p, [it.sku]: Math.max(0, parseInt(e.target.value) || 0) }))}
                              style={{ width: 60, textAlign: 'right', padding: '2px 4px', border: '1px solid #d1d5db', borderRadius: 4 }}
                            />
                          </td>
                          <td style={{ ...tdStyle, textAlign: 'center' }}>
                            <input type="checkbox"
                              checked={!!excludes[it.sku]}
                              onChange={e => setExcludes(p => ({ ...p, [it.sku]: e.target.checked }))}
                            />
                          </td>
                        </tr>
                      )
                    })}
                    {sortedPlanItems.length === 0 && (
                      <tr>
                        <td colSpan={10} style={{ ...tdStyle, textAlign: 'center', color: '#9ca3af', padding: 32 }}>
                          到着済み商品のSP-APIデータがありません
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}

      {/* 梱包情報。Amazonの納品プランで「箱に何を入れたか」を入れるところに使う。
          タオタロウのインボイスから読むので、手で数える必要がない */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <b style={{ fontSize: 15 }}>④ 梱包情報（箱の中身）</b>
          <span style={{ fontSize: 12, color: '#64748b' }}>
            インボイスから箱の3辺・重量・中身を読んで、納品プランに入れます
          </span>
          <button className="btn btn-secondary" style={{ marginLeft: 'auto', fontSize: 13 }}
            onClick={() => loadPacking(planSid)} disabled={loadingPack || !planSid}>
            {loadingPack ? '読み込み中…' : '箱の中身を読む'}
          </button>
        </div>

        {packErr && (
          <div style={{ marginTop: 10, padding: '8px 12px', background: '#fef2f2',
            border: '1px solid #fecaca', borderRadius: 6, fontSize: 13, color: '#b91c1c' }}>
            {packErr}
          </div>
        )}

        {packing && (
          <div style={{ marginTop: 12 }}>
            <div style={{ display: 'flex', gap: 10, alignItems: 'center',
              flexWrap: 'wrap', marginBottom: 10 }}>
              <b style={{ fontSize: 14 }}>
                配送依頼 {packing.sid}　／　{packing.box_count}箱
              </b>
              {packing.unknown_count > 0 && (
                <span style={{ fontSize: 12, color: '#b45309', fontWeight: 600 }}>
                  ⚠ 商品マスタと結びつかない行が {packing.unknown_count}件あります
                  （SKUが空のまま出ます）
                </span>
              )}
              <button className="btn btn-primary" style={{ marginLeft: 'auto', fontSize: 13 }}
                onClick={sendPacking} disabled={sendingPack}>
                {sendingPack ? '入れています…' : '📤 Amazonに箱の中身を入れる'}
              </button>
              <button className="btn btn-secondary" style={{ fontSize: 13 }}
                onClick={downloadPackingCsv}>⬇ CSVで保存</button>
              <button className="btn btn-secondary" style={{ fontSize: 13 }}
                onClick={() => { setPacking(null); setPackErr('') }}>閉じる</button>
            </div>
            {sendPackMsg && (
              <div style={{ fontSize: 12, marginBottom: 10, whiteSpace: 'pre-wrap',
                color: sendPackMsg.startsWith('うまく') ? '#b91c1c' : '#334155' }}>
                {sendPackMsg}
              </div>
            )}

            {packing.boxes.map(b => (
              <div key={b.box_no} style={{ marginBottom: 10, border: '1px solid #e2e8f0',
                borderRadius: 6, overflow: 'hidden' }}>
                <div style={{ padding: '6px 12px', background: '#f8fafc',
                  fontSize: 13, fontWeight: 600 }}>
                  箱 {b.box_no}
                  <span style={{ color: '#64748b', fontWeight: 400, marginLeft: 10 }}>
                    {b.length_cm}×{b.width_cm}×{b.height_cm}cm　{b.weight_kg}kg
                  </span>
                </div>
                <table style={{ width: '100%', fontSize: 13, borderCollapse: 'collapse' }}>
                  <tbody>
                    {b.items.map((it, i) => (
                      <tr key={i} style={{ borderTop: '1px solid #f1f5f9' }}>
                        <td style={{ padding: '5px 12px', fontWeight: 600, width: 160 }}>
                          {it.sku || <span style={{ color: '#b45309' }}>（未登録）</span>}
                        </td>
                        <td style={{ padding: '5px 12px', color: '#64748b', width: 140 }}>
                          {it.fnsku || '—'}
                        </td>
                        <td style={{ padding: '5px 12px', textAlign: 'right', width: 80 }}>
                          {it.qty}個
                        </td>
                        <td style={{ padding: '5px 12px', color: '#94a3b8' }}>{it.name}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          </div>
        )}
      </div>


      {/* 普段は使わないもの。画面を短くするために畳んでおく */}
      <details className="card" style={{ marginBottom: 16 }}>
        <summary style={{ cursor: 'pointer', fontSize: 14, fontWeight: 700 }}>
          その他（入庫の取り込み・発注済みリスト）
        </summary>
        <div style={{ marginTop: 12 }}>

      {/* ①入庫済みの取り込み。
          もとはタオタロウのサイトでExcelを落として、ここへ上げ直していた。
          APIで同じものが取れるので、ボタン1つにした */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <button
            onClick={handleSyncArrived}
            disabled={importing}
            style={{
              padding: '9px 18px', background: importing ? '#cbd5e1' : '#ea580c',
              color: '#fff', border: 'none', borderRadius: 6,
              cursor: importing ? 'default' : 'pointer', fontWeight: 700, fontSize: 14,
            }}
          >
            {importing ? '取り込み中…' : '① 入庫済みを取り込む'}
          </button>
          <span style={{ fontSize: 12, color: '#64748b' }}>
            タオタロウで倉庫に届いた商品に「到着済み」の印を付けます（Excelは要りません）
          </span>
          {importResult && !importResult.error && (
            <span style={{ fontSize: 13, marginLeft: 'auto' }}>
              <strong style={{ color: '#16a34a' }}>{importResult.matched}件</strong> 取り込みました
              {importResult.already > 0 && (
                <span style={{ color: '#9ca3af', marginLeft: 8 }}>
                  （{importResult.already}件はもう到着済）
                </span>
              )}
              {importResult.unmatched?.length > 0 && (
                <span style={{ color: '#9ca3af', marginLeft: 8 }}>
                  （{importResult.unmatched.length}件は発注済みリストに見当たらず）
                </span>
              )}
            </span>
          )}
          {importResult?.error && (
            <span style={{ color: '#ef4444', fontSize: 13, marginLeft: 'auto' }}>
              {importResult.error}
            </span>
          )}
        </div>
      </div>

      {/* 発注済みリストに見当たらなかった行。無いときは出さない
          （空の枠だけが残っていた） */}
      {importResult?.unmatched?.length > 0 && (
      <div className="card" style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 12, color: '#64748b', lineHeight: 1.8 }}>
          <b style={{ color: '#334155' }}>発注済みリストに無い入庫</b>
          ：タオタロウの倉庫には届いているのに、このツールの発注済みリストに
          同じ1688のURLの行が見つからなかったものです。
          タオタロウで直接発注したものが、たいていここに出ます。
          <b>見るだけの一覧</b>で、ここから配送依頼は作れません。
          配送依頼は<b>発注管理 →「配送依頼を出す」</b>で出します。
        </div>
        {true && (
          <details style={{ marginTop: 8, fontSize: 12 }}>
            <summary style={{ cursor: 'pointer', color: '#f59e0b' }}>
              未照合 {importResult.unmatched.length}件を表示
            </summary>
            <div style={{ overflowX: 'auto', marginTop: 4 }}>
              <table style={{ fontSize: 12, borderCollapse: 'collapse', width: '100%' }}>
                <thead>
                  <tr style={{ background: '#fef3c7' }}>
                    <th style={thStyle}>タオタロウID</th>
                    <th style={thStyle}>商品名</th>
                    <th style={thStyle}>色/サイズ</th>
                    <th style={thStyle}>数量</th>
                  </tr>
                </thead>
                <tbody>
                  {importResult.unmatched.map((u, i) => (
                    <tr key={i} style={{ borderBottom: '1px solid #f1f5f9' }}>
                      <td style={tdStyle}>{u.taotaro_order_id}</td>
                      <td style={{ ...tdStyle, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {u.name_cn}
                      </td>
                      <td style={tdStyle}>{[u.color, u.size].filter(Boolean).join(' / ')}</td>
                      <td style={{ ...tdStyle, textAlign: 'right' }}>{u.qty}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        )}
      </div>
      )}


      {/* ステータスフィルタ */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 16, flexWrap: 'wrap' }}>
        <button
          onClick={() => setTab('all')}
          style={{
            padding: '6px 16px', fontSize: 13, borderRadius: 4, border: '1px solid #d1d5db',
            background: tab === 'all' ? '#1e40af' : '#fff',
            color: tab === 'all' ? '#fff' : '#374151',
            cursor: 'pointer', fontWeight: 600,
          }}
        >
          全て ({orders.length})
        </button>
        {['ordered', 'arrived'].map(s => (
          <button key={s}
            onClick={() => setTab(s)}
            style={{
              padding: '6px 16px', fontSize: 13, borderRadius: 4, border: '1px solid #d1d5db',
              background: tab === s ? STATUS_COLORS[s] : '#fff',
              color: tab === s ? '#fff' : '#374151',
              cursor: 'pointer', fontWeight: 600,
            }}
          >
            {STATUS_LABELS[s]} ({statusCounts[s] || 0})
          </button>
        ))}
      </div>


      {/* 発注済みリスト */}
      {loading ? (
        <div className="card" style={{ textAlign: 'center', padding: 40, color: '#6b7280' }}>読込中...</div>
      ) : orders.length === 0 ? (
        <div className="card" style={{ textAlign: 'center', padding: 40, color: '#9ca3af' }}>
          <div style={{ fontSize: 40 }}>📋</div>
          <p>発注済みの商品がありません。<br />発注管理で商品を発注してください。</p>
        </div>
      ) : (
        <div style={{ overflowX: 'auto', marginBottom: 24 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ background: '#f8fafc', borderBottom: '2px solid #e2e8f0' }}>
                <th style={thStyle}>ステータス</th>
                <th style={thStyle}>発注日</th>
                <th style={thStyle}>SKU</th>
                <th style={thStyle}>商品名</th>
                <th style={thStyle}>色/サイズ</th>
                <th style={{ ...thStyle, textAlign: 'right' }}>数量</th>
                <th style={{ ...thStyle, textAlign: 'right' }}>単価(元)</th>
                <th style={thStyle}>仕入URL</th>
                <th style={thStyle}>操作</th>
              </tr>
            </thead>
            <tbody>
              {filteredOrders.map(o => (
                <tr key={o.id} style={{
                  borderBottom: '1px solid #f1f5f9',
                  background: o.status === 'arrived' ? '#f0fdf4' : 'transparent',
                }}>
                  <td style={tdStyle}>
                    <span style={{
                      display: 'inline-block', padding: '2px 8px', borderRadius: 4, fontSize: 11,
                      fontWeight: 700, color: '#fff',
                      background: STATUS_COLORS[o.status] || '#9ca3af',
                    }}>
                      {STATUS_LABELS[o.status] || o.status}
                    </span>
                  </td>
                  <td style={{ ...tdStyle, fontSize: 12, whiteSpace: 'nowrap', color: '#666' }}>
                    {o.ordered_at ? new Date(o.ordered_at).toLocaleDateString('ja-JP', { month: '2-digit', day: '2-digit' }) : '-'}
                  </td>
                  <td style={{ ...tdStyle, fontFamily: 'monospace', fontSize: 12 }}>{o.sku}</td>
                  <td style={{ ...tdStyle, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {o.name}
                  </td>
                  <td style={{ ...tdStyle, fontSize: 12, color: '#666' }}>
                    {[o.color, o.size].filter(Boolean).join(' / ')}
                  </td>
                  <td style={{ ...tdStyle, textAlign: 'right', fontWeight: 600 }}>{o.qty}</td>
                  <td style={{ ...tdStyle, textAlign: 'right' }}>{o.price}</td>
                  <td style={tdStyle}>
                    {o.buy_url && (
                      <a href={o.buy_url} target="_blank" rel="noreferrer" style={{ color: '#e94560', fontSize: 12 }}>リンク</a>
                    )}
                  </td>
                  <td style={{ ...tdStyle, whiteSpace: 'nowrap' }}>
                    {o.status === 'ordered' && (
                      <button className="btn btn-sm"
                        style={{ background: '#dcfce7', color: '#166534', fontSize: 11 }}
                        onClick={() => handleStatusChange(o.id, 'arrived')}
                      >到着済みにする</button>
                    )}
                    {o.status === 'arrived' && (
                      <button className="btn btn-sm"
                        style={{ background: '#e0e7ff', color: '#3730a3', fontSize: 11 }}
                        onClick={() => handleStatusChange(o.id, 'shipped')}
                      >配送依頼済み</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

        </div>
      </details>

    </div>
  )
}

const thStyle = {
  padding: '8px 10px',
  textAlign: 'left',
  fontSize: 12,
  fontWeight: 600,
  color: '#6b7280',
  whiteSpace: 'nowrap',
}
const tdStyle = {
  padding: '6px 10px',
  color: '#374151',
}
