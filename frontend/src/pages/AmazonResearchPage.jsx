import { useMemo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'

const yen = (v) => v == null ? '-' : `¥${Math.round(v).toLocaleString()}`
const num = (v) => (v === '' || v == null) ? null : Number(v)

/** 代行業者に頼む加工オプション。★タオタロウの料金表に合わせて調整する */
const AGENT_OPTIONS = [
  { label: '商品ラベル貼り付け', price: 0.80 },
  { label: '商品セット化作業', price: 1.00 },
  { label: 'OPP袋入れ替え', price: 0.50 },
  { label: '検品（簡易）', price: 0.50 },
  { label: '説明書封入', price: 0.30 },
]

/** 勝てる要素。競合の弱点＝自分が取れる差 */
const FACTORS = [
  '画像が弱い', 'レビュー数が少ない', 'レビューの星が低い',
  '梱包サイズに余地', 'セット数で差がつく', '厚みを薄くできる',
  'もともと薄い（2.2cm・3.3cm以下）', '商品ページが雑',
  '成約キーワードに穴がある', '自己配送で柔軟に動ける',
]

const STATUS = [
  { k: 'researching', l: 'リサーチ中', color: '#0369a1', bg: '#f0f9ff' },
  { k: 'ordered', l: '発注済み', color: '#166534', bg: '#f0fdf4' },
  { k: 'rejected', l: 'ボツ', color: '#991b1b', bg: '#fef2f2' },
]

/**
 * Amazon競合リサーチ。1商品1行で候補を並べ、原価と粗利率を出す。
 *
 * 原価はサーバー側で計算している（画面ごとに計算式がずれないように）。
 * 三辺・実重量・1688単価が欠けている行は「要確認」として原価を出さない。
 */
export default function AmazonResearchPage() {
  const qc = useQueryClient()
  const [researchId, setResearchId] = useState(null)
  const [statusFilter, setStatusFilter] = useState('')
  const [showSettings, setShowSettings] = useState(false)
  const [expanded, setExpanded] = useState({})   // {itemId: bool} 詳細の開閉

  const { data: rData } = useQuery({
    queryKey: ['amazon-researches'],
    queryFn: () => api.get('/amazon-research/researches').then(r => r.data),
  })
  const researches = rData?.researches || []
  const activeId = researchId ?? researches[0]?.id ?? null

  const { data: iData, isLoading } = useQuery({
    queryKey: ['amazon-research-items', activeId, statusFilter],
    queryFn: () => api.get('/amazon-research/items', {
      params: { research_id: activeId, ...(statusFilter ? { status: statusFilter } : {}) },
    }).then(r => r.data),
    enabled: !!activeId,
  })
  const items = iData?.items || []
  const settings = iData?.settings || {}

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['amazon-research-items'] })
    qc.invalidateQueries({ queryKey: ['amazon-researches'] })
  }

  const createResearch = useMutation({
    mutationFn: (name) => api.post('/amazon-research/researches', { name }).then(r => r.data),
    onSuccess: (d) => { setResearchId(d.id); refresh() },
    onError: (e) => alert('作成エラー: ' + (e.response?.data?.detail || e.message)),
  })

  const addItem = useMutation({
    mutationFn: () => api.post('/amazon-research/items',
      { research_id: activeId }).then(r => r.data),
    onSuccess: refresh,
    onError: (e) => alert('追加エラー: ' + (e.response?.data?.detail || e.message)),
  })

  const patchItem = useMutation({
    mutationFn: ({ id, body }) => api.patch(`/amazon-research/items/${id}`, body).then(r => r.data),
    onSuccess: refresh,
    onError: (e) => alert('更新エラー: ' + (e.response?.data?.detail || e.message)),
  })

  const delItem = useMutation({
    mutationFn: (id) => api.delete(`/amazon-research/items/${id}`),
    onSuccess: refresh,
  })

  const saveSettings = useMutation({
    mutationFn: (body) => api.put('/amazon-research/settings', body).then(r => r.data),
    onSuccess: refresh,
    onError: (e) => alert('保存エラー: ' + (e.response?.data?.detail || e.message)),
  })

  const set = (id, field, value) => patchItem.mutate({ id, body: { [field]: value } })

  const summary = useMemo(() => {
    const ok = items.filter(i => i.cost_jpy != null && i.profit_rate != null)
    if (!ok.length) return null
    const avg = ok.reduce((s, i) => s + i.profit_rate, 0) / ok.length
    const good = ok.filter(i => i.profit_rate >= 30).length
    return { count: items.length, calc: ok.length, avg: avg.toFixed(1), good }
  }, [items])

  return (
    <div>
      <div className="page-header">
        <h2>Amazon競合リサーチ</h2>
        <p style={{ color: '#64748b', fontSize: 13 }}>
          1商品1行で候補を並べ、リサーチ段階の情報だけから原価と粗利率を出します
        </p>
      </div>

      {/* リサーチの選択 */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <select value={activeId || ''} style={{ width: 'auto', minWidth: 200 }}
            onChange={e => setResearchId(Number(e.target.value) || null)}>
            {researches.length === 0 && <option value="">（リサーチがありません）</option>}
            {researches.map(r => (
              <option key={r.id} value={r.id}>{r.name}（{r.item_count}件）</option>
            ))}
          </select>
          <button className="btn btn-secondary" onClick={() => {
            const name = prompt('リサーチ名を入れてください（例: キッチン雑貨 2026春）')
            if (name?.trim()) createResearch.mutate(name.trim())
          }}>＋ 新しいリサーチ</button>

          <div style={{ display: 'flex', gap: 6, marginLeft: 8 }}>
            <button className={`btn ${!statusFilter ? 'btn-primary' : 'btn-secondary'}`}
              style={{ padding: '4px 12px', fontSize: 13 }}
              onClick={() => setStatusFilter('')}>すべて</button>
            {STATUS.map(s => (
              <button key={s.k}
                className={`btn ${statusFilter === s.k ? 'btn-primary' : 'btn-secondary'}`}
                style={{ padding: '4px 12px', fontSize: 13 }}
                onClick={() => setStatusFilter(s.k)}>{s.l}</button>
            ))}
          </div>

          <button className="btn btn-secondary" style={{ marginLeft: 'auto' }}
            onClick={() => setShowSettings(v => !v)}>
            ⚙ 原価の前提
          </button>
        </div>

        {/* 原価の前提 */}
        {showSettings && (
          <div style={{
            marginTop: 14, padding: 14, borderRadius: 8,
            background: '#f8fafc', border: '1px solid #e2e8f0',
          }}>
            <div style={{ fontSize: 12, color: '#475569', marginBottom: 10 }}>
              タオタロウの実績から出した初期値です（輸送単価は国際送料1,022元÷計費重量146kg、
              輸入関連費は納税額+通関料÷課税前原価）。1便からの実測なので、
              便が貯まったら実測値へ入れ替えてください。
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 10 }}>
              {[
                { k: 'exchange_rate', l: '市場為替（円/元）', step: '0.01', tip: '' },
                { k: 'rate_adjust', l: '決済レート補正（%）', step: '0.1' },
                { k: 'china_fixed', l: '中国側 基本作業費（元/点）', step: '0.01' },
                { k: 'ship_yuan', l: '輸送単価（元/kg）', step: '0.1' },
                { k: 'tariff_rate', l: '輸入関連費（%）', step: '0.1' },
                { k: 'pack_factor', l: '箱詰め係数の既定（%）', step: '1' },
              ].map(f => (
                <div className="form-group" style={{ margin: 0 }} key={f.k}>
                  <label>{f.l}</label>
                  <input type="number" step={f.step} defaultValue={settings[f.k] ?? ''}
                    onBlur={e => {
                      const v = num(e.target.value)
                      if (v !== settings[f.k]) saveSettings.mutate({ [f.k]: v })
                    }} />
                </div>
              ))}
            </div>
            <div style={{ marginTop: 10, fontSize: 13 }}>
              決済レート = <b>{settings.settle_rate ?? '-'}</b> 円/元
              {!settings.exchange_rate && (
                <span style={{ color: '#dc2626', marginLeft: 8 }}>
                  ⚠ 市場為替を入れるまで原価は出ません
                </span>
              )}
            </div>
          </div>
        )}
      </div>

      {/* サマリー */}
      {summary && (
        <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
          {[
            { l: '候補', v: `${summary.count}件` },
            { l: '原価が出た', v: `${summary.calc}件` },
            { l: '平均粗利率', v: `${summary.avg}%` },
            { l: '粗利30%以上', v: `${summary.good}件` },
          ].map(x => (
            <div key={x.l} className="card" style={{ margin: 0, minWidth: 140 }}>
              <div style={{ fontSize: 12, color: '#64748b' }}>{x.l}</div>
              <div style={{ fontSize: 22, fontWeight: 700 }}>{x.v}</div>
            </div>
          ))}
        </div>
      )}

      {!activeId ? (
        <div className="card" style={{ padding: 40, textAlign: 'center', color: '#9ca3af' }}>
          「＋ 新しいリサーチ」から始めてください
        </div>
      ) : isLoading ? (
        <div className="card" style={{ padding: 40, textAlign: 'center', color: '#9ca3af' }}>
          読み込み中...
        </div>
      ) : (
        <div className="card">
          <div style={{ marginBottom: 12 }}>
            <button className="btn btn-primary" onClick={() => addItem.mutate()}>
              ＋ 候補を追加
            </button>
          </div>

          {items.length === 0 ? (
            <div style={{ padding: 30, textAlign: 'center', color: '#9ca3af' }}>
              候補がありません
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr style={{ background: '#f8fafc', borderBottom: '2px solid #e2e8f0' }}>
                    {['', 'ASIN', '商品名', '月販', 'レビュー', '★',
                      '長辺', '中辺', '短辺', '重量', '売価', '手数料',
                      '決済kg', '原価', '粗利', '粗利率', '状態', ''].map((h, i) => (
                      <th key={i} style={{ padding: '8px 6px', whiteSpace: 'nowrap', fontSize: 12 }}>
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {items.map(it => {
                    const st = STATUS.find(s => s.k === it.status) || STATUS[0]
                    const bad = it.missing?.length > 0
                    return (
                      <>
                        <tr key={it.id} style={{
                          borderBottom: expanded[it.id] ? 'none' : '1px solid #f1f5f9',
                          background: it.status === 'rejected' ? '#fafafa' : undefined,
                          opacity: it.status === 'rejected' ? 0.6 : 1,
                        }}>
                          <td style={{ padding: '6px' }}>
                            <button className="btn btn-secondary"
                              style={{ padding: '2px 8px', fontSize: 11 }}
                              onClick={() => setExpanded(p => ({ ...p, [it.id]: !p[it.id] }))}>
                              {expanded[it.id] ? '▲' : '▼'}
                            </button>
                          </td>
                          <td style={{ padding: '6px' }}>
                            <input defaultValue={it.asin || ''} placeholder="B0..."
                              style={{ width: 100, fontFamily: 'monospace' }}
                              onBlur={e => e.target.value !== (it.asin || '')
                                && set(it.id, 'asin', e.target.value)} />
                          </td>
                          <td style={{ padding: '6px' }}>
                            <input defaultValue={it.competitor_name || ''} style={{ width: 180 }}
                              onBlur={e => e.target.value !== (it.competitor_name || '')
                                && set(it.id, 'competitor_name', e.target.value)} />
                          </td>
                          {[['monthly_sales', 64], ['review_count', 64], ['review_rate', 52]].map(([f, w]) => (
                            <td key={f} style={{ padding: '6px' }}>
                              <input type="number" step={f === 'review_rate' ? '0.1' : '1'}
                                defaultValue={it[f] ?? ''} style={{ width: w, background: '#f0fdf4' }}
                                onBlur={e => num(e.target.value) !== it[f]
                                  && set(it.id, f, num(e.target.value))} />
                            </td>
                          ))}
                          {[['len_a', 52], ['len_b', 52], ['len_c', 52], ['weight', 60],
                            ['price', 72], ['fee', 66]].map(([f, w]) => (
                            <td key={f} style={{ padding: '6px' }}>
                              <input type="number" step="0.01" defaultValue={it[f] ?? ''}
                                style={{ width: w }}
                                onBlur={e => num(e.target.value) !== it[f]
                                  && set(it.id, f, num(e.target.value))} />
                            </td>
                          ))}
                          <td style={{ padding: '6px', textAlign: 'right', whiteSpace: 'nowrap' }}>
                            {it.billable_kg ?? '-'}
                            {it.tier_label && (
                              <div style={{ fontSize: 10, color: '#94a3b8' }}>{it.tier_label}</div>
                            )}
                          </td>
                          <td style={{ padding: '6px', textAlign: 'right', whiteSpace: 'nowrap' }}>
                            {bad
                              ? <span style={{ color: '#dc2626', fontSize: 11, fontWeight: 700 }}>
                                  要確認
                                </span>
                              : yen(it.cost_jpy)}
                          </td>
                          <td style={{ padding: '6px', textAlign: 'right' }}>{yen(it.profit_jpy)}</td>
                          <td style={{
                            padding: '6px', textAlign: 'right', fontWeight: 700,
                            color: it.profit_rate == null ? undefined
                              : it.profit_rate >= 30 ? '#16a34a'
                              : it.profit_rate >= 15 ? '#d97706' : '#dc2626',
                          }}>
                            {it.profit_rate == null ? '-' : `${it.profit_rate}%`}
                          </td>
                          <td style={{ padding: '6px' }}>
                            <select defaultValue={it.status} style={{ width: 100, fontSize: 12 }}
                              onChange={e => set(it.id, 'status', e.target.value)}>
                              {STATUS.map(s => <option key={s.k} value={s.k}>{s.l}</option>)}
                            </select>
                          </td>
                          <td style={{ padding: '6px' }}>
                            <button className="btn btn-secondary"
                              style={{ padding: '2px 8px', fontSize: 11, color: '#dc2626' }}
                              onClick={() => { if (confirm('この候補を削除しますか？')) delItem.mutate(it.id) }}>
                              削除
                            </button>
                          </td>
                        </tr>

                        {/* 詳細（1688・オプション・勝てる要素） */}
                        {expanded[it.id] && (
                          <tr key={`${it.id}-d`} style={{ borderBottom: '1px solid #e2e8f0' }}>
                            <td colSpan={18} style={{ padding: '12px 16px', background: '#f8fafc' }}>
                              {bad && (
                                <div style={{
                                  padding: '8px 12px', marginBottom: 10, borderRadius: 6,
                                  background: '#fef2f2', border: '1px solid #fca5a5',
                                  color: '#991b1b', fontSize: 12,
                                }}>
                                  <b>要確認</b>：{it.missing.join('・')}が未入力のため原価を出していません。
                                  欠けたまま計算すると大型商品の原価を大幅に過小評価するためです
                                </div>
                              )}
                              {it.warns?.length > 0 && (
                                <div style={{
                                  padding: '8px 12px', marginBottom: 10, borderRadius: 6,
                                  background: '#fffbeb', border: '1px solid #fcd34d',
                                  color: '#92400e', fontSize: 12,
                                }}>
                                  ⚠ {it.warns.join(' / ')}
                                </div>
                              )}

                              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                                <div>
                                  <div style={{ fontWeight: 600, fontSize: 12, marginBottom: 6 }}>
                                    1688単価（単価 元 × 入数）
                                  </div>
                                  {(it.parts || []).map((p, i) => (
                                    <div key={i} style={{ display: 'flex', gap: 6, marginBottom: 4 }}>
                                      <input type="number" step="0.01" defaultValue={p.price}
                                        placeholder="単価(元)" style={{ width: 90 }}
                                        onBlur={e => {
                                          const parts = [...(it.parts || [])]
                                          parts[i] = { ...parts[i], price: Number(e.target.value || 0) }
                                          set(it.id, 'parts', parts)
                                        }} />
                                      <span style={{ lineHeight: '32px' }}>×</span>
                                      <input type="number" defaultValue={p.qty ?? 1}
                                        placeholder="入数" style={{ width: 70 }}
                                        onBlur={e => {
                                          const parts = [...(it.parts || [])]
                                          parts[i] = { ...parts[i], qty: Number(e.target.value || 1) }
                                          set(it.id, 'parts', parts)
                                        }} />
                                      <button className="btn btn-secondary"
                                        style={{ padding: '2px 8px', fontSize: 11 }}
                                        onClick={() => set(it.id, 'parts',
                                          (it.parts || []).filter((_, j) => j !== i))}>×</button>
                                    </div>
                                  ))}
                                  <button className="btn btn-secondary"
                                    style={{ padding: '2px 10px', fontSize: 12 }}
                                    onClick={() => set(it.id, 'parts',
                                      [...(it.parts || []), { price: 0, qty: 1 }])}>
                                    ＋ 部材を追加
                                  </button>
                                  <div style={{ fontSize: 11, color: '#64748b', marginTop: 4 }}>
                                    中国国内送料や加工費は含めないでください（基本作業費で加算されます）
                                  </div>

                                  <div style={{ fontWeight: 600, fontSize: 12, margin: '12px 0 6px' }}>
                                    1688 URL
                                  </div>
                                  {(it.urls_1688 || []).map((u, i) => (
                                    <div key={i} style={{ display: 'flex', gap: 6, marginBottom: 4 }}>
                                      <input defaultValue={u} placeholder="https://detail.1688.com/..."
                                        style={{ flex: 1 }}
                                        onBlur={e => {
                                          const urls = [...(it.urls_1688 || [])]
                                          urls[i] = e.target.value
                                          set(it.id, 'urls_1688', urls)
                                        }} />
                                      <button className="btn btn-secondary"
                                        style={{ padding: '2px 8px', fontSize: 11 }}
                                        onClick={() => set(it.id, 'urls_1688',
                                          (it.urls_1688 || []).filter((_, j) => j !== i))}>×</button>
                                    </div>
                                  ))}
                                  <button className="btn btn-secondary"
                                    style={{ padding: '2px 10px', fontSize: 12 }}
                                    onClick={() => set(it.id, 'urls_1688',
                                      [...(it.urls_1688 || []), ''])}>
                                    ＋ URLを追加
                                  </button>
                                </div>

                                <div>
                                  <div style={{ fontWeight: 600, fontSize: 12, marginBottom: 6 }}>
                                    オプション代（元/販売単位）
                                  </div>
                                  {AGENT_OPTIONS.map(o => {
                                    const on = (it.options || []).some(x => x.label === o.label)
                                    return (
                                      <label key={o.label} style={{
                                        display: 'flex', alignItems: 'center', gap: 6,
                                        fontSize: 12, marginBottom: 3, cursor: 'pointer',
                                      }}>
                                        <input type="checkbox" checked={on} style={{ width: 'auto' }}
                                          onChange={e => {
                                            const cur = it.options || []
                                            set(it.id, 'options', e.target.checked
                                              ? [...cur, { label: o.label, price: o.price }]
                                              : cur.filter(x => x.label !== o.label))
                                          }} />
                                        {o.label}（{o.price}元）
                                      </label>
                                    )
                                  })}

                                  <div style={{ fontWeight: 600, fontSize: 12, margin: '12px 0 6px' }}>
                                    勝てる要素
                                  </div>
                                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                                    {FACTORS.map(f => {
                                      const on = (it.winning_factors || []).includes(f)
                                      return (
                                        <button key={f}
                                          onClick={() => {
                                            const cur = it.winning_factors || []
                                            set(it.id, 'winning_factors', on
                                              ? cur.filter(x => x !== f) : [...cur, f])
                                          }}
                                          style={{
                                            padding: '3px 8px', fontSize: 11, borderRadius: 12,
                                            border: `1px solid ${on ? '#16a34a' : '#cbd5e1'}`,
                                            background: on ? '#f0fdf4' : '#fff',
                                            color: on ? '#166534' : '#64748b', cursor: 'pointer',
                                          }}>
                                          {f}
                                        </button>
                                      )
                                    })}
                                  </div>

                                  <div style={{ fontWeight: 600, fontSize: 12, margin: '12px 0 6px' }}>
                                    箱詰め係数（%）
                                  </div>
                                  <select defaultValue={it.pack_factor ?? ''} style={{ width: 140 }}
                                    onChange={e => set(it.id, 'pack_factor', num(e.target.value))}>
                                    <option value="">既定（{settings.pack_factor}%）</option>
                                    {[100, 95, 90, 85, 80].map(v =>
                                      <option key={v} value={v}>{v}%</option>)}
                                  </select>
                                  <div style={{ fontSize: 11, color: '#64748b', marginTop: 4 }}>
                                    容積重量にだけ掛かります。硬い箱は100%、柔らかい物ほど下げる
                                  </div>

                                  <div style={{ fontWeight: 600, fontSize: 12, margin: '12px 0 6px' }}>
                                    備考
                                  </div>
                                  <textarea rows={2} defaultValue={it.note || ''}
                                    style={{ width: '100%' }}
                                    onBlur={e => e.target.value !== (it.note || '')
                                      && set(it.id, 'note', e.target.value)} />
                                </div>
                              </div>

                              {it.cost_jpy != null && (
                                <div style={{ marginTop: 12, fontSize: 12, color: '#475569' }}>
                                  内訳: 中国側 {yen(it.china_jpy)} ＋ 国際送料 {yen(it.ship_jpy)}
                                  （送料比率 {it.ship_share}%）→ 輸入関連費 {settings.tariff_rate}% を掛けて
                                  <b> {yen(it.cost_jpy)}</b>
                                </div>
                              )}
                            </td>
                          </tr>
                        )}
                      </>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
