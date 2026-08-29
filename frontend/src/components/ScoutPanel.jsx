import { useMemo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'

const yen = (v) => v == null ? '-' : `¥${Math.round(v).toLocaleString()}`
const fmt = (v) => {
  if (!v) return '-'
  try {
    const d = new Date(v)
    return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  } catch { return v }
}

/**
 * セラースカウト。
 *
 * 巡回そのもの（ブラウザ自動操縦）は手元のPCで走らせる。Amazonはデータセンターの
 * ipからだと即ブロックするため、サーバー上では動かない。
 * ここは巡回の結果を見て、気になる商品をリサーチシートへ送る画面。
 *
 * 複数人で分担できる。割り当ては決めず、同じASINは新しい巡回で上書きする。
 */
export default function ScoutPanel() {
  const qc = useQueryClient()
  const [tab, setTab] = useState('products')
  const [q, setQ] = useState('')
  const [folder, setFolder] = useState('')
  const [minSales, setMinSales] = useState('')
  const [maxReviews, setMaxReviews] = useState('')
  const [sort, setSort] = useState('price_desc')

  const { data: sum } = useQuery({
    queryKey: ['scout-summary'],
    queryFn: () => api.get('/scout/summary').then(r => r.data),
    refetchInterval: 60000,
  })
  const { data: sellersData } = useQuery({
    queryKey: ['scout-sellers'],
    queryFn: () => api.get('/scout/sellers').then(r => r.data),
  })
  const { data: prodData, isLoading } = useQuery({
    queryKey: ['scout-products', q, folder, minSales, maxReviews, sort],
    queryFn: () => api.get('/scout/products', {
      params: {
        ...(q ? { q } : {}), ...(folder ? { folder } : {}),
        ...(minSales ? { min_sales: Number(minSales) } : {}),
        ...(maxReviews ? { max_reviews: Number(maxReviews) } : {}),
        sort,
      },
    }).then(r => r.data),
  })
  const { data: basket } = useQuery({
    queryKey: ['scout-basket'],
    queryFn: () => api.get('/scout/basket').then(r => r.data),
    refetchInterval: 30000,
  })

  const sellers = sellersData?.sellers || []
  const folders = sellersData?.folders || []
  const products = prodData?.products || []

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['scout-products'] })
    qc.invalidateQueries({ queryKey: ['scout-basket'] })
    qc.invalidateQueries({ queryKey: ['scout-summary'] })
  }

  const addBasket = useMutation({
    mutationFn: (asin) => api.post('/scout/basket/add', { asin }).then(r => r.data),
    onSuccess: refresh,
  })
  const removeBasket = useMutation({
    mutationFn: (asin) => api.post('/scout/basket/remove', { asin }).then(r => r.data),
    onSuccess: refresh,
  })

  const neverCrawled = useMemo(
    () => sellers.filter(s => !s.last_run_at).length, [sellers])

  return (
    <div>
      {/* 集計 */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 14, flexWrap: 'wrap' }}>
        {[
          { l: 'セラー', v: `${sum?.seller_count ?? '-'}社` },
          { l: '未巡回', v: `${sum?.never_crawled ?? '-'}社`,
            warn: (sum?.never_crawled || 0) > 0 },
          { l: '商品', v: `${(sum?.product_count ?? 0).toLocaleString()}件` },
          { l: 'かご', v: `${sum?.basket_count ?? 0}件` },
          { l: '最終巡回', v: fmt(sum?.last_run_at) },
        ].map(x => (
          <div key={x.l} className="card" style={{ margin: 0, minWidth: 130 }}>
            <div style={{ fontSize: 12, color: '#64748b' }}>{x.l}</div>
            <div style={{
              fontSize: 20, fontWeight: 700,
              color: x.warn ? '#d97706' : undefined,
            }}>{x.v}</div>
          </div>
        ))}
      </div>

      {/* 巡回のやり方 */}
      <details style={{ marginBottom: 14 }}>
        <summary style={{ cursor: 'pointer', fontSize: 13, color: '#334155', padding: '6px 0' }}>
          巡回（セラーの更新）のやり方
        </summary>
        <div style={{
          padding: 14, marginTop: 6, borderRadius: 8,
          background: '#f0f9ff', border: '1px solid #bae6fd', fontSize: 13,
        }}>
          <p style={{ marginTop: 0 }}>
            巡回はAmazonのストアフロントをブラウザで開いて回るため、<b>手元のPCで動かします</b>。
            サーバーからだと弾かれるためです。何人で分担しても構いません
            （同じセラーを重複して回しても、新しい情報に更新されるだけです）。
          </p>
          <div style={{ background: '#fff', padding: 10, borderRadius: 6, fontFamily: 'monospace', fontSize: 12 }}>
            cd scripts\scout<br />
            python sync_server.py --token &lt;トークン&gt; --run-by 自分の名前
          </div>
          <ul style={{ marginBottom: 0, paddingLeft: 20, color: '#0c4a6e' }}>
            <li>セラー一覧をサーバーから取り込み → 巡回 → 結果を送信、まで自動で行います</li>
            <li><code>--limit 30</code> で先頭30社だけ、<code>--sellers A1XXX,A2YYY</code> で指定も可</li>
            <li>実測で283社・約40分。Amazonにログインしたままだと自前で中止します</li>
          </ul>
        </div>
      </details>

      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        {[
          { k: 'products', l: `商品（${prodData?.total ?? 0}）` },
          { k: 'basket', l: `かご（${basket?.count ?? 0}）` },
          { k: 'sellers', l: `セラー（${sellers.length}）` },
        ].map(t => (
          <button key={t.k} onClick={() => setTab(t.k)}
            className={`btn ${tab === t.k ? 'btn-primary' : 'btn-secondary'}`}>
            {t.l}
          </button>
        ))}
      </div>

      {tab === 'products' && (
        <div className="card">
          <div style={{ display: 'flex', gap: 10, marginBottom: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
            <div className="form-group" style={{ margin: 0, minWidth: 200 }}>
              <label>商品名・ASINで検索</label>
              <input value={q} onChange={e => setQ(e.target.value)} />
            </div>
            <div className="form-group" style={{ margin: 0 }}>
              <label>フォルダ</label>
              <select value={folder} onChange={e => setFolder(e.target.value)} style={{ width: 'auto' }}>
                <option value="">すべて</option>
                {folders.map(f => <option key={f} value={f}>{f}</option>)}
              </select>
            </div>
            <div className="form-group" style={{ margin: 0 }}>
              <label>月間販売数 以上</label>
              <input type="number" value={minSales} placeholder="50" style={{ width: 90 }}
                onChange={e => setMinSales(e.target.value)} />
            </div>
            <div className="form-group" style={{ margin: 0 }}>
              <label>レビュー数 以下</label>
              <input type="number" value={maxReviews} placeholder="30" style={{ width: 90 }}
                onChange={e => setMaxReviews(e.target.value)} />
            </div>
            <div className="form-group" style={{ margin: 0 }}>
              <label>並び</label>
              <select value={sort} onChange={e => setSort(e.target.value)} style={{ width: 'auto' }}>
                <option value="price_desc">価格が高い順</option>
                <option value="price_asc">価格が安い順</option>
                <option value="sales_desc">販売数が多い順</option>
                <option value="reviews_asc">レビューが少ない順</option>
                <option value="rank_asc">ベストセラー順</option>
              </select>
            </div>
          </div>

          {isLoading ? (
            <div style={{ padding: 40, textAlign: 'center', color: '#9ca3af' }}>読み込み中...</div>
          ) : products.length === 0 ? (
            <div style={{ padding: 40, textAlign: 'center', color: '#9ca3af' }}>
              {neverCrawled === sellers.length && sellers.length > 0
                ? 'まだ巡回していません。上の「巡回のやり方」を開いてください'
                : '該当する商品がありません'}
            </div>
          ) : (
            <>
              <div style={{ fontSize: 12, color: '#64748b', marginBottom: 10 }}>
                {prodData.total.toLocaleString()}件中 {prodData.shown}件を表示
              </div>
              <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fill, minmax(190px, 1fr))',
                gap: 12,
              }}>
                {products.map(p => (
                  <div key={`${p.seller_id}-${p.asin}`} style={{
                    border: '1px solid #e5e7eb', borderRadius: 8, padding: 10,
                    background: p.in_basket ? '#f0fdf4' : '#fff',
                    display: 'flex', flexDirection: 'column',
                  }}>
                    <div style={{ height: 120, display: 'flex', alignItems: 'center',
                      justifyContent: 'center', marginBottom: 8 }}>
                      {p.image
                        ? <img src={p.image} alt="" style={{ maxWidth: '100%', maxHeight: 120, objectFit: 'contain' }} />
                        : <span style={{ color: '#cbd5e1' }}>画像なし</span>}
                    </div>
                    <div style={{ fontSize: 12, lineHeight: 1.4, height: 50, overflow: 'hidden', marginBottom: 6 }}>
                      {p.title || p.asin}
                    </div>
                    <div style={{ fontSize: 11, color: '#94a3b8', marginBottom: 4 }}>
                      {p.seller_name || p.seller_id}
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between',
                      alignItems: 'center', marginBottom: 6 }}>
                      <span style={{ fontWeight: 700 }}>{yen(p.price)}</span>
                      {p.sales_min > 0 && (
                        <span style={{
                          fontSize: 11, padding: '2px 6px', borderRadius: 10,
                          background: '#fef3c7', color: '#92400e', fontWeight: 600,
                        }}>{p.sales_min}+/月</span>
                      )}
                    </div>
                    <div style={{ fontSize: 11, color: '#64748b', marginBottom: 8 }}>
                      ★{p.rating ?? '-'}（{p.reviews ?? 0}）
                      {p.rank ? ` ・ ${p.rank}位` : ''}
                    </div>
                    <div style={{ marginTop: 'auto', display: 'flex', gap: 6 }}>
                      <a href={p.url || `https://www.amazon.co.jp/dp/${p.asin}`}
                        target="_blank" rel="noreferrer"
                        className="btn btn-secondary"
                        style={{ padding: '3px 8px', fontSize: 11, textDecoration: 'none' }}>
                        開く
                      </a>
                      <button
                        className={`btn ${p.in_basket ? 'btn-secondary' : 'btn-primary'}`}
                        style={{ padding: '3px 8px', fontSize: 11, flex: 1 }}
                        onClick={() => p.in_basket
                          ? removeBasket.mutate(p.asin) : addBasket.mutate(p.asin)}>
                        {p.in_basket ? '✓ かごに追加済み' : '＋ リサーチシートへ'}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {tab === 'basket' && (
        <div className="card">
          <p style={{ color: '#64748b', fontSize: 13, marginTop: 0 }}>
            ここに入れた商品は、競合リサーチシートの「🔎 セラースカウトから取り込む」で
            まとめて行になります（同じASINが既にある行は、行を増やさず空欄だけ埋めます）。
          </p>
          {(basket?.items || []).length === 0 ? (
            <div style={{ padding: 30, textAlign: 'center', color: '#9ca3af' }}>
              かごは空です
            </div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ background: '#f8fafc', borderBottom: '2px solid #e2e8f0' }}>
                  {['画像', 'ASIN', '商品名', '売価', '月販', 'レビュー', ''].map(h => (
                    <th key={h} style={{ padding: '8px 10px', textAlign: 'left' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {basket.items.map(b => (
                  <tr key={b.id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                    <td style={{ padding: '6px 10px' }}>
                      {b.image ? <img src={b.image} alt="" style={{ width: 40, height: 40, objectFit: 'contain' }} /> : '-'}
                    </td>
                    <td style={{ padding: '8px 10px', fontFamily: 'monospace' }}>{b.asin}</td>
                    <td style={{ padding: '8px 10px', maxWidth: 320 }}>{b.title || '-'}</td>
                    <td style={{ padding: '8px 10px' }}>{yen(b.price)}</td>
                    <td style={{ padding: '8px 10px' }}>{b.sales_min ?? '-'}</td>
                    <td style={{ padding: '8px 10px' }}>{b.reviews ?? '-'}</td>
                    <td style={{ padding: '8px 10px' }}>
                      <button className="btn btn-secondary"
                        style={{ padding: '2px 8px', fontSize: 11, color: '#dc2626' }}
                        onClick={() => removeBasket.mutate(b.asin)}>外す</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {tab === 'sellers' && (
        <div className="card">
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ background: '#f8fafc', borderBottom: '2px solid #e2e8f0' }}>
                  {['セラー', 'フォルダ', '商品数', '最終巡回', '巡回した人', '状態'].map(h => (
                    <th key={h} style={{ padding: '8px 10px', textAlign: 'left', whiteSpace: 'nowrap' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sellers.map(s => (
                  <tr key={s.seller_id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                    <td style={{ padding: '8px 10px' }}>
                      <div style={{ fontWeight: 600 }}>{s.name || s.seller_id}</div>
                      <div style={{ fontSize: 11, color: '#94a3b8' }}>{s.seller_id}</div>
                    </td>
                    <td style={{ padding: '8px 10px' }}>{s.folder || '-'}</td>
                    <td style={{ padding: '8px 10px', textAlign: 'right' }}>{s.product_count}</td>
                    <td style={{ padding: '8px 10px', whiteSpace: 'nowrap' }}>{fmt(s.last_run_at)}</td>
                    <td style={{ padding: '8px 10px' }}>{s.last_run_by || '-'}</td>
                    <td style={{ padding: '8px 10px' }}>
                      {!s.last_run_at
                        ? <span style={{ color: '#94a3b8' }}>未巡回</span>
                        : s.last_status === 'ok'
                          ? <span style={{ color: '#16a34a' }}>OK</span>
                          : <span style={{ color: '#dc2626' }}>{s.last_status}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
