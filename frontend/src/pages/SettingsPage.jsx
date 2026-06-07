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
          <h2>価格自動調整</h2>
          <div className="form-grid">
            <div className="form-group" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <label style={{ marginBottom: 0 }}>
                <input type="checkbox" {...fb('price_adjust_enabled')} style={{ width: 'auto', marginRight: 6 }} />
                価格自動調整を有効にする（毎週月曜に提案生成）
              </label>
            </div>
            <div className="form-group">
              <label>値下げ判定: 前期比何%減で値下げ提案</label>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <input type="number" step="1" min={1} max={99}
                  value={Math.round((form.price_drop_threshold ?? 0.20) * 100)}
                  onChange={e => setForm(p => ({ ...p, price_drop_threshold: Number(e.target.value) / 100 }))}
                  style={{ width: 70 }} />
                <span style={{ color: '#888', fontSize: 13 }}>%</span>
              </div>
            </div>
            <div className="form-group">
              <label>価格変更幅（現在価格の何%、10円単位）</label>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <input type="number" step="1" min={1} max={20}
                  value={Math.round((form.price_change_pct ?? 0.03) * 100)}
                  onChange={e => setForm(p => ({ ...p, price_change_pct: Number(e.target.value) / 100 }))}
                  style={{ width: 70 }} />
                <span style={{ color: '#888', fontSize: 13 }}>%</span>
              </div>
            </div>
            <div className="form-group">
              <label>価格下限: 最低利益率</label>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <input type="number" step="1" min={0} max={50}
                  value={Math.round((form.min_profit_rate ?? 0.10) * 100)}
                  onChange={e => setForm(p => ({ ...p, min_profit_rate: Number(e.target.value) / 100 }))}
                  style={{ width: 70 }} />
                <span style={{ color: '#888', fontSize: 13 }}>%</span>
              </div>
            </div>
          </div>
        </div>

        <div className="card">
          <h2>利益計算</h2>
          <div className="form-grid">
            <div className="form-group">
              <label>為替レート（円/元）</label>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <input type="number" step="0.1" min={1} {...f('exchange_rate', 'number')} style={{ width: 100 }} />
                <span style={{ color: '#888', fontSize: 13 }}>円 / 1元</span>
              </div>
            </div>
          </div>
        </div>

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
          <h2>新商品 発注数計算</h2>
          <p style={{ fontSize: 13, color: '#666', marginBottom: 12 }}>
            計算式: (販売数 − VINE数) ÷ 販売日数 × 必要日数
          </p>
          <div className="form-grid">
            <div className="form-group">
              <label>必要日数（目標在庫日数）</label>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <input type="number" min={1} max={365} {...f('new_product_required_days', 'number')} style={{ width: 80 }} />
                <span style={{ color: '#888', fontSize: 13 }}>日</span>
              </div>
            </div>
            <div className="form-group" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <label style={{ marginBottom: 0 }}>
                <input type="checkbox" {...fb('new_product_exclude_vine')} style={{ width: 'auto', marginRight: 6 }} />
                VINE注文を販売数から除外する
              </label>
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
