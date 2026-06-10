import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'

export default function RakutenSettingsPage() {
  const qc = useQueryClient()
  const [form, setForm] = useState(null)
  const [saved, setSaved] = useState(false)

  const { data } = useQuery({
    queryKey: ['rakuten-settings'],
    queryFn: () => api.get('/rakuten/settings').then(r => r.data),
  })

  useEffect(() => { if (data) setForm(data) }, [data])

  const save = useMutation({
    mutationFn: (d) => api.put('/rakuten/settings', d),
    onSuccess: () => {
      qc.invalidateQueries(['rakuten-settings'])
      qc.invalidateQueries(['rakuten-recommendations'])
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    },
  })

  if (!form) return <div className="loading">読み込み中...</div>

  const f = (k, type = 'text') => ({
    value: form[k] ?? '',
    onChange: e => setForm(p => ({ ...p, [k]: type === 'number' ? Number(e.target.value) : e.target.value }))
  })
  const fb = (k) => ({
    checked: form[k],
    onChange: e => setForm(p => ({ ...p, [k]: e.target.checked }))
  })

  // 現在の設定から提案発注数のイメージを計算して表示
  const exampleDaily = 5
  const predicted = exampleDaily * form.target_days
  const leadSales = (predicted / form.target_days) * form.lead_days
  const safety = (predicted + leadSales) * form.safety_stock_rate
  const exampleStock = 50
  const exampleOrder = Math.max(0, Math.round(predicted + leadSales + safety - exampleStock))

  return (
    <div>
      <h1 style={{ marginBottom: 24 }}>🛒 楽天 設定</h1>

      <form onSubmit={e => { e.preventDefault(); save.mutate(form) }}>

        {/* 発注計算設定 */}
        <div className="card">
          <h2>📦 発注計算</h2>
          <p style={{ fontSize: 13, color: '#666', marginBottom: 16 }}>
            提案発注数 ＝ 予測販売数（{form.target_days}日）＋ 入荷まで売れる数（{form.lead_days}日）＋ 安全在庫（{Math.round(form.safety_stock_rate * 100)}%）− 全在庫
          </p>
          <div className="form-grid">
            <div className="form-group">
              <label>予測販売日数（目標在庫日数）</label>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <input type="number" min={1} {...f('target_days', 'number')} style={{ width: 80 }} />
                <span style={{ color: '#888', fontSize: 13 }}>日</span>
              </div>
              <p style={{ fontSize: 12, color: '#888', marginTop: 4 }}>直近30日販売数を基に、この日数分の予測販売数を計算します</p>
            </div>
            <div className="form-group">
              <label>リードタイム（発注〜入荷）</label>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <input type="number" min={1} {...f('lead_days', 'number')} style={{ width: 80 }} />
                <span style={{ color: '#888', fontSize: 13 }}>日</span>
              </div>
              <p style={{ fontSize: 12, color: '#888', marginTop: 4 }}>発注してから入荷するまでの期間</p>
            </div>
            <div className="form-group">
              <label>安全在庫率（バッファ）</label>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <input
                  type="number" min={0} max={100} step={1}
                  value={Math.round(form.safety_stock_rate * 100)}
                  onChange={e => setForm(p => ({ ...p, safety_stock_rate: Number(e.target.value) / 100 }))}
                  style={{ width: 80 }}
                />
                <span style={{ color: '#888', fontSize: 13 }}>%</span>
              </div>
              <p style={{ fontSize: 12, color: '#888', marginTop: 4 }}>（予測販売数 + 入荷まで） × この率 = 安全在庫</p>
            </div>
            <div className="form-group">
              <label>発注タイミング閾値（在庫量設定日数）</label>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <input type="number" min={1} {...f('threshold_days', 'number')} style={{ width: 80 }} />
                <span style={{ color: '#888', fontSize: 13 }}>日</span>
              </div>
              <p style={{ fontSize: 12, color: '#888', marginTop: 4 }}>全在庫がこの日数分を下回るとオレンジ表示 + 発注リストに表示</p>
            </div>
          </div>

          {/* 計算例 */}
          <div style={{ background: '#0f172a', border: '1px solid #2d3748', borderRadius: 8, padding: '14px 18px', marginTop: 8 }}>
            <div style={{ fontSize: 12, color: '#64748b', marginBottom: 8, fontWeight: 700 }}>📐 計算例（日販5個・現在庫50個の場合）</div>
            <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', fontSize: 13 }}>
              {[
                ['予測販売数', `5 × ${form.target_days}日 = ${predicted}個`],
                ['入荷まで', `(${predicted}÷${form.target_days}) × ${form.lead_days}日 = ${Math.round(leadSales)}個`],
                ['安全在庫', `(${predicted}+${Math.round(leadSales)}) × ${Math.round(form.safety_stock_rate * 100)}% = ${Math.round(safety)}個`],
                ['提案発注数', `${predicted}+${Math.round(leadSales)}+${Math.round(safety)}-50 = ${exampleOrder}個`],
              ].map(([label, val]) => (
                <div key={label}>
                  <span style={{ color: '#64748b' }}>{label}：</span>
                  <span style={{ color: '#e2e8f0', fontFamily: 'monospace', fontWeight: 600 }}>{val}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* スーパーセール設定 */}
        <div className="card" style={{ marginTop: 20 }}>
          <h2>🎉 スーパーセール設定</h2>
          <div className="form-grid">
            <div className="form-group" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <label style={{ marginBottom: 0 }}>
                <input type="checkbox" {...fb('super_sale_enabled')} style={{ width: 'auto', marginRight: 6 }} />
                スーパーセール期間を設定する
              </label>
            </div>

            {/* モード選択 */}
            <div className="form-group" style={{ gridColumn: '1 / -1' }}>
              <label>セール期間の扱い</label>
              <div style={{ display: 'flex', gap: 24, marginTop: 8 }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', marginBottom: 0 }}>
                  <input
                    type="radio" name="super_sale_mode" value="A"
                    checked={form.super_sale_mode === 'A'}
                    onChange={() => setForm(p => ({ ...p, super_sale_mode: 'A' }))}
                    disabled={!form.super_sale_enabled}
                    style={{ width: 'auto' }}
                  />
                  <div>
                    <div style={{ fontWeight: 600, color: form.super_sale_mode === 'A' ? '#e2e8f0' : '#64748b' }}>除外モード</div>
                    <div style={{ fontSize: 12, color: '#64748b' }}>セール期間の販売数を除外して通常の発注数を計算（在庫切れ期間と同義）</div>
                  </div>
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', marginBottom: 0 }}>
                  <input
                    type="radio" name="super_sale_mode" value="B"
                    checked={form.super_sale_mode === 'B'}
                    onChange={() => setForm(p => ({ ...p, super_sale_mode: 'B' }))}
                    disabled={!form.super_sale_enabled}
                    style={{ width: 'auto' }}
                  />
                  <div>
                    <div style={{ fontWeight: 600, color: form.super_sale_mode === 'B' ? '#e2e8f0' : '#64748b' }}>反映モード</div>
                    <div style={{ fontSize: 12, color: '#64748b' }}>通常の発注数 + 前回スーパーセール販売数を上乗せ</div>
                  </div>
                </label>
              </div>
            </div>

            <div className="form-group">
              <label>スーパーセール 開始日</label>
              <input type="date" {...f('super_sale_start')} disabled={!form.super_sale_enabled} />
            </div>
            <div className="form-group">
              <label>スーパーセール 終了日</label>
              <input type="date" {...f('super_sale_end')} disabled={!form.super_sale_enabled} />
            </div>
          </div>

          {form.super_sale_enabled && (
            <div style={{
              background: form.super_sale_mode === 'A' ? '#1e293b' : '#1a1a2e',
              border: `1px solid ${form.super_sale_mode === 'A' ? '#475569' : '#7c3aed'}`,
              borderRadius: 8, padding: '12px 16px', marginTop: 8, fontSize: 13
            }}>
              {form.super_sale_mode === 'A' ? (
                <span style={{ color: '#94a3b8' }}>
                  📅 <strong style={{ color: '#e2e8f0' }}>{form.super_sale_start || '未設定'} 〜 {form.super_sale_end || '未設定'}</strong> の販売数を除外して計算します
                </span>
              ) : (
                <span style={{ color: '#94a3b8' }}>
                  ✨ <strong style={{ color: '#e2e8f0' }}>{form.super_sale_start || '未設定'} 〜 {form.super_sale_end || '未設定'}</strong> の販売数を通常発注数に上乗せします<br />
                  <span style={{ fontSize: 12, marginTop: 4, display: 'block' }}>※ セール販売数は商品マスタの「スーパーセール販売数」欄から入力します</span>
                </span>
              )}
            </div>
          )}
        </div>

        {/* 楽天市場セール参考 */}
        <div className="card" style={{ marginTop: 20 }}>
          <h2>📅 楽天市場 主要セール参考カレンダー</h2>
          <table style={{ fontSize: 12, borderCollapse: 'collapse', width: '100%' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #2d3748' }}>
                <th style={{ padding: '6px 12px', textAlign: 'left', color: '#64748b' }}>セール名</th>
                <th style={{ padding: '6px 12px', textAlign: 'left', color: '#64748b' }}>開催時期</th>
                <th style={{ padding: '6px 12px', textAlign: 'left', color: '#64748b' }}>期間</th>
              </tr>
            </thead>
            <tbody>
              {[
                ['スーパーSALE',      '3月・6月・9月・12月（年4回）', '約1週間', '#fef2f2'],
                ['お買い物マラソン',   '毎月1〜2回',                  '約10日間', '#fef9c3'],
                ['ポイントアップ祭',   '不定期（月1〜2回）',           '数日間',   '#f0fdf4'],
                ['39ショップ感謝デー', '毎月9日・19日・29日前後',       '1〜3日',   '#f8fafc'],
                ['新春初売りセール',   '1月上旬',                      '約1週間',  '#f8fafc'],
              ].map(([name, timing, duration, bg]) => (
                <tr key={name} style={{ borderBottom: '1px solid #1e293b', background: bg }}>
                  <td style={{ padding: '7px 12px', color: '#374151', fontWeight: 500 }}>{name}</td>
                  <td style={{ padding: '7px 12px', color: '#6b7280' }}>{timing}</td>
                  <td style={{ padding: '7px 12px', color: '#6b7280' }}>{duration}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p style={{ fontSize: 11, color: '#64748b', marginTop: 8 }}>※ スーパーSALEは楽天最大級のセール。6月・12月が特に大きいです。</p>
        </div>

        <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginTop: 24 }}>
          <button type="submit" className="btn btn-primary" disabled={save.isPending}>
            {save.isPending ? '保存中...' : '💾 設定を保存'}
          </button>
          {saved && <span style={{ color: '#27ae60', fontSize: 13, fontWeight: 600 }}>✓ 保存しました</span>}
        </div>
      </form>
    </div>
  )
}
