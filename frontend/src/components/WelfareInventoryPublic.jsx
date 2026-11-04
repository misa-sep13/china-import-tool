import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api, { mediaUrl } from '../api/client'

// 「11/4入荷」の形。年は同じ年のことしか出ないので省く
const arrivalLabel = (d) => {
  const [, m, day] = (d || '').split('-')
  return m ? `${Number(m)}/${Number(day)}入荷` : '入荷'
}
import { useWelfareVersion } from '../api/welfareVersion'

/**
 * 就労支援さん向けの在庫一覧（閲覧のみ）。
 *
 * 管理画面(WelfareInventoryPage)と違い、入力欄も更新ボタンも置かない。
 * 「いま手元に何が何個あるか」を見るためだけのもの。
 */
export default function WelfareInventoryPublic() {
  const [search, setSearch] = useState('')

  // 変わったかどうかだけを毎分見て、変わったときに取り直す
  const version = useWelfareVersion('inventory')

  const { data: rows = [], isLoading } = useQuery({
    queryKey: ['welfare-inventory-public', version],
    queryFn: () => api.get('/welfare/inventory').then(r => r.data),
    staleTime: Infinity,
  })

  const visible = useMemo(() => {
    // 残がないものは作業に使えないので出さない
    let list = rows.filter(r => (r.remaining_qty || 0) > 0)
    const q = search.trim().toLowerCase()
    if (q) {
      list = list.filter(r =>
        (r.sku || '').toLowerCase().includes(q)
        || (r.name_jp || '').toLowerCase().includes(q)
        || (r.supplier_spec || '').toLowerCase().includes(q)
      )
    }
    // 数量順だと探しにくいのでSKU順に並べる。
    // y9 と y10 が入れ違わないよう、数字の部分は数として比べる
    return [...list].sort((a, b) =>
      (a.sku || '').localeCompare(b.sku || '', 'ja', { numeric: true }))
  }, [rows, search])

  return (
    <div>
      <div className="top-actions no-print">
        <input
          className="search-input-ja"
          style={{ maxWidth: 360 }}
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="SKU・商品名・仕様で検索"
        />
      </div>

      {isLoading ? (
        <div style={{ padding: 40, textAlign: 'center', color: '#9ca3af' }}>読み込み中...</div>
      ) : visible.length === 0 ? (
        <div style={{ padding: 40, textAlign: 'center', color: '#9ca3af' }}>
          {search ? '該当する在庫がありません' : '在庫がありません'}
        </div>
      ) : (
        <div style={{ overflowX: 'auto', border: '1px solid #e5e7eb', borderRadius: 8 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, whiteSpace: 'nowrap' }}>
            <thead>
              <tr style={{ background: '#f8fafc', borderBottom: '2px solid #e2e8f0' }}>
                {['写真', 'SKU', '商品名', '仕様', '換算', '入荷数', '残量', 'この1週間の入荷', '実在庫', '備考'].map(h => (
                  <th key={h} style={{
                    padding: '10px 12px',
                    textAlign: ['入荷数', '残量', '実在庫', '換算'].includes(h) ? 'right' : 'left',
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visible.map(r => (
                <tr key={r.id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                  <td style={{ padding: '6px 12px' }}>
                    {r.image_url
                      ? <img src={mediaUrl(r.image_url)} alt="" style={{
                          width: 42, height: 42, objectFit: 'cover',
                          borderRadius: 4, display: 'block',
                        }} />
                      : '-'}
                  </td>
                  <td style={{ padding: '10px 12px', color: '#64748b' }}>{r.sku || '-'}</td>
                  <td style={{ padding: '10px 12px', fontWeight: 600, whiteSpace: 'normal', maxWidth: 260 }}>
                    {r.name_jp || '-'}
                  </td>
                  <td style={{ padding: '10px 12px', color: '#e11d48', whiteSpace: 'normal', maxWidth: 220 }}>
                    {r.supplier_spec || '-'}
                  </td>
                  <td style={{ padding: '10px 12px', textAlign: 'right' }}>
                    {(r.unit_per_set || 1) > 1 ? `${r.unit_per_set}個で1` : '1個で1'}
                  </td>
                  <td style={{ padding: '10px 12px', textAlign: 'right', color: '#64748b' }}>
                    {(r.total_received_qty || 0).toLocaleString()}
                  </td>
                  <td style={{ padding: '10px 12px', textAlign: 'right' }}>
                    {(r.remaining_qty || 0).toLocaleString()}
                  </td>
                  {/* 残量のうち、この1週間に届いたぶん。作業は平均1週間かかるので、
                      ここに出ているぶんはまだ手つかずの可能性がある。
                      1週間より前に届いたぶんは出ない（残量にだけ入っている） */}
                  <td style={{ padding: '6px 12px', whiteSpace: 'nowrap' }}>
                    {(r.recent_receipts || []).length === 0
                      ? <span style={{ color: '#cbd5e1' }}>-</span>
                      : r.recent_receipts.map(b => (
                          <div key={b.date} style={{ lineHeight: 1.5 }}>
                            <b>{b.qty.toLocaleString()}個</b>
                            <span style={{ color: '#64748b', marginLeft: 6 }}>
                              {arrivalLabel(b.date)}
                            </span>
                          </div>
                        ))}
                  </td>
                  {/* 楽天「在庫・損益」に登録されている実在庫。
                      就労支援の手元の残量とは別物なので青で見分けられるようにする */}
                  <td style={{
                    padding: '10px 12px', textAlign: 'right',
                    fontWeight: 700, color: '#2563eb',
                  }}>
                    {r.rakuten_stock == null ? '-' : r.rakuten_stock.toLocaleString()}
                  </td>
                  <td style={{ padding: '10px 12px', whiteSpace: 'normal', maxWidth: 200 }}>
                    {r.note || '-'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
