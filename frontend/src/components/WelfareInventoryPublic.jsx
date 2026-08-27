import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '../api/client'

/**
 * 就労支援さん向けの在庫一覧（閲覧のみ）。
 *
 * 管理画面(WelfareInventoryPage)と違い、入力欄も更新ボタンも置かない。
 * 「いま手元に何が何個あるか」を見るためだけのもの。
 */
export default function WelfareInventoryPublic() {
  const [search, setSearch] = useState('')

  const { data: rows = [], isLoading } = useQuery({
    queryKey: ['welfare-inventory-public'],
    queryFn: () => api.get('/welfare/inventory').then(r => r.data),
    refetchInterval: 60000,
  })

  const visible = useMemo(() => {
    // 残がないものは作業に使えないので出さない
    const list = rows.filter(r => (r.remaining_qty || 0) > 0)
    const q = search.trim().toLowerCase()
    if (!q) return list
    return list.filter(r =>
      (r.sku || '').toLowerCase().includes(q)
      || (r.name_jp || '').toLowerCase().includes(q)
      || (r.supplier_spec || '').toLowerCase().includes(q)
    )
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
                {['写真', 'SKU', '商品名', '仕様', '換算', '残量', '指示', '備考'].map(h => (
                  <th key={h} style={{
                    padding: '10px 12px',
                    textAlign: ['残量', '換算'].includes(h) ? 'right' : 'left',
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visible.map(r => (
                <tr key={r.id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                  <td style={{ padding: '6px 12px' }}>
                    {r.image_data_url
                      ? <img src={r.image_data_url} alt="" style={{
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
                  <td style={{ padding: '10px 12px', textAlign: 'right', fontWeight: 700 }}>
                    {(r.remaining_qty || 0).toLocaleString()}
                  </td>
                  <td style={{ padding: '10px 12px', whiteSpace: 'normal', maxWidth: 200 }}>
                    {r.instruction || '-'}
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
