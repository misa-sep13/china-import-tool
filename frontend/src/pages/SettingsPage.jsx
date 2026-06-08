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
          <h2>発注計算（リードタイム）</h2>
          <p style={{ fontSize: 13, color: '#666', marginBottom: 12 }}>
            発注〜FBA着まで：代行会社着15日＋配送依頼10日＋FBA着20日＋余裕在庫日数＝合計
          </p>
          <div className="form-grid">
            <div className="form-group">
              <label style={{ whiteSpace: 'nowrap' }}>リードタイム合計日数</label>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <input type="number" min={1} {...f('lead_days', 'number')} style={{ width: 80 }} />
                <span style={{ color: '#888', fontSize: 13 }}>日（推奨: 93）</span>
              </div>
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
            <div className="form-group">
              <label>90日の重み</label>
              <input type="number" step="0.01" min={0} max={1} {...f('weight_d90', 'number')} />
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
            計算式: (販売数 − VINE数) ÷ 販売日数 × リードタイム（93日）
          </p>
          <div className="form-grid">
            <div className="form-group">
              <label style={{ marginBottom: 4 }}>
                <input type="checkbox" {...fb('new_product_exclude_vine')} style={{ width: 'auto', marginRight: 6 }} />
                VINE注文を販売数から除外する
              </label>
              <p style={{ fontSize: 12, color: '#888', margin: 0, paddingLeft: 22 }}>
                VINEの売上・経費（FBA手数料・Amazon手数料・仕入原価）も利益計算から除外されます
              </p>
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
            <div className="form-group">
              <label>セール期間の上乗せ日数</label>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <input type="number" min={0} {...f('sale_extra_days', 'number')} style={{ width: 80 }} disabled={!form.sale_enabled} />
                <span style={{ color: '#888', fontSize: 13 }}>日</span>
              </div>
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

      {/* 計算ロジック説明 */}
      <div className="card" style={{ marginTop: 32, background: '#fafafa', border: '1px solid #ebebeb' }}>
        <h2 style={{ marginBottom: 20, color: '#9ca3af' }}>📐 発注数計算ロジック</h2>

        {/* 新商品 */}
        <div style={{ marginBottom: 28 }}>
          <h3 style={{ fontSize: 15, fontWeight: 700, color: '#93c5fd', marginBottom: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ background: '#fcd34d', color: '#fff', borderRadius: 4, padding: '2px 8px', fontSize: 12 }}>NEW</span>
            新商品（初回売上から90日未満）
          </h3>
          <div style={{ background: '#fefce8', border: '1px solid #fde68a', borderRadius: 8, padding: '14px 18px', marginBottom: 12 }}>
            <div style={{ fontFamily: 'monospace', fontSize: 14, color: '#b45309', fontWeight: 600 }}>
              推奨発注数 = ceil( (累計販売数 − VINE数) ÷ 経過日数 × リードタイム − 在庫 )
            </div>
          </div>
          <table style={{ fontSize: 13, borderCollapse: 'collapse', width: '100%' }}>
            <tbody>
              <tr style={{ borderBottom: '1px solid #f3f4f6' }}>
                <td style={{ padding: '6px 12px', fontWeight: 600, color: '#9ca3af', width: 160 }}>累計販売数</td>
                <td style={{ padding: '6px 12px', color: '#9ca3af' }}>SP-API orderMetrics（月次、過去365日）で初回売上月を特定し、それ以降の合計販売数</td>
              </tr>
              <tr style={{ borderBottom: '1px solid #f3f4f6' }}>
                <td style={{ padding: '6px 12px', fontWeight: 600, color: '#9ca3af' }}>VINE数</td>
                <td style={{ padding: '6px 12px', color: '#9ca3af' }}>「VINE注文を除外」がONの場合、Tool4SellerのVINEプロモーション注文数を引く</td>
              </tr>
              <tr style={{ borderBottom: '1px solid #f3f4f6' }}>
                <td style={{ padding: '6px 12px', fontWeight: 600, color: '#9ca3af' }}>経過日数</td>
                <td style={{ padding: '6px 12px', color: '#9ca3af' }}>初回売上日から本日までの日数</td>
              </tr>
              <tr>
                <td style={{ padding: '6px 12px', fontWeight: 600, color: '#9ca3af' }}>リードタイム</td>
                <td style={{ padding: '6px 12px', color: '#9ca3af' }}>設定値（デフォルト93日）</td>
              </tr>
            </tbody>
          </table>
        </div>

        {/* 既存商品 */}
        <div style={{ marginBottom: 28 }}>
          <h3 style={{ fontSize: 15, fontWeight: 700, color: '#9ca3af', marginBottom: 12 }}>
            📦 既存商品（初回売上から90日以上）
          </h3>
          <div style={{ background: '#f0f9ff', border: '1px solid #e0f2fe', borderRadius: 8, padding: '14px 18px', marginBottom: 12 }}>
            <div style={{ fontFamily: 'monospace', fontSize: 14, color: '#7dd3fc', fontWeight: 600 }}>
              推奨発注数 = ceil( 加重平均日販 × 成長補正 × リードタイム − 在庫 )
            </div>
          </div>
          <h4 style={{ fontSize: 13, fontWeight: 700, color: '#9ca3af', marginBottom: 8 }}>加重平均日販の内訳</h4>
          <table style={{ fontSize: 13, borderCollapse: 'collapse', width: '100%', marginBottom: 16 }}>
            <thead>
              <tr style={{ background: '#f9fafb' }}>
                <th style={{ padding: '6px 12px', textAlign: 'left', fontWeight: 600, color: '#9ca3af' }}>期間</th>
                <th style={{ padding: '6px 12px', textAlign: 'right', fontWeight: 600, color: '#9ca3af' }}>重み</th>
                <th style={{ padding: '6px 12px', textAlign: 'left', fontWeight: 600, color: '#9ca3af' }}>意味</th>
              </tr>
            </thead>
            <tbody>
              {[
                ['直近7日', '5%', '最新のトレンドに少し反応'],
                ['直近15日', '15%', '短期的な動向'],
                ['直近30日', '25%', '月次ベース'],
                ['直近60日', '25%', '中期トレンド'],
                ['直近90日', '30%', '安定した長期実績（最大ウェイト）'],
              ].map(([period, weight, desc]) => (
                <tr key={period} style={{ borderBottom: '1px solid #f3f4f6' }}>
                  <td style={{ padding: '6px 12px', fontWeight: 600, color: '#9ca3af' }}>{period}</td>
                  <td style={{ padding: '6px 12px', textAlign: 'right', fontFamily: 'monospace', color: '#93c5fd', fontWeight: 700 }}>{weight}</td>
                  <td style={{ padding: '6px 12px', color: '#9ca3af' }}>{desc}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h4 style={{ fontSize: 13, fontWeight: 700, color: '#9ca3af', marginBottom: 8 }}>成長補正（0.5 〜 1.0）</h4>
          <table style={{ fontSize: 13, borderCollapse: 'collapse', width: '100%' }}>
            <tbody>
              <tr style={{ borderBottom: '1px solid #f3f4f6' }}>
                <td style={{ padding: '6px 12px', fontWeight: 600, color: '#9ca3af', width: 240 }}>計算式</td>
                <td style={{ padding: '6px 12px', fontFamily: 'monospace', color: '#9ca3af' }}>(直近7日 + 直近15日) / 2 ÷ 直近90日</td>
              </tr>
              <tr style={{ borderBottom: '1px solid #f3f4f6' }}>
                <td style={{ padding: '6px 12px', fontWeight: 600, color: '#fca5a5' }}>比率 ≤ 0.7（売上が減少）</td>
                <td style={{ padding: '6px 12px', color: '#9ca3af' }}>補正 = <strong>0.5</strong>（下限）で発注を抑制</td>
              </tr>
              <tr style={{ borderBottom: '1px solid #f3f4f6' }}>
                <td style={{ padding: '6px 12px', fontWeight: 600, color: '#86efac' }}>比率 ≥ 1.3（売上が増加）</td>
                <td style={{ padding: '6px 12px', color: '#9ca3af' }}>補正 = <strong>1.0</strong>（上限）で過剰発注を防止</td>
              </tr>
              <tr>
                <td style={{ padding: '6px 12px', fontWeight: 600, color: '#9ca3af' }}>0.7 〜 1.3の間</td>
                <td style={{ padding: '6px 12px', color: '#9ca3af' }}>比率に応じて線形補間</td>
              </tr>
            </tbody>
          </table>
        </div>

        {/* リードタイム */}
        <div>
          <h3 style={{ fontSize: 15, fontWeight: 700, color: '#9ca3af', marginBottom: 12 }}>
            🚢 リードタイム内訳（デフォルト 93日）
          </h3>
          <table style={{ fontSize: 13, borderCollapse: 'collapse', width: '100%' }}>
            <thead>
              <tr style={{ background: '#f9fafb' }}>
                <th style={{ padding: '6px 12px', textAlign: 'left', fontWeight: 600, color: '#9ca3af' }}>フェーズ</th>
                <th style={{ padding: '6px 12px', textAlign: 'right', fontWeight: 600, color: '#9ca3af' }}>日数</th>
              </tr>
            </thead>
            <tbody>
              {[
                ['発注 → 代行会社着', '15日'],
                ['配送依頼 → 発送', '10日'],
                ['発送 → FBA着', '20日'],
                ['FBA検品・受入', '5日'],
                ['余裕在庫（バッファ）', '43日'],
              ].map(([phase, days]) => (
                <tr key={phase} style={{ borderBottom: '1px solid #f3f4f6' }}>
                  <td style={{ padding: '6px 12px', color: '#9ca3af' }}>{phase}</td>
                  <td style={{ padding: '6px 12px', textAlign: 'right', fontFamily: 'monospace', fontWeight: 600, color: '#9ca3af' }}>{days}</td>
                </tr>
              ))}
              <tr style={{ background: '#f9fafb', fontWeight: 700 }}>
                <td style={{ padding: '6px 12px', color: '#9ca3af' }}>合計</td>
                <td style={{ padding: '6px 12px', textAlign: 'right', fontFamily: 'monospace', color: '#9ca3af' }}>93日</td>
              </tr>
            </tbody>
          </table>
          <p style={{ fontSize: 12, color: '#c4c4c4', marginTop: 10 }}>
            ※ リードタイムは「発注計算（リードタイム）」セクションで変更できます。セール期間中は上乗せ日数を加算します。
          </p>
        </div>
      </div>
    </div>
  )
}
