import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '../api/client'

const REASON_LABEL = { up: '値上げ', down: '値下げ', revert: '巻き戻し' }
const REASON_COLOR = { up: '#16a34a', down: '#dc2626', revert: '#ca8a04' }

export default function PriceAdjustPage() {
  const qc = useQueryClient()
  const [tab, setTab] = useState('pending')
  const [suggesting, setSuggesting] = useState(false)

  const { data: list = [], isLoading } = useQuery({
    queryKey: ['priceAdjustments', tab],
    queryFn: () => api.get(`/price-adjustments/?status=${tab}`).then(r => r.data),
  })

  const approve = useMutation({
    mutationFn: ({ id, sku, newPrice }) => {
      // セラーセントラルの在庫管理ページをSKU検索＋価格パラメータ付きで開く
      const url = `https://sellercentral.amazon.co.jp/myinventory/inventory?searchField=sku&search=${encodeURIComponent(sku)}&cit_sku=${encodeURIComponent(sku)}&cit_price=${newPrice}`
      window.open(url, '_blank')
      return api.post(`/price-adjustments/${id}/approve`)
    },
    onSuccess: () => qc.invalidateQueries(['priceAdjustments']),
    onError: (e) => {
      // セラーセントラルは開いているのでDBだけ更新失敗の場合も通知
      qc.invalidateQueries(['priceAdjustments'])
      console.warn('DB更新失敗:', e.message)
    },
  })

  const reject = useMutation({
    mutationFn: (id) => api.post(`/price-adjustments/${id}/reject`),
    onSuccess: () => qc.invalidateQueries(['priceAdjustments']),
  })

  const handleSuggest = async () => {
    if (!confirm('SP-APIから売上データを取得して価格調整提案を生成します。\n数分かかる場合があります。よろしいですか？')) return
    setSuggesting(true)
    try {
      const res = await api.post('/price-adjustments/suggest')
      alert(`${res.data.suggested}件の提案を生成しました。`)
      qc.invalidateQueries(['priceAdjustments'])
    } catch (e) {
      alert('提案生成失敗: ' + (e.response?.data?.detail || e.message))
    } finally {
      setSuggesting(false)
    }
  }

  return (
    <div>
      <h1>💹 価格調整</h1>

      <div style={{ display: 'flex', gap: 8, marginBottom: 16, alignItems: 'center' }}>
        <button
          className={`btn ${tab === 'pending' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setTab('pending')}
        >承認待ち</button>
        <button
          className={`btn ${tab === 'applied' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setTab('applied')}
        >適用済み</button>
        <button
          className={`btn ${tab === 'rejected' ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setTab('rejected')}
        >却下済み</button>
        <div style={{ marginLeft: 'auto' }}>
          <button className="btn btn-secondary" onClick={handleSuggest} disabled={suggesting}>
            {suggesting ? '生成中...' : '🔄 提案を再生成'}
          </button>
        </div>
      </div>

      {tab === 'pending' && (
        <div className="card" style={{ marginBottom: 12, background: '#fffbeb', border: '1px solid #fcd34d', fontSize: 13, color: '#92400e', padding: '10px 16px' }}>
          ⚠️ 設定画面で「価格自動調整」をONにすると毎週月曜9時に自動生成されます。承認した提案のみAmazonに反映されます。
        </div>
      )}

      {isLoading ? (
        <div className="card" style={{ textAlign: 'center', padding: 40, color: '#888' }}>読み込み中...</div>
      ) : list.length === 0 ? (
        <div className="card empty-state">
          <div style={{ fontSize: 36 }}>💹</div>
          <p>{tab === 'pending' ? '承認待ちの提案はありません。' : '履歴がありません。'}</p>
        </div>
      ) : (
        <div className="card">
          <div style={{ overflowX: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th>SKU / 商品名</th>
                  <th style={{ textAlign: 'center' }}>種別</th>
                  <th style={{ textAlign: 'right' }}>現在価格</th>
                  <th style={{ textAlign: 'right' }}>提案価格</th>
                  <th style={{ textAlign: 'right' }}>変更額</th>
                  <th style={{ textAlign: 'right' }}>前期日販</th>
                  <th style={{ textAlign: 'right' }}>今期日販</th>
                  <th style={{ textAlign: 'right' }}>変更後利益率</th>
                  {tab === 'pending' && <th style={{ textAlign: 'center' }}>操作</th>}
                  {tab !== 'pending' && <th>日時</th>}
                </tr>
              </thead>
              <tbody>
                {list.map(row => (
                  <tr key={row.id}>
                    <td>
                      <div style={{ fontFamily: 'monospace', fontSize: 11, color: '#888' }}>{row.sku}</div>
                      <div style={{ fontSize: 13, maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{row.name}</div>
                    </td>
                    <td style={{ textAlign: 'center' }}>
                      <span style={{
                        background: REASON_COLOR[row.reason] + '20',
                        color: REASON_COLOR[row.reason],
                        fontWeight: 700, fontSize: 12,
                        padding: '2px 8px', borderRadius: 4,
                      }}>
                        {REASON_LABEL[row.reason]}
                      </span>
                    </td>
                    <td style={{ textAlign: 'right' }}>¥{row.old_price?.toLocaleString()}</td>
                    <td style={{ textAlign: 'right', fontWeight: 700 }}>¥{row.new_price?.toLocaleString()}</td>
                    <td style={{ textAlign: 'right', color: row.change_amt >= 0 ? '#16a34a' : '#dc2626', fontWeight: 600 }}>
                      {row.change_amt >= 0 ? '+' : ''}{row.change_amt?.toLocaleString()}円
                    </td>
                    <td style={{ textAlign: 'right', fontSize: 12, color: '#666' }}>
                      {row.daily_before != null ? row.daily_before.toFixed(2) : '-'}
                    </td>
                    <td style={{ textAlign: 'right', fontSize: 12, color: '#666' }}>
                      {row.daily_after != null ? row.daily_after.toFixed(2) : '-'}
                    </td>
                    <td style={{ textAlign: 'right', fontWeight: 600,
                      color: row.profit_rate_after == null ? '#bbb'
                        : row.profit_rate_after >= 20 ? '#16a34a'
                        : row.profit_rate_after >= 10 ? '#ca8a04' : '#dc2626'
                    }}>
                      {row.profit_rate_after != null ? `${row.profit_rate_after}%` : '-'}
                    </td>
                    {tab === 'pending' && (
                      <td style={{ textAlign: 'center', whiteSpace: 'nowrap' }}>
                        <button
                          className="btn btn-primary btn-sm"
                          style={{ marginRight: 6 }}
                          disabled={approve.isPending}
                          onClick={() => {
                            if (confirm(`${row.sku} の価格を ¥${row.old_price?.toLocaleString()} → ¥${row.new_price?.toLocaleString()} に変更しますか？\nセラーセントラルが開きます。拡張機能が価格を自動入力します。`))
                              approve.mutate({ id: row.id, sku: row.sku, newPrice: row.new_price })
                          }}
                        >承認</button>
                        <button
                          className="btn btn-sm"
                          style={{ background: '#fee2e2', color: '#991b1b' }}
                          disabled={reject.isPending}
                          onClick={() => reject.mutate(row.id)}
                        >却下</button>
                      </td>
                    )}
                    {tab !== 'pending' && (
                      <td style={{ fontSize: 11, color: '#888', whiteSpace: 'nowrap' }}>
                        {tab === 'applied' && row.applied_at
                          ? new Date(row.applied_at).toLocaleDateString('ja-JP')
                          : new Date(row.suggested_at).toLocaleDateString('ja-JP')}
                      </td>
                    )}
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
