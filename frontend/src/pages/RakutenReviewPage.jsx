import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'
import { normalizeSearch } from '../searchUtil'

const STATUS_LABELS = { pending: '未確認', confirmed: '確定', shipped: '発送済', skipped: 'スキップ' }
const STATUS_COLORS = { pending: '#d97706', confirmed: '#2563eb', shipped: '#16a34a', skipped: '#94a3b8' }

export default function RakutenReviewPage() {
  const qc = useQueryClient()
  const [tab, setTab] = useState('inquiries')
  const [days, setDays] = useState(7)
  const [reviewOnly, setReviewOnly] = useState(false)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [campaignFilter, setCampaignFilter] = useState('')
  const [selected, setSelected] = useState(new Set())

  // ── キャンペーンマスタ ──
  const campaignsQ = useQuery({
    queryKey: ['review-campaigns'],
    queryFn: () => api.get('/review/campaigns').then(r => r.data),
  })
  const campaigns = campaignsQ.data || []
  const campaignMap = useMemo(() => Object.fromEntries(campaigns.map(c => [c.code, c])), [campaigns])

  // ── 返信テンプレート ──
  const templatesQ = useQuery({
    queryKey: ['review-templates'],
    queryFn: () => api.get('/review/templates').then(r => r.data),
  })
  const templates = templatesQ.data || []

  // ── エントリー一覧 ──
  const entriesQ = useQuery({
    queryKey: ['review-entries', statusFilter, campaignFilter],
    queryFn: () => {
      const params = {}
      if (statusFilter) params.status = statusFilter
      if (campaignFilter) params.campaign_code = campaignFilter
      return api.get('/review/entries', { params }).then(r => r.data)
    },
  })
  const entries = entriesQ.data || []

  // ── 問い合わせ取得 ──
  const inquiriesMut = useMutation({
    mutationFn: () => {
      const now = new Date()
      const from = new Date(now - days * 86400000)
      const pad = n => String(n).padStart(2, '0')
      const fmtDate = d => `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`
      // to_dateは現在時刻まで（0:00にすると当日分が取得できない）
      return api.get('/review/inquiries', { params: {
        from_date: `${fmtDate(from)}T00:00:00`,
        to_date: `${fmtDate(now)}T${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`,
        review_only: reviewOnly,
      } }).then(r => r.data)
    },
  })

  // ── 問い合わせからエントリー登録 ──
  const registerMut = useMutation({
    mutationFn: async (inq) => {
      const addr = await api.get(`/review/order-address/${inq.order_number}`).then(r => r.data)
      const ship = addr.shipping || {}
      return api.post('/review/entries/import-single', {
        order_number: inq.order_number,
        zip1: ship.zip1,
        zip2: ship.zip2,
        prefecture: ship.prefecture,
        city: ship.city,
        address: ship.address,
        last_name: ship.last_name,
        first_name: ship.first_name,
        phone1: ship.phone1,
        phone2: ship.phone2,
        phone3: ship.phone3,
        campaign_code: inq.selected_campaign || inq.detected_campaign || '',
        campaign_name: '',
        quantity: 1,
        inquiry_message: inq.message,
        buyer_name: addr.buyer?.name || '',
        buyer_differs: addr.buyer_differs || false,
        item_name: inq.item_name,
      }).then(r => r.data)
    },
    onSuccess: () => {
      qc.invalidateQueries(['review-entries'])
      inquiriesMut.mutate()
    },
  })

  // ── R-Messe完了 ──
  const completeMut = useMutation({
    mutationFn: (inquiryNumbers) => api.post('/review/inquiries/complete', { inquiry_numbers: inquiryNumbers }).then(r => r.data),
    onSuccess: (data) => {
      if (data.errors?.length > 0) {
        alert('完了にできなかった問い合わせがあります:\n' + data.errors.map(e => `${e.inquiry_number}: ${e.message}`).join('\n'))
      }
      inquiriesMut.mutate()
    },
  })

  // ── ステータス更新 ──
  const statusMut = useMutation({
    mutationFn: ({ id, status }) => api.patch(`/review/entries/${id}/status`, { status }).then(r => r.data),
    onSuccess: () => qc.invalidateQueries(['review-entries']),
  })

  // ── 一括ステータス ──
  const bulkStatusMut = useMutation({
    mutationFn: ({ ids, status }) => api.post('/review/entries/bulk-status', null, { params: { ids: ids.join(','), status } }),
    onSuccess: () => { qc.invalidateQueries(['review-entries']); setSelected(new Set()) },
  })

  // ── 削除 ──
  const deleteMut = useMutation({
    mutationFn: (id) => api.delete(`/review/entries/${id}`),
    onSuccess: () => qc.invalidateQueries(['review-entries']),
  })

  // ── エクスポート ──
  const handleExport = () => {
    const params = new URLSearchParams({ status: 'confirmed' })
    const baseUrl = api.defaults.baseURL || ''
    window.open(`${baseUrl}/review/entries/export?${params}`, '_blank')
  }

  // ── フィルタ ──
  const filteredEntries = useMemo(() => {
    const q = normalizeSearch(search.trim())
    if (!q) return entries
    return entries.filter(e =>
      normalizeSearch(e.order_number || '').includes(q) ||
      normalizeSearch(e.last_name || '').includes(q) ||
      normalizeSearch(e.first_name || '').includes(q) ||
      normalizeSearch(e.campaign_code || '').includes(q) ||
      normalizeSearch(e.campaign_name || '').includes(q) ||
      normalizeSearch(e.product_name || '').includes(q) ||
      normalizeSearch(e.inquiry_message || '').includes(q)
    )
  }, [entries, search])

  return (
    <div>
      <h1 style={{ marginBottom: 16 }}>🎁 レビューキャンペーン</h1>

      <div style={{ display: 'flex', gap: 6, marginBottom: 16 }}>
        <button className={`btn ${tab === 'inquiries' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setTab('inquiries')}>問い合わせ取得</button>
        <button className={`btn ${tab === 'entries' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setTab('entries')}>エントリー一覧</button>
        <button className={`btn ${tab === 'campaigns' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setTab('campaigns')}>キャンペーンマスタ</button>
        <button className={`btn ${tab === 'templates' ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setTab('templates')}>返信テンプレート</button>
      </div>

      {tab === 'inquiries' && <InquiriesTab days={days} setDays={setDays} reviewOnly={reviewOnly} setReviewOnly={setReviewOnly} inquiriesMut={inquiriesMut} registerMut={registerMut} campaigns={campaigns} completeMut={completeMut} templates={templates} />}
      {tab === 'entries' && (
        <EntriesTab
          entries={filteredEntries}
          entriesQ={entriesQ}
          search={search}
          setSearch={setSearch}
          statusFilter={statusFilter}
          setStatusFilter={setStatusFilter}
          campaignFilter={campaignFilter}
          setCampaignFilter={setCampaignFilter}
          campaigns={campaigns}
          selected={selected}
          setSelected={setSelected}
          statusMut={statusMut}
          bulkStatusMut={bulkStatusMut}
          deleteMut={deleteMut}
          handleExport={handleExport}
        />
      )}
      {tab === 'campaigns' && <CampaignsTab campaigns={campaigns} qc={qc} />}
      {tab === 'templates' && <TemplatesTab templates={templates} qc={qc} />}
    </div>
  )
}


// ── 問い合わせ取得タブ ──
function InquiriesTab({ days, setDays, reviewOnly, setReviewOnly, inquiriesMut, registerMut, campaigns, completeMut, templates }) {
  const [localCampaigns, setLocalCampaigns] = useState({})
  const [expandedMsg, setExpandedMsg] = useState(null)
  const [detailInq, setDetailInq] = useState(null)

  const inquiries = inquiriesMut.data?.inquiries || []

  return (
    <div>
      <div className="card" style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <label style={{ fontSize: 13, fontWeight: 600 }}>取得期間</label>
        <select value={days} onChange={e => setDays(Number(e.target.value))} style={{ width: 120 }}>
          <option value={3}>3日間</option>
          <option value={7}>7日間</option>
          <option value={14}>14日間</option>
          <option value={30}>30日間</option>
          <option value={60}>60日間</option>
          <option value={90}>90日間</option>
        </select>
        <label style={{ fontSize: 13, display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
          <input type="checkbox" checked={reviewOnly} onChange={e => setReviewOnly(e.target.checked)} />
          レビュー関連のみ
        </label>
        <button
          className="btn btn-primary"
          onClick={() => inquiriesMut.mutate()}
          disabled={inquiriesMut.isPending}
        >
          {inquiriesMut.isPending ? '取得中...' : '📥 問い合わせ取得'}
        </button>
        {inquiriesMut.data && (
          <span style={{ fontSize: 13, color: '#16a34a', fontWeight: 600 }}>
            {inquiriesMut.data.total}件（完了は除く）
          </span>
        )}
        {inquiriesMut.error && (
          <span className="error-msg">{inquiriesMut.error.response?.data?.detail || inquiriesMut.error.message}</span>
        )}
      </div>

      {inquiries.length > 0 && (
        <div className="card" style={{ padding: 0 }}>
          <div className="sticky-table-wrap">
            <table className="sticky-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr>
                  <th style={{ width: 90 }}>日時</th>
                  <th style={{ width: 100 }}>お客様名</th>
                  <th style={{ minWidth: 250 }}>問い合わせ内容</th>
                  <th style={{ width: 120 }}>購入商品</th>
                  <th style={{ width: 160 }}>受注番号</th>
                  <th style={{ width: 160 }}>キャンペーン判定</th>
                  <th style={{ width: 80 }}>操作</th>
                </tr>
              </thead>
              <tbody>
                {inquiries.map(inq => {
                  const campaign = localCampaigns[inq.inquiry_number] || inq.detected_campaign || ''
                  return (
                    <tr key={inq.inquiry_number} style={{ background: inq.already_registered ? '#f0fdf4' : undefined }}>
                      <td style={{ fontSize: 11, whiteSpace: 'nowrap' }}>
                        {inq.reg_date ? new Date(inq.reg_date).toLocaleDateString('ja-JP', { month: 'numeric', day: 'numeric' }) : '—'}
                      </td>
                      <td>{inq.user_name || '—'}</td>
                      <td>
                        <div
                          style={{ cursor: 'pointer', maxHeight: expandedMsg === inq.inquiry_number ? 'none' : 48, overflow: 'hidden', lineHeight: 1.5 }}
                          onClick={() => setExpandedMsg(expandedMsg === inq.inquiry_number ? null : inq.inquiry_number)}
                          title="クリックで展開"
                        >
                          {inq.message || '—'}
                        </div>
                      </td>
                      <td style={{ fontSize: 11 }}>{inq.item_name || '—'}</td>
                      <td style={{ fontFamily: 'monospace', fontSize: 10 }}>{inq.order_number || '—'}</td>
                      <td>
                        {inq.already_registered ? (
                          <span style={{ color: '#16a34a', fontWeight: 600, fontSize: 11 }}>登録済み</span>
                        ) : (
                          <select
                            value={campaign}
                            onChange={e => setLocalCampaigns(prev => ({ ...prev, [inq.inquiry_number]: e.target.value }))}
                            style={{ width: '100%', fontSize: 11 }}
                          >
                            <option value="">-- 未選択 --</option>
                            {campaigns.map(c => (
                              <option key={c.code} value={c.code}>{c.code} ({c.name})</option>
                            ))}
                          </select>
                        )}
                      </td>
                      <td>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                          {!inq.already_registered && campaign && inq.order_number && (
                            <button
                              className="btn btn-primary"
                              style={{ fontSize: 11, padding: '2px 8px' }}
                              onClick={() => registerMut.mutate({ ...inq, selected_campaign: campaign })}
                              disabled={registerMut.isPending}
                            >
                              登録
                            </button>
                          )}
                          <button
                            className="btn btn-secondary"
                            style={{ fontSize: 11, padding: '2px 8px' }}
                            onClick={() => setDetailInq(inq)}
                          >
                            返信
                          </button>
                          <button
                            className="btn btn-secondary"
                            style={{ fontSize: 11, padding: '2px 8px', color: '#16a34a' }}
                            onClick={() => { if (confirm('R-Messeの問い合わせを完了にしますか？')) completeMut.mutate([inq.inquiry_number]) }}
                            disabled={completeMut.isPending}
                            title="R-Messe側も完了になります"
                          >
                            完了
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {detailInq && (
        <InquiryDetailModal
          inquiry={detailInq}
          templates={templates}
          completeMut={completeMut}
          onClose={() => setDetailInq(null)}
        />
      )}
    </div>
  )
}


// ── 問い合わせ詳細・返信モーダル ──
function InquiryDetailModal({ inquiry, templates, completeMut, onClose }) {
  const qc = useQueryClient()
  const [msg, setMsg] = useState('')

  const detailQ = useQuery({
    queryKey: ['review-inquiry', inquiry.inquiry_number],
    queryFn: () => api.get(`/review/inquiry/${inquiry.inquiry_number}`).then(r => r.data),
  })
  const detail = detailQ.data

  const replyMut = useMutation({
    mutationFn: () => api.post('/review/inquiry/reply', { inquiry_number: inquiry.inquiry_number, message: msg }).then(r => r.data),
    onSuccess: () => {
      setMsg('')
      qc.invalidateQueries(['review-inquiry', inquiry.inquiry_number])
    },
  })

  const fmtDate = (d) => d ? new Date(d).toLocaleString('ja-JP', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : ''

  return (
    <div
      style={{ position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.5)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      onClick={onClose}
    >
      <div
        className="card"
        style={{ width: 'min(760px, 94vw)', maxHeight: '88vh', display: 'flex', flexDirection: 'column', padding: 16 }}
        onClick={e => e.stopPropagation()}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
          <strong style={{ fontSize: 15 }}>{inquiry.user_name || '—'} 様</strong>
          <span style={{ fontSize: 11, color: '#64748b', fontFamily: 'monospace' }}>{inquiry.inquiry_number}</span>
          <button className="btn btn-secondary" style={{ marginLeft: 'auto', fontSize: 12 }} onClick={onClose}>✕ 閉じる</button>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', background: '#f8fafc', borderRadius: 8, padding: 12, minHeight: 200 }}>
          {detailQ.isLoading && <div style={{ color: '#999', textAlign: 'center', padding: 24 }}>読み込み中...</div>}
          {detailQ.error && <div className="error-msg">{detailQ.error.response?.data?.detail || detailQ.error.message}</div>}
          {(detail?.thread || []).map((m, i) => (
            <div key={i} style={{ display: 'flex', justifyContent: m.from === 'merchant' ? 'flex-end' : 'flex-start', marginBottom: 10 }}>
              <div style={{
                maxWidth: '78%',
                background: m.from === 'merchant' ? '#dbeafe' : '#fff',
                border: '1px solid ' + (m.from === 'merchant' ? '#bfdbfe' : '#e2e8f0'),
                borderRadius: 10,
                padding: '8px 12px',
                fontSize: 13,
                whiteSpace: 'pre-wrap',
                lineHeight: 1.6,
              }}>
                <div style={{ fontSize: 10, color: '#64748b', marginBottom: 4 }}>
                  {m.from === 'merchant' ? '自分（店舗）' : (inquiry.user_name || 'お客様')} ・ {fmtDate(m.date)}
                </div>
                {m.deleted ? <span style={{ color: '#94a3b8' }}>（削除されたメッセージ）</span> : m.message}
              </div>
            </div>
          ))}
        </div>

        <div style={{ marginTop: 12 }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6 }}>
            <label style={{ fontSize: 12, fontWeight: 600 }}>テンプレート</label>
            <select
              defaultValue=""
              onChange={e => {
                const t = templates.find(x => String(x.id) === e.target.value)
                if (t) setMsg(t.body)
              }}
              style={{ width: 240 }}
            >
              <option value="">-- 選択して挿入 --</option>
              {templates.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
            <span style={{ fontSize: 11, color: '#94a3b8', marginLeft: 'auto' }}>{msg.length}/2000文字</span>
          </div>
          <textarea
            value={msg}
            onChange={e => setMsg(e.target.value)}
            placeholder="ここに返信を記入してください"
            rows={6}
            style={{ width: '100%', fontSize: 13, lineHeight: 1.6, padding: 8, boxSizing: 'border-box' }}
          />
          {replyMut.error && <div className="error-msg" style={{ marginTop: 4 }}>{replyMut.error.response?.data?.detail || replyMut.error.message}</div>}
          {replyMut.isSuccess && <div style={{ color: '#16a34a', fontSize: 12, marginTop: 4 }}>返信を送信しました</div>}
          <div style={{ display: 'flex', gap: 8, marginTop: 8, justifyContent: 'flex-end' }}>
            <button
              className="btn btn-secondary"
              style={{ color: '#16a34a' }}
              onClick={() => { if (confirm('R-Messeの問い合わせを完了にしますか？')) { completeMut.mutate([inquiry.inquiry_number]); onClose() } }}
            >
              完了にする
            </button>
            <button
              className="btn btn-primary"
              disabled={!msg.trim() || replyMut.isPending}
              onClick={() => { if (confirm('この内容でお客様に返信を送信しますか？')) replyMut.mutate() }}
            >
              {replyMut.isPending ? '送信中...' : '📨 送信'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}


// ── エントリー一覧タブ ──
function EntriesTab({ entries, entriesQ, search, setSearch, statusFilter, setStatusFilter, campaignFilter, setCampaignFilter, campaigns, selected, setSelected, statusMut, bulkStatusMut, deleteMut, handleExport }) {
  const [expandedMsg, setExpandedMsg] = useState(null)
  const toggleSelect = (id) => setSelected(prev => {
    const next = new Set(prev)
    next.has(id) ? next.delete(id) : next.add(id)
    return next
  })
  const toggleAll = () => {
    if (selected.size === entries.length) setSelected(new Set())
    else setSelected(new Set(entries.map(e => e.id)))
  }

  const confirmedCount = entries.filter(e => e.status === 'confirmed').length

  return (
    <div>
      <div className="card" style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)} style={{ width: 130 }}>
          <option value="">全ステータス</option>
          {Object.entries(STATUS_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select value={campaignFilter} onChange={e => setCampaignFilter(e.target.value)} style={{ width: 180 }}>
          <option value="">全キャンペーン</option>
          {campaigns.map(c => <option key={c.code} value={c.code}>{c.code} ({c.name})</option>)}
        </select>
        <input value={search} onChange={e => setSearch(e.target.value)} placeholder="検索..." style={{ width: 200, marginLeft: 'auto' }} />
        {selected.size > 0 && (
          <>
            <button className="btn btn-primary" style={{ fontSize: 12 }} onClick={() => bulkStatusMut.mutate({ ids: [...selected], status: 'confirmed' })}>
              選択を確定 ({selected.size})
            </button>
            <button className="btn btn-secondary" style={{ fontSize: 12 }} onClick={() => bulkStatusMut.mutate({ ids: [...selected], status: 'skipped' })}>
              スキップ
            </button>
          </>
        )}
        <button className="btn btn-secondary" onClick={handleExport} style={{ fontSize: 12 }} disabled={confirmedCount === 0}>
          📤 CSV出力 ({confirmedCount}件)
        </button>
      </div>

      <div className="card" style={{ padding: 0 }}>
        <div className="sticky-table-wrap">
          <table className="sticky-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr>
                <th style={{ width: 32 }}>
                  <input type="checkbox" checked={selected.size === entries.length && entries.length > 0} onChange={toggleAll} />
                </th>
                <th style={{ width: 70 }}>ステータス</th>
                <th style={{ width: 110 }}>キャンペーン</th>
                <th style={{ width: 160 }}>受注番号</th>
                <th>送付先</th>
                <th style={{ width: 100 }}>送付先氏名</th>
                <th style={{ width: 90 }}>注文者</th>
                <th style={{ minWidth: 200 }}>問い合わせ内容</th>
                <th style={{ width: 100 }}>購入商品</th>
                <th style={{ width: 80 }}>操作</th>
              </tr>
            </thead>
            <tbody>
              {entriesQ.isLoading && (
                <tr><td colSpan={10} style={{ textAlign: 'center', padding: 32, color: '#999' }}>読み込み中...</td></tr>
              )}
              {!entriesQ.isLoading && entries.length === 0 && (
                <tr><td colSpan={10} style={{ textAlign: 'center', padding: 32, color: '#999' }}>データがありません</td></tr>
              )}
              {entries.map(e => {
                const buyerDiffStyle = e.buyer_differs ? { color: '#dc2626', fontWeight: 700 } : {}
                return (
                  <tr key={e.id} style={{ background: e.status === 'confirmed' ? '#eff6ff' : e.status === 'shipped' ? '#f0fdf4' : e.status === 'skipped' ? '#f8fafc' : undefined }}>
                    <td><input type="checkbox" checked={selected.has(e.id)} onChange={() => toggleSelect(e.id)} /></td>
                    <td>
                      <select
                        value={e.status}
                        onChange={ev => statusMut.mutate({ id: e.id, status: ev.target.value })}
                        style={{ fontSize: 11, color: STATUS_COLORS[e.status] || '#334155', fontWeight: 600, width: '100%' }}
                      >
                        {Object.entries(STATUS_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                      </select>
                    </td>
                    <td style={{ fontSize: 11, fontWeight: 600 }}>
                      {e.campaign_code || '—'}
                      <div style={{ fontWeight: 400, color: '#64748b' }}>{e.product_name || ''}</div>
                    </td>
                    <td style={{ fontFamily: 'monospace', fontSize: 10 }}>{e.order_number}</td>
                    <td style={{ fontSize: 11 }}>
                      〒{e.zip1}-{e.zip2} {e.prefecture}{e.city}{e.address}
                    </td>
                    <td style={buyerDiffStyle}>
                      {e.last_name} {e.first_name}
                      {e.buyer_differs && <span title="注文者と送付先が異なります" style={{ fontSize: 10 }}> ⚠️</span>}
                    </td>
                    <td style={{ fontSize: 11 }}>{e.buyer_name || '—'}</td>
                    <td>
                      <div
                        style={{ cursor: 'pointer', maxHeight: expandedMsg === e.id ? 'none' : 40, overflow: 'hidden', lineHeight: 1.4, fontSize: 11, color: '#475569' }}
                        onClick={() => setExpandedMsg(expandedMsg === e.id ? null : e.id)}
                        title="クリックで展開"
                      >
                        {e.inquiry_message || '—'}
                      </div>
                    </td>
                    <td style={{ fontSize: 11 }}>{e.item_name || '—'}</td>
                    <td>
                      <button
                        className="btn btn-secondary"
                        style={{ fontSize: 10, padding: '1px 6px', color: '#dc2626' }}
                        onClick={() => { if (confirm('削除しますか？')) deleteMut.mutate(e.id) }}
                      >
                        削除
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}


// ── キャンペーンマスタタブ ──
function CampaignsTab({ campaigns, qc }) {
  const [form, setForm] = useState({ code: '', name: '', product_sku: '', keywords: '' })
  const [editing, setEditing] = useState(null)

  const createMut = useMutation({
    mutationFn: (data) => api.post('/review/campaigns', data).then(r => r.data),
    onSuccess: () => { qc.invalidateQueries(['review-campaigns']); setForm({ code: '', name: '', product_sku: '', keywords: '' }) },
  })
  const updateMut = useMutation({
    mutationFn: ({ id, ...data }) => api.put(`/review/campaigns/${id}`, data).then(r => r.data),
    onSuccess: () => { qc.invalidateQueries(['review-campaigns']); setEditing(null) },
  })
  const deleteMut = useMutation({
    mutationFn: (id) => api.delete(`/review/campaigns/${id}`),
    onSuccess: () => qc.invalidateQueries(['review-campaigns']),
  })

  return (
    <div>
      <div className="card" style={{ marginBottom: 16 }}>
        <h3 style={{ margin: '0 0 12px', fontSize: 14 }}>キャンペーン追加</h3>
        <div style={{ display: 'flex', gap: 8, alignItems: 'end', flexWrap: 'wrap' }}>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>コード</label>
            <input value={form.code} onChange={e => setForm(f => ({ ...f, code: e.target.value }))} placeholder="review-A" style={{ width: 140 }} />
          </div>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>商品名</label>
            <input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder="魔法のクロス" style={{ width: 180 }} />
          </div>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>SKU（任意）</label>
            <input value={form.product_sku} onChange={e => setForm(f => ({ ...f, product_sku: e.target.value }))} placeholder="" style={{ width: 120 }} />
          </div>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>判定キーワード（カンマ区切り）</label>
            <input value={form.keywords} onChange={e => setForm(f => ({ ...f, keywords: e.target.value }))} placeholder="魔法のクロス, クロス, A" style={{ width: 260 }} />
          </div>
          <button className="btn btn-primary" onClick={() => createMut.mutate(form)} disabled={!form.code || !form.name || createMut.isPending}>
            追加
          </button>
        </div>
        {createMut.error && <div className="error-msg" style={{ marginTop: 8 }}>{createMut.error.response?.data?.detail || createMut.error.message}</div>}
      </div>

      <div className="card" style={{ padding: 0 }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr style={{ background: '#f8fafc' }}>
              <th style={{ padding: '8px 12px', textAlign: 'left' }}>コード</th>
              <th style={{ padding: '8px 12px', textAlign: 'left' }}>商品名</th>
              <th style={{ padding: '8px 12px', textAlign: 'left' }}>SKU</th>
              <th style={{ padding: '8px 12px', textAlign: 'left', minWidth: 200 }}>判定キーワード</th>
              <th style={{ padding: '8px 12px', width: 100 }}>操作</th>
            </tr>
          </thead>
          <tbody>
            {campaigns.map(c => (
              <tr key={c.id} style={{ borderTop: '1px solid #e2e8f0' }}>
                {editing === c.id ? (
                  <EditCampaignRow campaign={c} onSave={(data) => updateMut.mutate({ id: c.id, ...data })} onCancel={() => setEditing(null)} />
                ) : (
                  <>
                    <td style={{ padding: '8px 12px', fontFamily: 'monospace' }}>{c.code}</td>
                    <td style={{ padding: '8px 12px' }}>{c.name}</td>
                    <td style={{ padding: '8px 12px', fontFamily: 'monospace', color: '#64748b' }}>{c.product_sku || '—'}</td>
                    <td style={{ padding: '8px 12px', fontSize: 12, color: '#475569' }}>{c.keywords || '—'}</td>
                    <td style={{ padding: '8px 12px', display: 'flex', gap: 4 }}>
                      <button className="btn btn-secondary" style={{ fontSize: 11, padding: '2px 8px' }} onClick={() => setEditing(c.id)}>編集</button>
                      <button className="btn btn-secondary" style={{ fontSize: 11, padding: '2px 8px', color: '#dc2626' }} onClick={() => { if (confirm('削除？')) deleteMut.mutate(c.id) }}>削除</button>
                    </td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── 返信テンプレートタブ ──
function TemplatesTab({ templates, qc }) {
  const [form, setForm] = useState({ name: '', body: '' })
  const [editing, setEditing] = useState(null)
  const [editForm, setEditForm] = useState({ name: '', body: '' })

  const createMut = useMutation({
    mutationFn: (data) => api.post('/review/templates', data).then(r => r.data),
    onSuccess: () => { qc.invalidateQueries(['review-templates']); setForm({ name: '', body: '' }) },
  })
  const updateMut = useMutation({
    mutationFn: ({ id, ...data }) => api.put(`/review/templates/${id}`, data).then(r => r.data),
    onSuccess: () => { qc.invalidateQueries(['review-templates']); setEditing(null) },
  })
  const deleteMut = useMutation({
    mutationFn: (id) => api.delete(`/review/templates/${id}`),
    onSuccess: () => qc.invalidateQueries(['review-templates']),
  })

  return (
    <div>
      <div className="card" style={{ marginBottom: 16 }}>
        <h3 style={{ margin: '0 0 12px', fontSize: 14 }}>テンプレート追加</h3>
        <div className="form-group" style={{ marginBottom: 8 }}>
          <label>テンプレート名</label>
          <input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder="Aクロス" style={{ width: 240 }} />
        </div>
        <div className="form-group" style={{ marginBottom: 8 }}>
          <label>本文</label>
          <textarea
            value={form.body}
            onChange={e => setForm(f => ({ ...f, body: e.target.value }))}
            placeholder={'この度はみそらマートをご利用くださり誠にありがとうございます。\n\nレビューのご記入ありがとうございます！...'}
            rows={8}
            style={{ width: '100%', fontSize: 13, lineHeight: 1.6, padding: 8, boxSizing: 'border-box' }}
          />
        </div>
        <button className="btn btn-primary" onClick={() => createMut.mutate(form)} disabled={!form.name || !form.body || createMut.isPending}>
          追加
        </button>
        {createMut.error && <div className="error-msg" style={{ marginTop: 8 }}>{createMut.error.response?.data?.detail || createMut.error.message}</div>}
      </div>

      {templates.map(t => (
        <div key={t.id} className="card" style={{ marginBottom: 8, padding: 12 }}>
          {editing === t.id ? (
            <>
              <input value={editForm.name} onChange={e => setEditForm(f => ({ ...f, name: e.target.value }))} style={{ width: 240, marginBottom: 6 }} />
              <textarea
                value={editForm.body}
                onChange={e => setEditForm(f => ({ ...f, body: e.target.value }))}
                rows={8}
                style={{ width: '100%', fontSize: 13, lineHeight: 1.6, padding: 8, boxSizing: 'border-box', marginBottom: 6 }}
              />
              <div style={{ display: 'flex', gap: 6 }}>
                <button className="btn btn-primary" style={{ fontSize: 12 }} onClick={() => updateMut.mutate({ id: t.id, ...editForm })}>保存</button>
                <button className="btn btn-secondary" style={{ fontSize: 12 }} onClick={() => setEditing(null)}>取消</button>
              </div>
            </>
          ) : (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <strong style={{ fontSize: 14 }}>{t.name}</strong>
                <button className="btn btn-secondary" style={{ fontSize: 11, padding: '2px 8px', marginLeft: 'auto' }} onClick={() => { setEditing(t.id); setEditForm({ name: t.name, body: t.body }) }}>編集</button>
                <button className="btn btn-secondary" style={{ fontSize: 11, padding: '2px 8px', color: '#dc2626' }} onClick={() => { if (confirm('削除しますか？')) deleteMut.mutate(t.id) }}>削除</button>
              </div>
              <div style={{ fontSize: 12, color: '#475569', whiteSpace: 'pre-wrap', marginTop: 6, lineHeight: 1.6, maxHeight: 120, overflow: 'hidden' }}>
                {t.body}
              </div>
            </>
          )}
        </div>
      ))}
      {templates.length === 0 && <div style={{ color: '#999', fontSize: 13 }}>テンプレートがありません。上のフォームから追加してください。</div>}
    </div>
  )
}


function EditCampaignRow({ campaign, onSave, onCancel }) {
  const [f, setF] = useState({ code: campaign.code, name: campaign.name, product_sku: campaign.product_sku || '', keywords: campaign.keywords || '' })
  return (
    <>
      <td style={{ padding: '4px 8px' }}><input value={f.code} onChange={e => setF(p => ({ ...p, code: e.target.value }))} style={{ width: '100%' }} /></td>
      <td style={{ padding: '4px 8px' }}><input value={f.name} onChange={e => setF(p => ({ ...p, name: e.target.value }))} style={{ width: '100%' }} /></td>
      <td style={{ padding: '4px 8px' }}><input value={f.product_sku} onChange={e => setF(p => ({ ...p, product_sku: e.target.value }))} style={{ width: '100%' }} /></td>
      <td style={{ padding: '4px 8px' }}><input value={f.keywords} onChange={e => setF(p => ({ ...p, keywords: e.target.value }))} placeholder="魔法のクロス, クロス, A" style={{ width: '100%' }} /></td>
      <td style={{ padding: '4px 8px', display: 'flex', gap: 4 }}>
        <button className="btn btn-primary" style={{ fontSize: 11, padding: '2px 8px' }} onClick={() => onSave(f)}>保存</button>
        <button className="btn btn-secondary" style={{ fontSize: 11, padding: '2px 8px' }} onClick={onCancel}>取消</button>
      </td>
    </>
  )
}
