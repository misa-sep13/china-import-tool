import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'

const STATUS_LABELS = { pending: '未確認', approved: '承認', pushed: '反映済', skipped: 'スキップ' }
const STATUS_COLORS = { pending: '#d97706', approved: '#2563eb', pushed: '#16a34a', skipped: '#94a3b8' }

export default function KeywordAnalysisPage() {
  const qc = useQueryClient()
  const [selectedUpload, setSelectedUpload] = useState(null)
  const [editingId, setEditingId] = useState(null)
  const [editText, setEditText] = useState('')
  const [manageNumbers, setManageNumbers] = useState({})

  const uploadsQ = useQuery({
    queryKey: ['kw-uploads'],
    queryFn: () => api.get('/keyword-analysis/uploads').then(r => r.data),
  })
  const uploads = uploadsQ.data || []

  const dataQ = useQuery({
    queryKey: ['kw-data', selectedUpload],
    queryFn: () => api.get(`/keyword-analysis/data/${selectedUpload}`).then(r => r.data),
    enabled: !!selectedUpload,
  })
  const products = dataQ.data || []

  const uploadMut = useMutation({
    mutationFn: (file) => {
      const fd = new FormData()
      fd.append('file', file)
      return api.post('/keyword-analysis/upload', fd).then(r => r.data)
    },
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['kw-uploads'] })
      setSelectedUpload(data.upload_id)
    },
  })

  const suggestMut = useMutation({
    mutationFn: (uploadId) => api.post(`/keyword-analysis/suggest/${uploadId}`).then(r => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['kw-data', selectedUpload] }),
  })

  const updateTitleMut = useMutation({
    mutationFn: ({ optId, title }) => api.put(`/keyword-analysis/optimization/${optId}`, { suggested_title: title }).then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['kw-data', selectedUpload] })
      setEditingId(null)
    },
  })

  const statusMut = useMutation({
    mutationFn: ({ optId, status }) => api.patch(`/keyword-analysis/optimization/${optId}/status`, { status }).then(r => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['kw-data', selectedUpload] }),
  })

  const pushMut = useMutation({
    mutationFn: ({ optId, manageNumber }) => api.post(`/keyword-analysis/push/${optId}`, { manage_number: manageNumber }).then(r => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['kw-data', selectedUpload] }),
  })

  const handleFile = (e) => {
    const file = e.target.files?.[0]
    if (file) uploadMut.mutate(file)
    e.target.value = ''
  }

  const charCount = (s) => {
    if (!s) return 0
    let count = 0
    for (const ch of s) {
      count += /[\x00-\x7F]/.test(ch) ? 0.5 : 1
    }
    return Math.ceil(count)
  }

  return (
    <div>
      <h1>🔍 キーワード分析・タイトル最適化</h1>

      {/* CSV Upload */}
      <div className="card">
        <h2>CSVアップロード</h2>
        <p style={{ fontSize: 12, color: '#666', marginBottom: 12 }}>
          RMS「商品別検索キーワード」ページからダウンロードしたCSVをアップロードしてください
        </p>
        <label className="btn btn-primary" style={{ cursor: 'pointer' }}>
          📂 CSVを選択
          <input type="file" accept=".csv" onChange={handleFile} style={{ display: 'none' }} />
        </label>
        {uploadMut.isPending && <span style={{ marginLeft: 12, color: '#666' }}>アップロード中...</span>}
        {uploadMut.isError && <span style={{ marginLeft: 12, color: '#e94560' }}>エラー: {uploadMut.error?.response?.data?.detail || uploadMut.error?.message}</span>}
        {uploadMut.isSuccess && (
          <span style={{ marginLeft: 12, color: '#16a34a' }}>
            ✓ {uploadMut.data.products}商品 / {uploadMut.data.keywords}キーワード ({uploadMut.data.period})
          </span>
        )}
      </div>

      {/* Upload History */}
      {uploads.length > 0 && (
        <div className="card">
          <h2>アップロード履歴</h2>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: '2px solid #e5e7eb', textAlign: 'left' }}>
                <th style={{ padding: '8px 12px' }}>日時</th>
                <th style={{ padding: '8px 12px' }}>対象期間</th>
                <th style={{ padding: '8px 12px' }}>商品数</th>
                <th style={{ padding: '8px 12px' }}>キーワード数</th>
                <th style={{ padding: '8px 12px' }}></th>
              </tr>
            </thead>
            <tbody>
              {uploads.map(u => (
                <tr key={u.id} style={{ borderBottom: '1px solid #f1f3f5', background: selectedUpload === u.id ? '#eff6ff' : undefined }}>
                  <td style={{ padding: '8px 12px' }}>{u.uploaded_at ? new Date(u.uploaded_at).toLocaleString('ja-JP') : '-'}</td>
                  <td style={{ padding: '8px 12px' }}>{u.period_from} 〜 {u.period_to}</td>
                  <td style={{ padding: '8px 12px' }}>{u.product_count}</td>
                  <td style={{ padding: '8px 12px' }}>{u.keyword_count}</td>
                  <td style={{ padding: '8px 12px' }}>
                    <button className="btn btn-secondary btn-sm" onClick={() => setSelectedUpload(u.id)}>
                      表示
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Product Detail */}
      {selectedUpload && (
        <div className="card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <h2 style={{ margin: 0 }}>商品別キーワード・タイトル最適化</h2>
            <button
              className="btn btn-primary"
              onClick={() => suggestMut.mutate(selectedUpload)}
              disabled={suggestMut.isPending}
            >
              {suggestMut.isPending ? '⏳ 生成中...' : '🤖 AI提案生成'}
            </button>
          </div>

          {dataQ.isLoading && <p style={{ color: '#666' }}>読み込み中...</p>}

          {products.map(p => (
            <div key={p.no} style={{ border: '1px solid #e5e7eb', borderRadius: 8, padding: 16, marginBottom: 16 }}>
              {/* Product header */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                <div>
                  <span style={{ fontWeight: 700, fontSize: 14 }}>No.{p.no}</span>
                  <span style={{ marginLeft: 8, fontSize: 13, color: '#333' }}>{p.name}</span>
                </div>
                <div style={{ textAlign: 'right' }}>
                  {p.optimization?.manage_number && (
                    <span style={{ fontSize: 11, color: '#2563eb', marginRight: 12 }}>管理番号: {p.optimization.manage_number}</span>
                  )}
                  <span style={{ fontSize: 12, color: '#666' }}>合計アクセス: {p.total_access}</span>
                </div>
              </div>

              {/* Keywords table */}
              <div style={{ overflowX: 'auto', marginBottom: 12 }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid #e5e7eb', color: '#666' }}>
                      <th style={{ padding: '6px 8px', textAlign: 'left' }}>キーワード</th>
                      <th style={{ padding: '6px 8px', textAlign: 'right' }}>アクセス</th>
                      <th style={{ padding: '6px 8px', textAlign: 'right' }}>CVR(%)</th>
                      <th style={{ padding: '6px 8px', textAlign: 'center' }}>ランク</th>
                      <th style={{ padding: '6px 8px', textAlign: 'center' }}>アクション</th>
                    </tr>
                  </thead>
                  <tbody>
                    {p.keywords.map((kw, i) => (
                      <tr key={i} style={{ borderBottom: '1px solid #f5f5f5' }}>
                        <td style={{ padding: '6px 8px' }}>{kw.keyword}</td>
                        <td style={{ padding: '6px 8px', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{kw.access}</td>
                        <td style={{ padding: '6px 8px', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{kw.cvr.toFixed(2)}</td>
                        <td style={{ padding: '6px 8px', textAlign: 'center' }}>{kw.rank}</td>
                        <td style={{ padding: '6px 8px', textAlign: 'center' }}>
                          {kw.action_access && <span style={{ background: '#dbeafe', color: '#2563eb', borderRadius: 4, padding: '2px 6px', marginRight: 4, fontSize: 11 }}>アクセス</span>}
                          {kw.action_cvr && <span style={{ background: '#fef3c7', color: '#d97706', borderRadius: 4, padding: '2px 6px', marginRight: 4, fontSize: 11 }}>転換率</span>}
                          {kw.action_good && <span style={{ background: '#dcfce7', color: '#16a34a', borderRadius: 4, padding: '2px 6px', fontSize: 11 }}>Good</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Optimization suggestion */}
              {p.optimization && (
                <div style={{ background: '#f8fafc', borderRadius: 8, padding: 14, border: '1px solid #e2e8f0' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                    <span style={{ fontWeight: 700, fontSize: 13 }}>タイトル改善提案</span>
                    <span style={{
                      fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 4,
                      background: STATUS_COLORS[p.optimization.status] + '18',
                      color: STATUS_COLORS[p.optimization.status],
                    }}>
                      {STATUS_LABELS[p.optimization.status]}
                    </span>
                  </div>

                  {/* Current title */}
                  <div style={{ marginBottom: 8 }}>
                    <div style={{ fontSize: 11, color: '#666', marginBottom: 2 }}>修正前（{charCount(p.optimization.current_title)}文字）</div>
                    <div style={{ fontSize: 13, padding: 8, background: '#fff', borderRadius: 4, border: '1px solid #e5e7eb', wordBreak: 'break-all' }}>
                      {p.optimization.current_title}
                    </div>
                  </div>

                  {/* Suggested title */}
                  <div style={{ marginBottom: 8 }}>
                    <div style={{ fontSize: 11, color: '#666', marginBottom: 2 }}>
                      修正案（{charCount(p.optimization.suggested_title)}文字）
                      {charCount(p.optimization.suggested_title) > 127 && <span style={{ color: '#e94560', marginLeft: 4 }}>⚠ 127文字超過</span>}
                    </div>
                    {editingId === p.optimization.id ? (
                      <div>
                        <textarea
                          value={editText}
                          onChange={e => setEditText(e.target.value)}
                          style={{ width: '100%', minHeight: 60, fontSize: 13, padding: 8, borderRadius: 4, border: '1px solid #d1d5db', resize: 'vertical' }}
                        />
                        <div style={{ fontSize: 11, color: charCount(editText) > 127 ? '#e94560' : '#666', marginBottom: 6 }}>
                          {charCount(editText)}文字 / 127文字
                        </div>
                        <div style={{ display: 'flex', gap: 6 }}>
                          <button className="btn btn-primary btn-sm" onClick={() => updateTitleMut.mutate({ optId: p.optimization.id, title: editText })} disabled={updateTitleMut.isPending}>
                            保存
                          </button>
                          <button className="btn btn-secondary btn-sm" onClick={() => setEditingId(null)}>
                            キャンセル
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div
                        onClick={() => { setEditingId(p.optimization.id); setEditText(p.optimization.suggested_title) }}
                        style={{ fontSize: 13, padding: 8, background: '#fff', borderRadius: 4, border: '1px dashed #93c5fd', cursor: 'pointer', wordBreak: 'break-all' }}
                        title="クリックして編集"
                      >
                        {p.optimization.suggested_title}
                      </div>
                    )}
                  </div>

                  {/* Reasoning */}
                  <div style={{ fontSize: 12, color: '#555', marginBottom: 10 }}>
                    💡 {p.optimization.reasoning}
                  </div>

                  {/* Pushed date */}
                  {p.optimization.pushed_at && (
                    <div style={{ fontSize: 12, color: '#16a34a', marginBottom: 10 }}>
                      ✅ 実施日: {new Date(p.optimization.pushed_at).toLocaleString('ja-JP')}
                    </div>
                  )}

                  {/* Actions */}
                  {p.optimization.status !== 'pushed' && (
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                      {p.optimization.status !== 'approved' && (
                        <button className="btn btn-success btn-sm" onClick={() => statusMut.mutate({ optId: p.optimization.id, status: 'approved' })}>
                          ✓ 承認
                        </button>
                      )}
                      {p.optimization.status !== 'skipped' && (
                        <button className="btn btn-secondary btn-sm" onClick={() => statusMut.mutate({ optId: p.optimization.id, status: 'skipped' })}>
                          スキップ
                        </button>
                      )}
                      {p.optimization.status === 'approved' && (
                        <>
                          <input
                            type="text"
                            placeholder="商品管理番号"
                            value={manageNumbers[p.optimization.id] ?? p.optimization.manage_number ?? ''}
                            onChange={e => setManageNumbers(prev => ({ ...prev, [p.optimization.id]: e.target.value }))}
                            style={{ padding: '5px 8px', border: '1px solid #d1d5db', borderRadius: 4, fontSize: 12, width: 160 }}
                          />
                          <button
                            className="btn btn-primary btn-sm"
                            onClick={() => pushMut.mutate({ optId: p.optimization.id, manageNumber: manageNumbers[p.optimization.id] ?? p.optimization.manage_number ?? '' })}
                            disabled={pushMut.isPending || !(manageNumbers[p.optimization.id] ?? p.optimization.manage_number)}
                          >
                            🚀 RMS Push
                          </button>
                        </>
                      )}
                    </div>
                  )}
                  {pushMut.isError && pushMut.variables?.optId === p.optimization.id && (
                    <div style={{ color: '#e94560', fontSize: 12, marginTop: 6 }}>
                      Push失敗: {pushMut.error?.response?.data?.detail || pushMut.error?.message}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
