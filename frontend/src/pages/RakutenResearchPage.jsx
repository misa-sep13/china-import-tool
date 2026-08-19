import { useState, useEffect, useCallback } from 'react'
import api from '../api/client'

const TYPE_LABEL = { shop: 'セラー', keyword: 'キーワード', genre: 'ジャンル' }
const TYPE_INPUT_LABEL = {
  shop: 'ショップコード（店舗URLの識別子）',
  keyword: '検索キーワード',
  genre: 'ジャンルID',
}

export default function RakutenResearchPage() {
  const [tab, setTab] = useState('candidates') // 'candidates' | 'watchlist'

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>商品リサーチ</h2>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => setTab('candidates')} style={tab === 'candidates' ? btnPrimary : btnSecondary}>
            候補一覧
          </button>
          <button onClick={() => setTab('watchlist')} style={tab === 'watchlist' ? btnPrimary : btnSecondary}>
            ピックアップ済み
          </button>
        </div>
      </div>

      {tab === 'candidates' ? <CandidatesTab /> : <WatchlistTab />}
    </div>
  )
}

// ============================================================
// 候補一覧タブ
// ============================================================

function CandidatesTab() {
  const [targets, setTargets] = useState([])
  const [targetId, setTargetId] = useState('')
  const [keyword, setKeyword] = useState('')
  const [minReview, setMinReview] = useState('')
  const [maxReview, setMaxReview] = useState('')
  const [minPrice, setMinPrice] = useState('')
  const [maxPrice, setMaxPrice] = useState('')
  const [sort, setSort] = useState('review_delta')
  const [candidates, setCandidates] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showTargetManage, setShowTargetManage] = useState(false)
  const [pickingCode, setPickingCode] = useState('')

  const fetchTargets = useCallback(async () => {
    const res = await api.get('/research/targets')
    setTargets(res.data.targets || [])
  }, [])

  const fetchCandidates = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const params = { sort, order: 'desc' }
      if (targetId) params.target_id = targetId
      if (keyword) params.keyword = keyword
      if (minReview) params.min_review = minReview
      if (maxReview) params.max_review = maxReview
      if (minPrice) params.min_price = minPrice
      if (maxPrice) params.max_price = maxPrice
      const res = await api.get('/research/candidates', { params })
      setCandidates(res.data.candidates || [])
    } catch (e) {
      setError('候補の取得に失敗しました')
    }
    setLoading(false)
  }, [targetId, keyword, minReview, maxReview, minPrice, maxPrice, sort])

  useEffect(() => { fetchTargets() }, [fetchTargets])
  useEffect(() => { fetchCandidates() }, [fetchCandidates])

  const handlePick = async (c) => {
    setPickingCode(c.item_code)
    try {
      await api.post('/research/watchlist', {
        item_code: c.item_code,
        item_name: c.item_name,
        item_price: c.item_price,
        review_count: c.review_count,
        review_average: c.review_average,
        shop_code: c.shop_code,
        shop_name: c.shop_name,
        item_url: c.item_url,
        image_url: c.image_url,
      })
      setCandidates(prev => prev.map(x => x.item_code === c.item_code ? { ...x, picked: true } : x))
    } catch (e) {
      alert('ピックアップに失敗しました')
    }
    setPickingCode('')
  }

  return (
    <div>
      <div style={{ ...card, marginBottom: 16, display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <select value={targetId} onChange={e => setTargetId(e.target.value)} style={selectStyle}>
          <option value="">すべての対象</option>
          {targets.map(t => (
            <option key={t.id} value={t.id}>
              [{TYPE_LABEL[t.type] || t.type}] {t.label}{!t.is_active ? '（停止中）' : ''}
            </option>
          ))}
        </select>
        <input
          placeholder="商品名・ショップ名で絞り込み"
          value={keyword}
          onChange={e => setKeyword(e.target.value)}
          style={{ ...inputStyle, width: 220 }}
        />
        <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          <span style={{ fontSize: 12, color: '#6b7280' }}>レビュー数</span>
          <input
            placeholder="以上"
            type="number"
            value={minReview}
            onChange={e => setMinReview(e.target.value)}
            style={{ ...inputStyle, width: 90 }}
          />
          <span style={{ fontSize: 12, color: '#6b7280' }}>〜</span>
          <input
            placeholder="以下"
            type="number"
            value={maxReview}
            onChange={e => setMaxReview(e.target.value)}
            style={{ ...inputStyle, width: 90 }}
          />
        </div>
        <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          <span style={{ fontSize: 12, color: '#6b7280' }}>価格</span>
          <input
            placeholder="以上"
            type="number"
            value={minPrice}
            onChange={e => setMinPrice(e.target.value)}
            style={{ ...inputStyle, width: 90 }}
          />
          <span style={{ fontSize: 12, color: '#6b7280' }}>〜</span>
          <input
            placeholder="以下"
            type="number"
            value={maxPrice}
            onChange={e => setMaxPrice(e.target.value)}
            style={{ ...inputStyle, width: 90 }}
          />
        </div>
        <select value={sort} onChange={e => setSort(e.target.value)} style={selectStyle}>
          <option value="review_delta">レビュー増加数順（伸び）</option>
          <option value="review_count">レビュー数順</option>
          <option value="price">価格順</option>
          <option value="review_average">評価順</option>
          <option value="rank">ジャンル別ランキング順</option>
        </select>
        <div style={{ flex: 1 }} />
        <button onClick={() => setShowTargetManage(true)} style={btnSecondary}>対象管理</button>
      </div>

      {loading ? (
        <div style={emptyBox}>読み込み中...</div>
      ) : error ? (
        <div style={{ ...emptyBox, background: '#fef2f2', border: '1px solid #fca5a5', color: '#991b1b' }}>{error}</div>
      ) : candidates.length === 0 ? (
        <div style={emptyBox}>
          候補がありません。対象を登録してローカルバッチを実行してください。
        </div>
      ) : (
        <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 8 }}>{candidates.length}件</div>
      )}

      <div style={grid}>
        {candidates.map(c => (
          /* 同じ商品がセラーとキーワードの両方に出ることがある。item_codeだけだと
             キーが重複してReactの再描画が壊れるので、対象IDと組み合わせる */
          <ProductCard
            key={`${c.research_target_id}-${c.item_code}`}
            item={c}
            actionLabel={c.picked ? '✓ ピックアップ済み' : 'ピックアップ'}
            actionDisabled={c.picked || pickingCode === c.item_code}
            onAction={() => handlePick(c)}
          />
        ))}
      </div>

      {showTargetManage && (
        <TargetManageModal
          targets={targets}
          onClose={() => setShowTargetManage(false)}
          onChanged={fetchTargets}
        />
      )}
    </div>
  )
}

function TargetManageModal({ targets, onClose, onChanged }) {
  const [type, setType] = useState('shop')
  const [value, setValue] = useState('')
  const [label, setLabel] = useState('')

  const handleAdd = async () => {
    if (!value.trim()) return
    await api.post('/research/targets', { type, value: value.trim(), label: label.trim() || null })
    setValue(''); setLabel('')
    onChanged()
  }

  const handleToggle = async (t) => {
    await api.put(`/research/targets/${t.id}`, { is_active: !t.is_active })
    onChanged()
  }

  const handleDelete = async (t) => {
    if (!confirm(`「${t.label}」を削除しますか？（この対象の候補も削除されます）`)) return
    await api.delete(`/research/targets/${t.id}`)
    onChanged()
  }

  return (
    <div style={overlay} onClick={onClose}>
      <div style={modal} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <h3 style={{ margin: 0 }}>リサーチ対象管理</h3>
          <button onClick={onClose} style={btnSecondary}>閉じる</button>
        </div>

        <div style={{ ...card, marginBottom: 16, display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <label style={labelStyle}>
            種類
            <select value={type} onChange={e => setType(e.target.value)} style={selectStyle}>
              <option value="shop">セラー（ショップ）</option>
              <option value="keyword">キーワード</option>
              <option value="genre">ジャンルID</option>
            </select>
          </label>
          <label style={labelStyle}>
            {TYPE_INPUT_LABEL[type]}
            <input value={value} onChange={e => setValue(e.target.value)} style={inputStyle} />
          </label>
          <label style={labelStyle}>
            表示名（任意）
            <input value={label} onChange={e => setLabel(e.target.value)} style={inputStyle} />
          </label>
          <button onClick={handleAdd} style={btnPrimary}>+ 追加</button>
        </div>

        <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 16, lineHeight: 1.7 }}>
          {type === 'shop' && (
            <>
              <b>セラー（ショップ）</b>：そのショップの商品を、レビューが多い順に最大120件まとめて取得します。<br />
              入力するのは店舗URLの識別子です。店舗ページのURLが
              <code style={codeStyle}>https://www.rakuten.co.jp/ponopono/</code>
              なら <code style={codeStyle}>ponopono</code> と入力してください（店舗の表示名では取得できません）。
            </>
          )}
          {type === 'keyword' && (
            <>
              <b>キーワード</b>：楽天の検索結果の上位30件を取得します。
              検索結果の並び順は楽天のランキングとは別物なので、順位は表示しません。
            </>
          )}
          {type === 'genre' && (
            <>
              <b>ジャンルID</b>：そのジャンルのリアルタイムランキング上位30件を取得します。
              こちらは楽天が出している実際の順位が表示されます。
            </>
          )}
        </div>

        <table style={tableStyle}>
          <thead>
            <tr>
              <th style={thStyle}>種類</th>
              <th style={thStyle}>値</th>
              <th style={thStyle}>表示名</th>
              <th style={thStyle}>状態</th>
              <th style={thStyle}>操作</th>
            </tr>
          </thead>
          <tbody>
            {targets.map(t => (
              <tr key={t.id} style={{ opacity: t.is_active ? 1 : 0.5 }}>
                <td style={tdStyle}>{TYPE_LABEL[t.type] || t.type}</td>
                <td style={tdStyle}>{t.value}</td>
                <td style={tdStyle}>{t.label}</td>
                <td style={tdStyle}>{t.is_active ? '有効' : '停止中'}</td>
                <td style={tdStyle}>
                  <div style={{ display: 'flex', gap: 4 }}>
                    <button onClick={() => handleToggle(t)} style={btnSmall}>
                      {t.is_active ? '停止' : '再開'}
                    </button>
                    <button onClick={() => handleDelete(t)} style={{ ...btnSmall, color: '#dc2626' }}>削除</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {targets.length === 0 && (
          <div style={{ padding: 20, textAlign: 'center', color: '#9ca3af' }}>対象がまだありません</div>
        )}
      </div>
    </div>
  )
}

// ============================================================
// ピックアップ済み（ウォッチリスト）タブ
// ============================================================

function WatchlistTab() {
  const [items, setItems] = useState([])
  const [sort, setSort] = useState('picked_at')
  const [loading, setLoading] = useState(true)

  const fetchItems = useCallback(async () => {
    setLoading(true)
    const res = await api.get('/research/watchlist', { params: { sort, order: 'desc' } })
    setItems(res.data.items || [])
    setLoading(false)
  }, [sort])

  useEffect(() => { fetchItems() }, [fetchItems])

  const handleUpdate = async (id, patch) => {
    setItems(prev => prev.map(x => x.id === id ? { ...x, ...patch } : x))
    await api.put(`/research/watchlist/${id}`, patch)
  }

  const handleDelete = async (id) => {
    if (!confirm('ウォッチリストから外しますか？')) return
    await api.delete(`/research/watchlist/${id}`)
    fetchItems()
  }

  const handleExportCsv = () => {
    const header = ['商品名', 'ショップ名', '価格', 'レビュー数', '評価', '月間売上(手動)', 'フォルダ', 'メモ', 'URL']
    const rows = items.map(w => [
      w.item_name, w.shop_name, w.item_price, w.review_count, w.review_average,
      w.monthly_sales ?? '', w.folder ?? '', (w.memo ?? '').replace(/\n/g, ' '), w.item_url,
    ])
    const csv = [header, ...rows]
      .map(row => row.map(v => `"${String(v ?? '').replace(/"/g, '""')}"`).join(','))
      .join('\r\n')
    const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `research_watchlist_${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div>
      <div style={{ ...card, marginBottom: 16, display: 'flex', gap: 8, alignItems: 'center' }}>
        <select value={sort} onChange={e => setSort(e.target.value)} style={selectStyle}>
          <option value="picked_at">追加日順</option>
          <option value="review_count">レビュー数順</option>
          <option value="price">価格順</option>
          <option value="monthly_sales">月間売上順</option>
        </select>
        <div style={{ flex: 1 }} />
        <button onClick={handleExportCsv} style={btnSecondary}>CSV出力</button>
      </div>

      {loading ? (
        <div style={emptyBox}>読み込み中...</div>
      ) : items.length === 0 ? (
        <div style={emptyBox}>ピックアップした商品がまだありません</div>
      ) : (
        <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 8 }}>{items.length}件</div>
      )}

      <div style={grid}>
        {items.map(w => (
          <WatchlistCard key={w.id} item={w} onUpdate={handleUpdate} onDelete={() => handleDelete(w.id)} />
        ))}
      </div>
    </div>
  )
}

// ============================================================
// 共通カード部品
// ============================================================

function ProductCard({ item, actionLabel, actionDisabled, onAction }) {
  return (
    <div style={productCard}>
      <a href={item.item_url} target="_blank" rel="noreferrer">
        {item.image_url ? (
          <img src={item.image_url} alt="" style={cardImage} />
        ) : (
          <div style={{ ...cardImage, background: '#f3f4f6' }} />
        )}
      </a>
      <div style={{ padding: 10, display: 'flex', flexDirection: 'column', gap: 4, flex: 1 }}>
        <div style={shopBadge}>{item.shop_name}</div>
        <a href={item.item_url} target="_blank" rel="noreferrer" style={cardTitle} title={item.item_name}>
          {item.item_name}
        </a>
        <div style={{ fontWeight: 700, fontSize: 16 }}>¥{(item.item_price ?? 0).toLocaleString()}</div>
        {/* 素のテキストと条件付き要素を兄弟にすると、ブラウザ翻訳がテキストノードを
            差し替えたときにReactの再描画と食い違う。テキストは必ず要素で包む */}
        <div style={{ fontSize: 12, color: '#6b7280' }}>
          <span>★{(item.review_average ?? 0).toFixed(2)}（{(item.review_count ?? 0).toLocaleString()}件）</span>
          {/* 順位はジャンル別ランキング由来のときだけ。キーワード検索の並び順は順位ではない */}
          {item.rank ? <span style={{ marginLeft: 8 }}>ランキング{item.rank}位</span> : null}
        </div>
        <ReviewDeltaBadge delta={item.review_delta} since={item.prev_fetched_at} />
        <button onClick={onAction} disabled={actionDisabled} style={{ ...btnPrimary, marginTop: 'auto', opacity: actionDisabled ? 0.6 : 1 }}>
          {actionLabel}
        </button>
      </div>
    </div>
  )
}

// 楽天で検索すれば分かる情報（価格・レビュー数）ではなく、
// 前回バッチからの伸びを見せる。これがこのツールを使う理由になる部分。
function ReviewDeltaBadge({ delta, since }) {
  if (delta == null) {
    return (
      <div style={{ fontSize: 11, color: '#9ca3af' }}>
        レビュー増加：初回取得（次回から比較できます）
      </div>
    )
  }
  const sinceLabel = since ? `${new Date(since).getMonth() + 1}/${new Date(since).getDate()}から` : '前回から'
  if (delta <= 0) {
    return <div style={{ fontSize: 11, color: '#9ca3af' }}>{sinceLabel} 増減なし</div>
  }
  return (
    <div style={{
      fontSize: 12, fontWeight: 700, color: '#15803d',
      background: '#dcfce7', borderRadius: 4, padding: '2px 6px', alignSelf: 'flex-start',
    }}>
      {sinceLabel} レビュー +{delta.toLocaleString()}
    </div>
  )
}

function WatchlistCard({ item, onUpdate, onDelete }) {
  const [monthlySales, setMonthlySales] = useState(item.monthly_sales ?? '')
  const [folder, setFolder] = useState(item.folder ?? '')
  const [memo, setMemo] = useState(item.memo ?? '')

  return (
    <div style={productCard}>
      <a href={item.item_url} target="_blank" rel="noreferrer">
        {item.image_url ? (
          <img src={item.image_url} alt="" style={cardImage} />
        ) : (
          <div style={{ ...cardImage, background: '#f3f4f6' }} />
        )}
      </a>
      <div style={{ padding: 10, display: 'flex', flexDirection: 'column', gap: 4, flex: 1 }}>
        <div style={shopBadge}>{item.shop_name}</div>
        <a href={item.item_url} target="_blank" rel="noreferrer" style={cardTitle} title={item.item_name}>
          {item.item_name}
        </a>
        <div style={{ fontWeight: 700, fontSize: 16 }}>¥{(item.item_price ?? 0).toLocaleString()}</div>
        <div style={{ fontSize: 12, color: '#6b7280' }}>
          ★{(item.review_average ?? 0).toFixed(2)}（{(item.review_count ?? 0).toLocaleString()}件）
        </div>

        <label style={{ ...labelStyle, marginTop: 4 }}>
          月間売上（手動）
          <input
            type="number"
            value={monthlySales}
            onChange={e => setMonthlySales(e.target.value)}
            onBlur={() => onUpdate(item.id, { monthly_sales: monthlySales === '' ? null : Number(monthlySales) })}
            style={inputStyle}
          />
        </label>
        <label style={labelStyle}>
          フォルダ
          <input
            value={folder}
            onChange={e => setFolder(e.target.value)}
            onBlur={() => onUpdate(item.id, { folder: folder || null })}
            style={inputStyle}
          />
        </label>
        <label style={labelStyle}>
          メモ
          <textarea
            value={memo}
            onChange={e => setMemo(e.target.value)}
            onBlur={() => onUpdate(item.id, { memo: memo || null })}
            style={{ ...inputStyle, minHeight: 50, resize: 'vertical' }}
          />
        </label>
        <button onClick={onDelete} style={{ ...btnSecondary, color: '#dc2626', marginTop: 'auto' }}>
          リストから外す
        </button>
      </div>
    </div>
  )
}

const card = { background: '#fff', borderRadius: 8, padding: 16, border: '1px solid #e5e7eb' }
const btnPrimary = { background: '#2563eb', color: '#fff', border: 'none', borderRadius: 6, padding: '8px 16px', cursor: 'pointer', fontWeight: 600, fontSize: 13 }
const btnSecondary = { background: '#f1f5f9', color: '#334155', border: '1px solid #cbd5e1', borderRadius: 6, padding: '8px 16px', cursor: 'pointer', fontSize: 13 }
const btnSmall = { background: '#f1f5f9', border: '1px solid #cbd5e1', borderRadius: 4, padding: '2px 8px', cursor: 'pointer', fontSize: 12 }
const selectStyle = { border: '1px solid #d1d5db', borderRadius: 6, padding: '6px 10px', fontSize: 13 }
const inputStyle = { border: '1px solid #d1d5db', borderRadius: 6, padding: '6px 10px', fontSize: 13, width: '100%', boxSizing: 'border-box' }
const labelStyle = { fontSize: 12, color: '#374151', display: 'flex', flexDirection: 'column', gap: 2 }
const tableStyle = { width: '100%', borderCollapse: 'collapse', fontSize: 14 }
const thStyle = { textAlign: 'left', padding: '8px 10px', borderBottom: '2px solid #e5e7eb', color: '#6b7280', fontWeight: 600, fontSize: 12 }
const tdStyle = { padding: '6px 10px', borderBottom: '1px solid #f3f4f6' }
const overlay = { position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.4)', zIndex: 100, display: 'flex', alignItems: 'center', justifyContent: 'center' }
const modal = { background: '#fff', borderRadius: 12, padding: 24, maxWidth: 800, width: '90%', maxHeight: '80vh', overflow: 'auto' }
const emptyBox = { padding: 40, textAlign: 'center', color: '#9ca3af', borderRadius: 8 }
const codeStyle = { background: '#f1f5f9', padding: '1px 5px', borderRadius: 3, fontFamily: 'monospace', margin: '0 2px' }
const grid = { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 12 }
const productCard = { display: 'flex', flexDirection: 'column', border: '1px solid #e5e7eb', borderRadius: 8, overflow: 'hidden', background: '#fff' }
const cardImage = { width: '100%', height: 160, objectFit: 'contain', background: '#fafafa', display: 'block' }
const shopBadge = { fontSize: 11, color: '#2563eb', fontWeight: 600 }
const cardTitle = { fontSize: 13, color: '#111827', textDecoration: 'none', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden', lineHeight: 1.4, minHeight: '2.8em' }
