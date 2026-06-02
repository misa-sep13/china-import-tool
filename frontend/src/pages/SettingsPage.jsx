import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'

export default function SettingsPage() {
  const qc = useQueryClient()
  const [form, setForm] = useState(null)
  const [saved, setSaved] = useState(false)

  const { data } = useQuery({
    queryKey: ['settings'],
    queryFn: () => api.get('/settings/').then(r => r.data),
  })

  useEffect(() => { if (data) setForm(data) }, [data])

  const save = useMutation({
    mutationFn: (d) => api.put('/settings/', d),
    onSuccess: () => { qc.invalidateQueries(['settings']); setSaved(true); setTimeout(() => setSaved(false), 2000) },
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

  const handleSubmit = (e) => {
    e.preventDefault()
    save.mutate(form)
  }

  return (
    <div>
      <h1>⚙️ 設定</h1>
      <form onSubmit={handleSubmit}>
        <div className="card">
          <h2>発注トリガー・目標在庫日数</h2>
          <div className="form-grid">
            <div className="form-group">
              <label>発注トリガー残日数</label>
              <input type="number" min={1} {...f('threshold_days', 'number')} />
            </div>
            <div className="form-group">
              <label>通常時 目標在庫日数</label>
              <input type="number" min={1} {...f('target_days_normal', 'number')} />
            </div>
            <div className="form-group">
              <label>セール時 目標在庫日数</label>
              <input type="number" min={1} {...f('target_days_sale', 'number')} />
            </div>
            <div className="form-group">
              <label>最小発注数量</label>
              <input type="number" min={1} {...f('min_order_qty', 'number')} />
            </div>
          </div>
        </div>

        <div className="card">
          <h2>加重日販の重み（合計1.0）</h2>
          <div className="form-grid">
            <div className="form-group">
              <label>7日の重み</label>
              <input type="number" step="0.01" min={0} max={1} {...f('weight_d7', 'number')} />
            </div>
            <div className="form-group">
              <label>15日の重み</label>
              <input type="number" step="0.01" min={0} max={1} {...f('weight_d15', 'number')} />
            </div>
            <div className="form-group">
              <label>30日の重み</label>
              <input type="number" step="0.01" min={0} max={1} {...f('weight_d30', 'number')} />
            </div>
            <div className="form-group">
              <label>60日の重み</label>
              <input type="number" step="0.01" min={0} max={1} {...f('weight_d60', 'number')} />
            </div>
          </div>
        </div>

        <div className="card">
          <h2>成長・下落判定</h2>
          <div className="form-grid">
            <div className="form-group">
              <label>成長判定 倍率閾値</label>
              <input type="number" step="0.01" {...f('growth_ratio_threshold', 'number')} />
            </div>
            <div className="form-group">
              <label>成長時 発注倍率</label>
              <input type="number" step="0.01" {...f('growth_multiplier', 'number')} />
            </div>
            <div className="form-group">
              <label>下落判定 倍率閾値</label>
              <input type="number" step="0.01" {...f('decline_ratio_threshold', 'number')} />
            </div>
            <div className="form-group">
              <label>下落時 発注倍率</label>
              <input type="number" step="0.01" {...f('decline_multiplier', 'number')} />
            </div>
          </div>
        </div>

        <div className="card">
          <h2>セール期間設定</h2>
          <div className="form-grid">
            <div className="form-group" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <label style={{ marginBottom: 0 }}>
                <input type="checkbox" {...fb('sale_enabled')} style={{ width: 'auto', marginRight: 6 }} />
                セール期間を有効にする
              </label>
            </div>
            <div className="form-group">
              <label>セール開始日</label>
              <input type="date" {...f('sale_start')} disabled={!form.sale_enabled} />
            </div>
            <div className="form-group">
              <label>セール終了日</label>
              <input type="date" {...f('sale_end')} disabled={!form.sale_enabled} />
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
          <button type="submit" className="btn btn-primary" disabled={save.isPending}>
            {save.isPending ? '保存中...' : '💾 設定を保存'}
          </button>
          {saved && <span style={{ color: '#27ae60', fontSize: 13, fontWeight: 600 }}>✓ 保存しました</span>}
        </div>
      </form>
    </div>
  )
}
