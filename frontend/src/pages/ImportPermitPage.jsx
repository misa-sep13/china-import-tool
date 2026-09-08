// 輸入許可書の保管。
// 通関業者から届く許可書をメールから拾って残し、税理士へ渡すときに
// まとめて書き出せるようにする。原本のPDFをそのまま持っている。
import React, { useState, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'

const yen = (v) => (v ? `¥${Number(v).toLocaleString()}` : '—')
const kb = (v) => (v ? `${Math.round(Number(v) / 1024)}KB` : '—')

// 何年ぶんも遡ることは少ないので、よく使う範囲だけ出す
const SPANS = [
  { days: 60, label: '直近2か月' },
  { days: 180, label: '直近半年' },
  { days: 400, label: '直近1年' },
]

async function openBlob(url, params) {
  const res = await api.get(url, { params, responseType: 'blob' })
  const href = URL.createObjectURL(res.data)
  const cd = res.headers['content-disposition'] || ''
  const name = /filename="([^"]+)"/.exec(cd)?.[1]
  if (name) {
    // ZIPは開いても仕方ないので保存させる
    const a = document.createElement('a')
    a.href = href
    a.download = decodeURIComponent(name)
    a.click()
  } else {
    window.open(href, '_blank')
  }
  setTimeout(() => URL.revokeObjectURL(href), 60000)
}

export default function ImportPermitPage() {
  const qc = useQueryClient()
  const fileRef = useRef(null)
  const [year, setYear] = useState('')
  const [month, setMonth] = useState('')
  const [days, setDays] = useState(60)
  const [folder, setFolder] = useState(null)   // null=まだ既定を決めていない
  const [result, setResult] = useState(null)
  const [candidates, setCandidates] = useState(null)
  const [checking, setChecking] = useState(false)

  const params = {}
  if (year) params.year = Number(year)
  if (month) params.month = Number(month)

  // メールのフォルダ。振り分けていると受信トレイには残らないので選べるようにする
  const { data: folderData } = useQuery({
    queryKey: ['permit-folders'],
    queryFn: () => api.get('/import-permits/folders').then(r => r.data),
    retry: false,
  })
  const folders = (folderData?.items || []).filter(f => !f.skip)

  // 「輸入許可書」のようなフォルダがあれば最初から選んでおく。
  // 毎回選び直させると、選び忘れて0件になって迷う
  if (folder === null && folders.length > 0) {
    const hit = folders.find(f => /許可書|許可通知|permit/i.test(f.label))
    setFolder(hit ? hit.raw : '')
  }

  const { data, isLoading } = useQuery({
    queryKey: ['import-permits', year, month],
    queryFn: () => api.get('/import-permits/', { params }).then(r => r.data),
  })
  const items = data?.items || []

  const reload = () => qc.invalidateQueries({ queryKey: ['import-permits'] })

  const fetchMail = useMutation({
    mutationFn: () => api.post('/import-permits/fetch-mail', { days, folder: folder || '' }).then(r => r.data),
    onSuccess: (d) => { setResult(d); setCandidates(null); reload() },
    onError: (e) => alert('取り込めませんでした: ' + (e.response?.data?.detail || e.message)),
  })

  const uploadOne = useMutation({
    mutationFn: (file) => {
      const fd = new FormData()
      fd.append('file', file)
      return api.post('/import-permits/upload', fd).then(r => r.data)
    },
    onSuccess: (d) => {
      if (!d.looks_like_permit) {
        alert('許可書として読めませんでしたが、ファイルは保管しました。\n金額の欄は空になります。')
      }
      reload()
    },
    onError: (e) => alert('取り込めませんでした: ' + (e.response?.data?.detail || e.message)),
  })

  const toDrive = useMutation({
    mutationFn: (id) => api.post(`/import-permits/${id}/to-drive`).then(r => r.data),
    onSuccess: reload,
    onError: (e) => alert('ドライブへ置けませんでした: ' + (e.response?.data?.detail || e.message)),
  })

  const remove = useMutation({
    mutationFn: (id) => api.delete(`/import-permits/${id}`),
    onSuccess: reload,
  })

  async function showCandidates() {
    setChecking(true)
    try {
      const r = await api.get('/import-permits/scan-candidates', { params: { days, folder: folder || '' } })
      setCandidates(r.data.items || [])
    } catch (e) {
      alert('受信箱を見られませんでした: ' + (e.response?.data?.detail || e.message))
    } finally {
      setChecking(false)
    }
  }

  const years = [...new Set(items.map(x => (x.permit_date || x.mail_date || '').slice(0, 4)).filter(Boolean))]

  return (
    <div>
      <h2 style={{ marginBottom: 4 }}>輸入許可書</h2>
      <div style={{ fontSize: 13, color: '#64748b', marginBottom: 16 }}>
        卸発注で使っているメールから許可書のPDFを拾って保管します。
        税理士へ渡すときは、まとめてZIPで書き出してください。
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <select value={folder ?? ''} onChange={e => setFolder(e.target.value)}
            style={{ padding: '6px 10px', maxWidth: 220 }}>
            <option value="">受信トレイ</option>
            {folders.map(f => <option key={f.raw} value={f.raw}>{f.label}</option>)}
            <option value="*">すべてのフォルダ（時間がかかります）</option>
          </select>
          <select value={days} onChange={e => setDays(Number(e.target.value))}
            style={{ padding: '6px 10px' }}>
            {SPANS.map(s => <option key={s.days} value={s.days}>{s.label}</option>)}
          </select>
          <button className="btn btn-primary" onClick={() => fetchMail.mutate()}
            disabled={fetchMail.isPending}>
            {fetchMail.isPending ? 'メールを見ています…' : 'メールから取り込む'}
          </button>
          <span style={{ fontSize: 12, color: '#94a3b8' }}>
            同じ許可書は何度押しても増えません
          </span>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
            <button className="btn btn-secondary"
              onClick={() => fileRef.current?.click()} disabled={uploadOne.isPending}>
              PDFを直接入れる
            </button>
            <input ref={fileRef} type="file" accept=".pdf" style={{ display: 'none' }}
              onChange={e => {
                const f = e.target.files?.[0]
                e.target.value = ''
                if (f) uploadOne.mutate(f)
              }} />
          </div>
        </div>

        {result && (
          <div style={{ marginTop: 10, fontSize: 13, color: '#166534', fontWeight: 600 }}>
            {result.added}件を取り込みました
            {result.skipped > 0 && `（取り込み済み ${result.skipped}件はそのまま）`}
            {result.scanned === 0 && '。許可書らしいPDFが見つかりませんでした'}
            {/* 拾えたときも、取りこぼしが無いか確かめられるよう常に出す */}
            <button className="btn btn-sm btn-secondary" style={{ marginLeft: 10, fontSize: 12 }}
              onClick={showCandidates} disabled={checking}>
              {checking ? '確認中…' : 'このフォルダの添付を全部見る'}
            </button>
          </div>
        )}
        {(result?.drive_errors || []).length > 0 && (
          <div style={{ marginTop: 6, fontSize: 12, color: '#b91c1c' }}>
            {result.drive_errors.join(' / ')}
          </div>
        )}
      </div>

      {candidates && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', marginBottom: 8 }}>
            <b style={{ fontSize: 14 }}>受信箱にあるPDFの添付</b>
            <span style={{ fontSize: 12, color: '#64748b', marginLeft: 10 }}>
              許可書と判定できなかったものも含みます
            </span>
            <button className="btn btn-sm btn-secondary" style={{ marginLeft: 'auto', fontSize: 12 }}
              onClick={() => setCandidates(null)}>閉じる</button>
          </div>
          {candidates.length === 0
            ? <div style={{ fontSize: 13, color: '#94a3b8' }}>この期間にPDFの添付はありませんでした。</div>
            : (
              <table style={{ width: '100%', fontSize: 12 }}>
                <thead><tr>{['フォルダ', '日付', '差出人', '件名', '添付', '判定', '中身の先頭'].map(h =>
                  <th key={h} style={{ textAlign: 'left', padding: '4px 8px' }}>{h}</th>)}</tr></thead>
                <tbody>
                  {candidates.map((c, i) => (
                    <tr key={i} style={{ borderTop: '1px solid #f1f5f9' }}>
                      <td style={{ padding: '4px 8px', whiteSpace: 'nowrap' }}>{c.folder}</td>
                      <td style={{ padding: '4px 8px', whiteSpace: 'nowrap' }}>{c.date}</td>
                      <td style={{ padding: '4px 8px', maxWidth: 180, overflow: 'hidden' }}>{c.from}</td>
                      <td style={{ padding: '4px 8px', maxWidth: 220, overflow: 'hidden' }}>{c.subject}</td>
                      <td style={{ padding: '4px 8px' }}>{c.filename}</td>
                      <td style={{ padding: '4px 8px', color: c.is_permit ? '#15803d' : '#94a3b8' }}>
                        {c.is_permit ? '許可書' : '対象外'}
                      </td>
                      <td style={{ padding: '4px 8px', color: '#94a3b8', maxWidth: 260, overflow: 'hidden' }}>
                        {c.text_head || '（文字が入っていないPDF）'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
        </div>
      )}

      <div className="card">
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
          <select value={year} onChange={e => setYear(e.target.value)} style={{ padding: '6px 10px' }}>
            <option value="">すべての年</option>
            {years.map(y => <option key={y} value={y}>{y}年</option>)}
          </select>
          <select value={month} onChange={e => setMonth(e.target.value)} style={{ padding: '6px 10px' }}>
            <option value="">すべての月</option>
            {Array.from({ length: 12 }, (_, i) => i + 1).map(m =>
              <option key={m} value={m}>{m}月</option>)}
          </select>
          <span style={{ fontSize: 13, color: '#64748b' }}>
            {items.length}件 ／ 納税額合計 <b>{yen(data?.total_tax)}</b>
          </span>
          <button className="btn btn-primary" style={{ marginLeft: 'auto' }}
            disabled={items.length === 0}
            onClick={() => openBlob('/import-permits/zip', params)}>
            まとめてZIPで書き出す
          </button>
        </div>

        {isLoading ? <div style={{ color: '#94a3b8' }}>読み込み中…</div> : (
          <table style={{ width: '100%', fontSize: 13 }}>
            <thead><tr style={{ background: '#f8fafc' }}>
              {['許可年月日', '申告番号', '納税額', '関税', '消費税', '仕入書(元)', 'レート', 'メール', ''].map(h =>
                <th key={h} style={{ textAlign: 'left', padding: '6px 8px', whiteSpace: 'nowrap' }}>{h}</th>)}
            </tr></thead>
            <tbody>
              {items.map(p => (
                <tr key={p.id} style={{ borderTop: '1px solid #f1f5f9' }}>
                  <td style={{ padding: '6px 8px', whiteSpace: 'nowrap' }}>
                    {p.permit_date || <span style={{ color: '#b45309' }}>{p.mail_date || '—'}（推定）</span>}
                  </td>
                  <td style={{ padding: '6px 8px' }}>{p.permit_no || '—'}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right', fontWeight: 600 }}>{yen(p.total_tax)}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right' }}>{yen(p.customs_duty)}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right' }}>
                    {yen((p.consumption_tax || 0) + (p.local_consumption_tax || 0))}
                  </td>
                  <td style={{ padding: '6px 8px', textAlign: 'right' }}>{p.permit_cny || '—'}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right' }}>{p.exchange_rate || '—'}</td>
                  <td style={{ padding: '6px 8px', maxWidth: 260 }}>
                    <div style={{ fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {p.source === 'upload' ? '手で追加' : p.mail_subject || '—'}
                    </div>
                    <div style={{ fontSize: 11, color: '#94a3b8' }}>{p.filename}・{kb(p.size_bytes)}</div>
                  </td>
                  <td style={{ padding: '6px 8px', whiteSpace: 'nowrap' }}>
                    <button className="btn btn-sm btn-secondary" style={{ fontSize: 12 }}
                      onClick={() => openBlob(`/import-permits/${p.id}/pdf`)}>開く</button>
                    {data?.drive_ready && (
                      p.drive_url
                        ? <a href={p.drive_url} target="_blank" rel="noreferrer"
                            style={{ marginLeft: 6, fontSize: 12, color: '#15803d' }}>ドライブ</a>
                        : <button className="btn btn-sm btn-secondary" style={{ marginLeft: 6, fontSize: 12 }}
                            disabled={toDrive.isPending}
                            onClick={() => toDrive.mutate(p.id)}>ドライブへ</button>
                    )}
                    <button className="btn btn-sm btn-secondary" style={{ marginLeft: 6, fontSize: 12, color: '#b91c1c' }}
                      onClick={() => { if (confirm('この許可書を削除しますか？')) remove.mutate(p.id) }}>削除</button>
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr><td colSpan={9} style={{ padding: 16, color: '#94a3b8' }}>
                  まだ1件もありません。「メールから取り込む」を押してください。
                </td></tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
