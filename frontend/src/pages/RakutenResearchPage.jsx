import { useState, useEffect, useCallback } from 'react'
import api from '../api/client'
import ProductDraftsTab from '../components/ProductDraftsTab'

const TYPE_LABEL = { shop: 'セラー', keyword: 'キーワード', genre: 'ジャンル' }

// url_key（"luckyhill/nz-48ss"）からNintの商品詳細URLを組み立てる。
// 商品詳細は追跡リストの契約件数に関係なく開けるので、リサーチはこの経路を使う。
function nintUrl(urlKey) {
  if (!urlKey || !urlKey.includes('/')) return null
  const [shop, code] = urlKey.split('/')
  const unique = encodeURIComponent(`1#:@${shop}#:@${code}`)
  return `https://ec.nint.jp/v/item/detail?Cpage=rakuten&catalogId=0&unique_item_code=${unique}`
}
const TYPE_INPUT_LABEL = {
  shop: 'ショップコード（店舗URLの識別子）',
  keyword: '検索キーワード',
  genre: 'ジャンルID',
}

export default function RakutenResearchPage() {
  const [tab, setTab] = useState('candidates') // 'candidates' | 'watchlist' | 'drafts'

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
          <button onClick={() => setTab('drafts')} style={tab === 'drafts' ? btnPrimary : btnSecondary}>
            採用（商品化）
          </button>
        </div>
      </div>

      {tab === 'candidates' && <CandidatesTab />}
      {tab === 'watchlist' && <WatchlistTab />}
      {tab === 'drafts' && <ProductDraftsTab />}
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
  const [sort, setSort] = useState('review_delta_rate')
  const [candidates, setCandidates] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showTargetManage, setShowTargetManage] = useState(false)
  const [pickingCode, setPickingCode] = useState('')
  const [savingShop, setSavingShop] = useState('')
  const [justSavedShop, setJustSavedShop] = useState('')
  const [truncated, setTruncated] = useState(false)
  const [showGenrePicker, setShowGenrePicker] = useState(false)
  const [pendingGenre, setPendingGenre] = useState('')

  // 登録済みのセラーはボタンを「登録済み」にするので、shopCodeを引けるようにしておく
  const savedShopCodes = new Set(targets.filter(t => t.type === 'shop').map(t => t.value))

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
      setTruncated(!!res.data.truncated)
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

  // ジャンルを選んだら、そのジャンルの商品がすぐ並ぶようにする。
  // 未取得のジャンルはサーバーから楽天を呼べない（IP制限）ので、対象に追加して
  // 次回バッチに拾わせる。何も起きないように見えないよう、その旨を伝える
  const handleSelectGenre = async (g) => {
    setShowGenrePicker(false)
    const existing = targets.find(t => t.type === 'genre' && String(t.value) === String(g.genre_id))
    if (existing) {
      setTargetId(String(existing.id))
      setPendingGenre('')
      return
    }
    try {
      const res = await api.post('/research/targets', {
        type: 'genre',
        value: String(g.genre_id),
        label: g.name,
      })
      await fetchTargets()
      setTargetId(String(res.data.id))
      setPendingGenre(g.name)
    } catch (e) {
      alert('ジャンルの登録に失敗しました')
    }
  }

  const handleSaveSeller = async (c) => {
    if (!c.shop_code) return
    setSavingShop(c.shop_code)
    try {
      await api.post('/research/targets', {
        type: 'shop',
        value: c.shop_code,
        label: c.shop_name || c.shop_code,
      })
      await fetchTargets()
      setJustSavedShop(c.shop_name || c.shop_code)
    } catch (e) {
      alert('セラーの登録に失敗しました')
    }
    setSavingShop('')
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
          <option value="review_delta_rate">伸び率順（レビュー増加率）</option>
          <option value="review_delta">レビュー増加数順</option>
          <option value="review_count">レビュー数順</option>
          <option value="price">価格順</option>
          <option value="review_average">評価順</option>
          <option value="nint_units">月間販売個数順（Nint）</option>
          <option value="nint_growth">販売個数の伸び率順（Nint）</option>
          <option value="rank">ジャンル別ランキング順</option>
        </select>
        <div style={{ flex: 1 }} />
        {/* ジャンルを選んだらそのジャンルの商品がすぐ並ぶようにする。
            対象管理を開かずに、ここから直接ジャンルを切り替えられる */}
        <button onClick={() => setShowGenrePicker(true)} style={btnPrimary}>ジャンルで見る</button>
        <NintImportButton onImported={fetchCandidates} />
        <button onClick={() => setShowTargetManage(true)} style={btnSecondary}>対象管理</button>
      </div>

      {pendingGenre && (
        <div style={{
          ...card, marginBottom: 16, background: '#eff6ff', border: '1px solid #93c5fd',
          display: 'flex', alignItems: 'center', gap: 12,
        }}>
          <span style={{ fontSize: 13, flex: 1 }}>
            ジャンル「{pendingGenre}」を対象に追加しました。まだ取得していないジャンルなので、
            次回のバッチ実行後に商品が並びます。
          </span>
          <button onClick={() => setPendingGenre('')} style={btnSmall}>閉じる</button>
        </div>
      )}

      {/* 登録しても商品が並ぶのは次のバッチ実行後。何も起きないように見えるので明示する */}
      {justSavedShop && (
        <div style={{
          ...card, marginBottom: 16, background: '#f0fdf4', border: '1px solid #86efac',
          display: 'flex', alignItems: 'center', gap: 12,
        }}>
          <span style={{ fontSize: 13, flex: 1 }}>
            セラー「{justSavedShop}」を登録しました。このセラーの商品は、次回のバッチ実行後に一覧へ表示されます。
          </span>
          <button onClick={() => setJustSavedShop('')} style={btnSmall}>閉じる</button>
        </div>
      )}

      {loading ? (
        <div style={emptyBox}>読み込み中...</div>
      ) : error ? (
        <div style={{ ...emptyBox, background: '#fef2f2', border: '1px solid #fca5a5', color: '#991b1b' }}>{error}</div>
      ) : candidates.length === 0 ? (
        <div style={emptyBox}>
          候補がありません。対象を登録してローカルバッチを実行してください。
        </div>
      ) : (
        <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 8 }}>
          <span>{candidates.length}件</span>
          {truncated && (
            <span style={{ marginLeft: 8, color: '#b45309' }}>
              表示上限に達しています。絞り込みを使うと目的の商品を探しやすくなります
            </span>
          )}
        </div>
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
            sellerSaved={savedShopCodes.has(c.shop_code)}
            sellerSaving={savingShop === c.shop_code}
            onSaveSeller={() => handleSaveSeller(c)}
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

      {showGenrePicker && (
        <GenrePicker onSelect={handleSelectGenre} onClose={() => setShowGenrePicker(false)} />
      )}
    </div>
  )
}

function TargetManageModal({ targets, onClose, onChanged }) {
  const [type, setType] = useState('shop')
  const [value, setValue] = useState('')
  const [label, setLabel] = useState('')
  const [showGenrePicker, setShowGenrePicker] = useState(false)
  const [genreLabel, setGenreLabel] = useState('')

  const handleAdd = async () => {
    if (!value.trim()) return
    await api.post('/research/targets', { type, value: value.trim(), label: label.trim() || null })
    setValue(''); setLabel(''); setGenreLabel('')
    onChanged()
  }

  const handlePickGenre = (g) => {
    setValue(String(g.genre_id))
    setGenreLabel(g.path || g.name)
    // 表示名が空なら、選んだジャンル名をそのまま使う（IDだけ並ぶと分からないため）
    if (!label.trim()) setLabel(g.name)
    setShowGenrePicker(false)
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
          {type === 'genre' ? (
            <label style={labelStyle}>
              ジャンル
              <button onClick={() => setShowGenrePicker(true)} style={{ ...btnSecondary, textAlign: 'left', minWidth: 260 }}>
                {genreLabel || 'ジャンルを選ぶ…'}
              </button>
            </label>
          ) : (
            <label style={labelStyle}>
              {TYPE_INPUT_LABEL[type]}
              <input value={value} onChange={e => setValue(e.target.value)} style={inputStyle} />
            </label>
          )}
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
              <b>ジャンル</b>：「ジャンルを選ぶ」から名前で検索するか、階層を辿って選べます
              （ジャンルIDを自分で調べる必要はありません）。<br />
              ランキング上位30件に加えて、そのジャンルの商品を
              レビューの多い順に約300件まとめて取得します（1ページ目だけではありません）。<br />
              ランキングに入っている商品には「ランキング〇位」が付きます。
              件数が多いので、レビュー数や価格の絞り込みと併せて使ってください。
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

      {showGenrePicker && (
        <GenrePicker onSelect={handlePickGenre} onClose={() => setShowGenrePicker(false)} />
      )}
    </div>
  )
}

// ジャンルIDを手で調べるのは現実的でないので、名前で探すか階層を辿って選ばせる
function GenrePicker({ onSelect, onClose }) {
  const [genres, setGenres] = useState([])
  const [keyword, setKeyword] = useState('')
  const [trail, setTrail] = useState([])   // 辿ってきた親ジャンル
  const [loading, setLoading] = useState(true)
  const [total, setTotal] = useState(0)

  const load = useCallback(async () => {
    setLoading(true)
    const params = {}
    if (keyword.trim()) {
      params.keyword = keyword.trim()
    } else if (trail.length) {
      params.parent_id = trail[trail.length - 1].genre_id
    }
    const res = await api.get('/research/genres', { params })
    setGenres(res.data.genres || [])
    setTotal(res.data.total || 0)
    setLoading(false)
  }, [keyword, trail])

  useEffect(() => { load() }, [load])

  const searching = !!keyword.trim()

  return (
    <div style={{ ...overlay, zIndex: 200 }} onClick={onClose}>
      <div style={modal} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <h3 style={{ margin: 0 }}>ジャンルを選ぶ</h3>
          <button onClick={onClose} style={btnSecondary}>閉じる</button>
        </div>

        {total === 0 ? (
          <div style={{ ...card, background: '#fffbeb', border: '1px solid #fcd34d', fontSize: 13, lineHeight: 1.7 }}>
            ジャンル一覧がまだ取り込まれていません。<br />
            ローカルPCで <code style={codeStyle}>python scripts/sync_rakuten_genres.py</code> を
            一度実行すると、ここから選べるようになります。
          </div>
        ) : (
          <>
            <input
              placeholder="ジャンル名で検索（例: ベビー、ペット、キッチン）"
              value={keyword}
              onChange={e => setKeyword(e.target.value)}
              style={{ ...inputStyle, marginBottom: 10 }}
            />

            {/* 検索中は階層を辿る意味がないのでパンくずは出さない */}
            {!searching && (
              <div style={{ fontSize: 12, marginBottom: 8, display: 'flex', gap: 4, flexWrap: 'wrap', alignItems: 'center' }}>
                <button onClick={() => setTrail([])} style={btnSmall}>すべて</button>
                {trail.map((g, i) => (
                  <span key={g.genre_id} style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                    <span style={{ color: '#9ca3af' }}>›</span>
                    <button onClick={() => setTrail(trail.slice(0, i + 1))} style={btnSmall}>{g.name}</button>
                  </span>
                ))}
              </div>
            )}

            {loading ? (
              <div style={{ padding: 20, textAlign: 'center', color: '#9ca3af' }}>読み込み中...</div>
            ) : genres.length === 0 ? (
              <div style={{ padding: 20, textAlign: 'center', color: '#9ca3af' }}>
                {searching ? '該当するジャンルがありません' : 'これ以上の下位ジャンルはありません'}
              </div>
            ) : (
              <div style={{ maxHeight: 380, overflowY: 'auto', border: '1px solid #e5e7eb', borderRadius: 6 }}>
                {genres.map(g => (
                  <div key={g.genre_id} style={{
                    display: 'flex', alignItems: 'center', gap: 8,
                    padding: '6px 10px', borderBottom: '1px solid #f3f4f6',
                  }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 13 }}>{g.name}</div>
                      {/* どの階層のジャンルか分からないと選べないので道筋を出す */}
                      {searching && g.path && (
                        <div style={{ fontSize: 11, color: '#9ca3af' }}>{g.path}</div>
                      )}
                    </div>
                    <span style={{ fontSize: 11, color: '#9ca3af' }}>ID {g.genre_id}</span>
                    {!searching && (
                      <button onClick={() => setTrail([...trail, g])} style={btnSmall}>下位へ</button>
                    )}
                    <button onClick={() => onSelect(g)} style={btnPrimary}>選択</button>
                  </div>
                ))}
              </div>
            )}
          </>
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

function ProductCard({ item, actionLabel, actionDisabled, onAction, sellerSaved, sellerSaving, onSaveSeller }) {
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
        {/* 気になる商品を見つけたら、その場でセラーごと追いかけられるようにする */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ ...shopBadge, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {item.shop_name}
          </span>
          {item.shop_code && (
            <button
              onClick={onSaveSeller}
              disabled={sellerSaved || sellerSaving}
              title={sellerSaved ? 'このセラーは登録済みです' : 'このセラーを登録して商品を追跡する'}
              style={sellerSaved ? sellerBtnSaved : sellerBtn}
            >
              {sellerSaved ? '✓ セラー' : sellerSaving ? '登録中' : '+ セラー'}
            </button>
          )}
        </div>
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
        <ReviewDeltaBadge delta={item.review_delta} rate={item.review_delta_rate} since={item.prev_fetched_at} />
        <NintBadge nint={item.nint} />
        <NintOpenButton urlKey={item.url_key} hasData={!!item.nint} />
        <button onClick={onAction} disabled={actionDisabled} style={{ ...btnPrimary, marginTop: 'auto', opacity: actionDisabled ? 0.6 : 1 }}>
          {actionLabel}
        </button>
      </div>
    </div>
  )
}

// 楽天で検索すれば分かる情報（価格・レビュー数）ではなく、
// 前回バッチからの伸びを見せる。これがこのツールを使う理由になる部分。
// 増加数だけだと大手の定番商品が上位を占めるので、伸び率も併記する。
function ReviewDeltaBadge({ delta, rate, since }) {
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
      {sinceLabel} +{delta.toLocaleString()}件
      {rate != null && <span> （+{rate}%）</span>}
    </div>
  )
}

// NintのCSV書き出しを取り込む。楽天APIは販売数を返さないので売上はここから入れる。
// Nintは規約でスクレイピングを禁じているため、画面のDL機能で出したCSVを読み込む形にしている。
function NintImportButton({ onImported }) {
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)

  const handleFile = async (e) => {
    const file = e.target.files?.[0]
    e.target.value = ''   // 同じファイルを続けて選べるようにする
    if (!file) return
    setBusy(true)
    setResult(null)
    try {
      const form = new FormData()
      form.append('file', file)
      const res = await api.post('/research/nint/import', form)
      setResult(res.data)
      onImported?.()
    } catch (err) {
      setResult({ error: err.response?.data?.detail || '取り込みに失敗しました' })
    }
    setBusy(false)
  }

  return (
    <>
      <label style={{ ...btnSecondary, display: 'inline-block' }}>
        {busy ? '取り込み中...' : 'Nint CSV取り込み'}
        <input type="file" accept=".csv" onChange={handleFile} style={{ display: 'none' }} disabled={busy} />
      </label>
      {result && (
        <span style={{ fontSize: 12, color: result.error ? '#dc2626' : '#15803d' }}>
          {result.error
            ? result.error
            : `${result.imported_items}商品 × ${result.months?.length ?? 0}ヶ月分を取り込みました`}
        </span>
      )}
    </>
  )
}

// 楽天APIは販売数を返さないので、ここはNintから取り込んだ実績。
// レビューの伸びと違って過去14ヶ月分が一度に入るため、取り込んだ時点で伸びが分かる。
// 売上がまだ無い商品は、その場でNintを開けるようにする。
// 開けば拡張機能が自動で取り込むので、数字を手で写す必要がない。
function NintOpenButton({ urlKey, hasData }) {
  const url = nintUrl(urlKey)
  if (!url) return null
  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer"
      title={hasData ? 'Nintで最新の売上を見る' : 'Nintで売上を見る（開くと自動で取り込まれます）'}
      style={{
        fontSize: 11, fontWeight: 600, textAlign: 'center', textDecoration: 'none',
        borderRadius: 4, padding: '3px 6px',
        background: hasData ? '#f1f5f9' : '#004aad',
        color: hasData ? '#475569' : '#fff',
        border: hasData ? '1px solid #cbd5e1' : 'none',
      }}
    >
      {hasData ? 'Nintで再確認' : 'Nintで売上を見る'}
    </a>
  )
}

function NintBadge({ nint }) {
  if (!nint) return null
  const ym = nint.latest_month
  const label = ym ? `${ym.slice(0, 4)}/${ym.slice(4)}` : ''
  const up = nint.growth_rate != null && nint.growth_rate > 0
  return (
    <div style={{
      fontSize: 12, background: '#fff7ed', border: '1px solid #fed7aa',
      borderRadius: 4, padding: '3px 6px',
    }}>
      <div style={{ fontWeight: 700, color: '#9a3412' }}>
        {label} {nint.units != null ? `${nint.units.toLocaleString()}個` : '—'}
        {nint.sales_amount != null && (
          <span style={{ fontWeight: 400 }}> / {Math.round(nint.sales_amount).toLocaleString()}円</span>
        )}
      </div>
      {nint.growth_rate != null && (
        <div style={{ fontSize: 11, color: up ? '#15803d' : '#9ca3af' }}>
          {nint.base_month ? `${nint.base_month.slice(4)}月比` : '前月比'} {up ? '+' : ''}{nint.growth_rate}%
        </div>
      )}
    </div>
  )
}

function WatchlistCard({ item, onUpdate, onDelete }) {
  const [adopting, setAdopting] = useState(false)
  const onAdopt = async () => {
    setAdopting(true)
    try {
      const res = await api.post('/product-drafts/adopt', { watchlist_id: item.id })
      alert(res.data.already_exists
        ? 'この商品はすでに「採用（商品化）」タブにあります。'
        : '「採用（商品化）」タブに追加しました。')
    } catch (e) {
      alert('採用に失敗しました: ' + (e.response?.data?.detail || e.message))
    } finally {
      setAdopting(false)
    }
  }

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
        <NintBadge nint={item.nint} />
        <NintOpenButton urlKey={item.url_key} hasData={!!item.nint} />

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
        <div style={{ display: 'flex', gap: 6, marginTop: 'auto' }}>
          <button onClick={onAdopt} disabled={adopting} style={{ ...btnPrimary, flex: 1, opacity: adopting ? 0.6 : 1 }}>
            {adopting ? '採用中...' : '採用（商品化へ）'}
          </button>
          <button onClick={onDelete} style={{ ...btnSecondary, color: '#dc2626' }}>
            外す
          </button>
        </div>
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
const sellerBtn = {
  background: '#fff', color: '#2563eb', border: '1px solid #93c5fd', borderRadius: 4,
  padding: '1px 6px', cursor: 'pointer', fontSize: 11, fontWeight: 600, whiteSpace: 'nowrap',
}
const sellerBtnSaved = {
  ...sellerBtn, background: '#eff6ff', color: '#60a5fa', borderColor: '#dbeafe', cursor: 'default',
}
const grid = { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 12 }
const productCard = { display: 'flex', flexDirection: 'column', border: '1px solid #e5e7eb', borderRadius: 8, overflow: 'hidden', background: '#fff' }
const cardImage = { width: '100%', height: 160, objectFit: 'contain', background: '#fafafa', display: 'block' }
const shopBadge = { fontSize: 11, color: '#2563eb', fontWeight: 600 }
const cardTitle = { fontSize: 13, color: '#111827', textDecoration: 'none', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden', lineHeight: 1.4, minHeight: '2.8em' }
