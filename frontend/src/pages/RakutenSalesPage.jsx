import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'

const fmtYen = (v) => v == null ? '—' : `¥${Math.round(Number(v) || 0).toLocaleString()}`
const fmtNum = (v) => Number(v || 0).toLocaleString()
const fmtPct = (v) => v == null ? '—' : `${Number(v).toFixed(1)}%`

function currentMonth() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

export default function RakutenSalesPage() {
  const qc = useQueryClient()
  const [period, setPeriod] = useState(currentMonth())
  const [selectedPeriod, setSelectedPeriod] = useState('')
  const [level, setLevel] = useState('parent')
  const [search, setSearch] = useState('')
  const [files, setFiles] = useState({})

  const monthsQuery = useQuery({
    queryKey: ['rakuten-sales-months'],
    queryFn: () => api.get('/rakuten/sales/months').then(r => r.data.months || []),
  })

  const activePeriod = selectedPeriod || monthsQuery.data?.[0]?.period || period

  const summaryQuery = useQuery({
    queryKey: ['rakuten-sales-summary', activePeriod, level],
    queryFn: () => api.get('/rakuten/sales/summary', { params: { period: activePeriod, level } }).then(r => r.data),
    enabled: !!activePeriod,
  })

  const importMutation = useMutation({
    mutationFn: async () => {
      const fd = new FormData()
      fd.append('period', period)
      const orderFiles = files.order_files || []
      if (orderFiles.length === 0) throw new Error('受注データを選択してください')
      for (const f of orderFiles) fd.append('order_file', f)
      if (files.rpp_file) fd.append('rpp_file', files.rpp_file)
      if (files.coupon_ad_file) fd.append('coupon_ad_file', files.coupon_ad_file)
      if (files.affiliate_file) fd.append('affiliate_file', files.affiliate_file)
      const res = await api.post('/rakuten/sales/import', fd)
      return res.data
    },
    onSuccess: (data) => {
      setSelectedPeriod(data.import.period)
      qc.invalidateQueries(['rakuten-sales-months'])
      qc.invalidateQueries(['rakuten-sales-summary'])
    },
  })

  const rows = summaryQuery.data?.rows || []
  const filteredRows = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return rows
    return rows.filter(r =>
      String(r.product_key || '').toLowerCase().includes(q) ||
      String(r.sku_key || '').toLowerCase().includes(q) ||
      String(r.product_name || '').toLowerCase().includes(q)
    )
  }, [rows, search])

  const totalAd = rows.reduce((sum, r) => sum + Number(r.rpp_cost || 0) + Number(r.coupon_ad_cost || 0), 0)
  const totals = summaryQuery.data?.totals || {}
  const importInfo = summaryQuery.data?.import

  const onFile = (key, multiple) => (e) => {
    if (multiple) {
      setFiles(prev => ({ ...prev, [key]: Array.from(e.target.files || []) }))
    } else {
      setFiles(prev => ({ ...prev, [key]: e.target.files?.[0] || null }))
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        <h1 style={{ marginBottom: 0 }}>📈 楽天 売上管理</h1>
        <select value={activePeriod} onChange={e => setSelectedPeriod(e.target.value)} style={{ width: 160 }}>
          {monthsQuery.data?.length ? monthsQuery.data.map(m => (
            <option key={m.period} value={m.period}>{m.period}</option>
          )) : <option value={period}>{period}</option>}
        </select>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="form-grid" style={{ gridTemplateColumns: '130px repeat(4, minmax(170px, 1fr)) auto', alignItems: 'end', marginBottom: 0 }}>
          <div className="form-group">
            <label>対象月</label>
            <input type="month" value={period} onChange={e => setPeriod(e.target.value)} />
          </div>
          <FileInput label="受注データ" required multiple onChange={onFile('order_files', true)} />
          <FileInput label="RPP" onChange={onFile('rpp_file')} />
          <FileInput label="クーアド" onChange={onFile('coupon_ad_file')} />
          <FileInput label="アフィ" onChange={onFile('affiliate_file')} />
          <button
            className="btn btn-primary"
            onClick={() => importMutation.mutate()}
            disabled={importMutation.isPending}
            style={{ height: 36, whiteSpace: 'nowrap' }}
          >
            {importMutation.isPending ? '取込中...' : '⬆️ 取込'}
          </button>
        </div>
        {importMutation.error && (
          <div className="error-msg" style={{ marginTop: 10 }}>
            {importMutation.error.response?.data?.detail || importMutation.error.message}
          </div>
        )}
        {importMutation.data && (
          <div style={{ marginTop: 10, color: '#16a34a', fontSize: 13, fontWeight: 600 }}>
            {importMutation.data.import.period} 取込済み（親{importMutation.data.parent_count}件 / SKU{importMutation.data.sku_count}件）
          </div>
        )}
        <ImportGuide />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(150px, 1fr))', gap: 12, marginBottom: 16 }}>
        <Metric label="売上" value={fmtYen(totals.sales)} tone="#2563eb" />
        <Metric label="利益" value={fmtYen(totals.profit)} tone={Number(totals.profit || 0) >= 0 ? '#16a34a' : '#dc2626'} />
        <Metric label="利益率" value={fmtPct(totals.profit_rate)} tone={Number(totals.profit_rate || 0) >= 20 ? '#16a34a' : '#d97706'} />
        <Metric label="販売数" value={fmtNum(totals.units)} tone="#334155" />
        <Metric label="広告費" value={fmtYen(totalAd)} tone="#7c3aed" />
      </div>

      <div className="card" style={{ padding: '12px 16px', marginBottom: 16, display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <div style={{ display: 'inline-flex', gap: 6 }}>
          <button className={`btn ${level === 'parent' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setLevel('parent')}>親商品</button>
          <button className={`btn ${level === 'sku' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setLevel('sku')}>SKU別</button>
        </div>
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="商品番号・SKU・商品名"
          style={{ width: 260, marginLeft: 'auto' }}
        />
        {importInfo && (
          <span style={{ color: '#64748b', fontSize: 12 }}>
            受注{importInfo.order_rows}行 / RPP{importInfo.rpp_rows}行 / クーアド{importInfo.coupon_ad_rows}行 / アフィ{importInfo.affiliate_rows}行
          </span>
        )}
      </div>

      <div className="card" style={{ padding: 0 }}>
        <div className="sticky-table-wrap">
          <table className="sticky-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr>
                <th>{level === 'parent' ? '商品管理番号' : '親商品'}</th>
                {level === 'sku' && <th>SKU</th>}
                <th>商品名</th>
                <th style={{ textAlign: 'right' }}>販売数</th>
                <th style={{ textAlign: 'right' }}>売上</th>
                <th style={{ textAlign: 'right' }}>ポイント</th>
                <th style={{ textAlign: 'right' }}>店舗クーポン</th>
                <th style={{ textAlign: 'right' }}>クーポン手数料</th>
                <th style={{ textAlign: 'right' }}>RPP</th>
                <th style={{ textAlign: 'right' }}>クーアド</th>
                <th style={{ textAlign: 'right' }}>アフィ</th>
                <th style={{ textAlign: 'right' }}>楽天手数料</th>
                <th style={{ textAlign: 'right' }}>送料</th>
                <th style={{ textAlign: 'right' }}>原価</th>
                <th style={{ textAlign: 'right' }}>利益</th>
                <th style={{ textAlign: 'right' }}>利益率</th>
                <th style={{ textAlign: 'right' }}>RPP比率</th>
              </tr>
            </thead>
            <tbody>
              {summaryQuery.isLoading && (
                <tr><td colSpan={level === 'sku' ? 17 : 16} style={{ textAlign: 'center', padding: 32, color: '#999' }}>読み込み中...</td></tr>
              )}
              {!summaryQuery.isLoading && filteredRows.length === 0 && (
                <tr><td colSpan={level === 'sku' ? 17 : 16} style={{ textAlign: 'center', padding: 32, color: '#999' }}>データがありません</td></tr>
              )}
              {filteredRows.map(r => (
                <tr key={`${r.product_key}-${r.sku_key || ''}`}>
                  <td style={{ fontFamily: 'monospace', whiteSpace: 'nowrap' }}>{r.product_key}</td>
                  {level === 'sku' && <td style={{ fontFamily: 'monospace', whiteSpace: 'nowrap' }}>{r.sku_key || '—'}</td>}
                  <td style={{ minWidth: 220 }}>{r.product_name || '—'}</td>
                  <td style={{ textAlign: 'right' }}>{fmtNum(r.units)}</td>
                  <td style={{ textAlign: 'right', fontWeight: 700 }}>{fmtYen(r.sales)}</td>
                  <td style={{ textAlign: 'right' }}>{fmtYen(r.point_cost)}</td>
                  <td style={{ textAlign: 'right' }}>{fmtYen(r.store_coupon)}</td>
                  <td style={{ textAlign: 'right' }}>{fmtYen(r.coupon_fee)}</td>
                  <td style={{ textAlign: 'right', color: Number(r.rpp_cost || 0) > 0 ? '#7c3aed' : '#94a3b8' }}>{fmtYen(r.rpp_cost)}</td>
                  <td style={{ textAlign: 'right', color: Number(r.coupon_ad_cost || 0) > 0 ? '#7c3aed' : '#94a3b8' }}>{fmtYen(r.coupon_ad_cost)}</td>
                  <td style={{ textAlign: 'right' }}>{fmtYen(Number(r.affiliate_cost || 0) + Number(r.affiliate_fee || 0))}</td>
                  <td style={{ textAlign: 'right' }}>{fmtYen(r.platform_fee)}</td>
                  <td style={{ textAlign: 'right' }}>{fmtYen(r.shipping_cost)}</td>
                  <td style={{ textAlign: 'right' }}>{fmtYen(r.product_cost)}</td>
                  <td style={{ textAlign: 'right', fontWeight: 700, color: Number(r.profit || 0) >= 0 ? '#16a34a' : '#dc2626' }}>{fmtYen(r.profit)}</td>
                  <td style={{ textAlign: 'right', fontWeight: 700, color: Number(r.profit_rate || 0) >= 20 ? '#16a34a' : '#d97706' }}>{fmtPct(r.profit_rate)}</td>
                  <td style={{ textAlign: 'right' }}>{fmtPct(r.rpp_rate)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

function FileInput({ label, required, multiple, onChange }) {
  return (
    <div className="form-group">
      <label>{label}{required ? ' *' : ''}</label>
      <input type="file" accept=".csv,.tsv,.txt,.xlsx,.xlsm" multiple={multiple} onChange={onChange} />
    </div>
  )
}

function ImportGuide() {
  const [open, setOpen] = useState(false)
  const guideStyle = { fontSize: 12, lineHeight: 1.7, color: '#475569' }
  const sectionStyle = { display: 'flex', gap: 8, alignItems: 'flex-start', padding: '6px 0' }
  const labelStyle = { fontWeight: 700, fontSize: 11, color: '#334155', minWidth: 56, flexShrink: 0 }
  const urlStyle = { color: '#2563eb', textDecoration: 'none', fontSize: 11, wordBreak: 'break-all' }
  const stepStyle = { display: 'inline-block', background: '#f1f5f9', borderRadius: 3, padding: '1px 6px', fontSize: 11, margin: '1px 2px' }
  const data = [
    { name: '受注データ', tab: null, url: 'https://csvdl-rp.rms.rakuten.co.jp/rms/mall/csvdl/CD02_01_001?dataType=opp_order#result', dlUrl: null,
      steps: '注文日時を対象月の初日〜末日 → 出力テンプレート: 全カラムダウンロード用 → DL（5000件超は分割して複数選択可）' },
    { name: 'RPP', tab: null, url: 'https://ad.rms.rakuten.co.jp/rpp/reports', dlUrl: 'https://ad.rms.rakuten.co.jp/rpp/download',
      steps: '商品別 → 月ごとに表示 → 全商品レポートDL → DL先でzip解凍 → zip・csv削除' },
    { name: 'クーアド', tab: null, url: 'https://ad.rms.rakuten.co.jp/cpnadv/performance_reports', dlUrl: 'https://ad.rms.rakuten.co.jp/cpnadv/download_history',
      steps: '商品別 → 月ごとに表示 → この条件でDL → DL先でzip解凍 → zip・csv削除' },
    { name: 'アフィ', tab: null, url: 'https://afl.rms.rakuten.co.jp/report/pending?date=2024-12', dlUrl: null,
      steps: '成果速報－注文一覧 → 対象月に設定 → 受注番号にチェック → ↓マークでDL' },
  ]
  return (
    <div style={{ marginTop: 10, borderTop: '1px solid #e2e8f0', paddingTop: 6 }}>
      <button
        onClick={() => setOpen(v => !v)}
        style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 12, color: '#64748b', padding: 0, fontWeight: 600 }}
      >
        {open ? '▾' : '▸'} データ取得手順
      </button>
      {open && (
        <div style={{ ...guideStyle, marginTop: 6 }}>
          {data.map(d => (
            <div key={d.name} style={sectionStyle}>
              <span style={labelStyle}>{d.name}</span>
              <div>
                <a href={d.url} target="_blank" rel="noreferrer" style={urlStyle}>{d.url.replace(/^https?:\/\//, '')}</a>
                {d.dlUrl && <><br /><span style={{ fontSize: 10, color: '#94a3b8' }}>DL先:</span> <a href={d.dlUrl} target="_blank" rel="noreferrer" style={urlStyle}>{d.dlUrl.replace(/^https?:\/\//, '')}</a></>}
                <br />
                {d.steps.split(' → ').map((s, i) => <span key={i} style={stepStyle}>{s}</span>)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function Metric({ label, value, tone }) {
  return (
    <div className="card" style={{ marginBottom: 0, padding: '14px 16px', borderTop: `3px solid ${tone}` }}>
      <div style={{ color: '#64748b', fontSize: 12, marginBottom: 6 }}>{label}</div>
      <div style={{ color: tone, fontSize: 18, fontWeight: 800 }}>{value}</div>
    </div>
  )
}
