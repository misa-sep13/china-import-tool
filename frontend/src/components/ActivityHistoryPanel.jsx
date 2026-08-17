import { useQuery } from '@tanstack/react-query'
import api from '../api/client'

const ACTION_LABEL = {
  create: '登録', update: '更新', delete: '削除',
  stock_change: '在庫変更', import: '荷受け', withdraw: '出庫', adjust: '残量修正',
}

const fmtTime = (iso) => {
  if (!iso) return ''
  try { return new Date(iso).toLocaleString('ja-JP', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) }
  catch { return iso }
}

export default function ActivityHistoryPanel({ open, onClose }) {
  const { data, isLoading } = useQuery({
    queryKey: ['activity-log-recent'],
    queryFn: () => api.get('/activity-log/recent', { params: { limit: 80 } }).then(r => r.data),
    enabled: open,
    refetchInterval: open ? 30000 : false,
  })

  if (!open) return null
  const items = data?.items || []

  return (
    <>
      <div
        onClick={onClose}
        style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', zIndex: 200 }}
      />
      <div style={{
        position: 'fixed', top: 0, right: 0, bottom: 0, width: 420, maxWidth: '90vw',
        background: '#fff', zIndex: 201, boxShadow: '-4px 0 16px rgba(0,0,0,0.2)',
        display: 'flex', flexDirection: 'column',
      }}>
        <div style={{ padding: '16px 20px', borderBottom: '1px solid #e2e8f0', display: 'flex', alignItems: 'center' }}>
          <h3 style={{ margin: 0, fontSize: 16 }}>更新履歴</h3>
          <button className="btn btn-secondary" style={{ marginLeft: 'auto', fontSize: 12 }} onClick={onClose}>閉じる</button>
        </div>
        <div style={{ overflowY: 'auto', flex: 1, padding: '8px 0' }}>
          {isLoading && <div style={{ padding: 20, color: '#64748b', fontSize: 13 }}>読み込み中...</div>}
          {!isLoading && items.length === 0 && (
            <div style={{ padding: 20, color: '#64748b', fontSize: 13 }}>まだ記録がありません</div>
          )}
          {items.map((it, i) => (
            <div key={i} style={{ padding: '10px 20px', borderBottom: '1px solid #f1f5f9' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 }}>
                <span style={{ fontSize: 11, color: '#94a3b8' }}>{fmtTime(it.created_at)}</span>
                {it.actor_label && (
                  <span style={{
                    fontSize: 10, fontWeight: 700, padding: '1px 6px', borderRadius: 3,
                    background: it.actor === 'contractor' ? '#fef3c7' : it.actor === 'service' ? '#e0e7ff' : '#dcfce7',
                    color: it.actor === 'contractor' ? '#92400e' : it.actor === 'service' ? '#3730a3' : '#166534',
                  }}>
                    {it.actor_label}
                  </span>
                )}
                <span style={{ fontSize: 11, color: '#64748b' }}>{ACTION_LABEL[it.action] || it.action}</span>
              </div>
              <div style={{ fontSize: 13, color: '#1a1a2e' }}>{it.summary}</div>
            </div>
          ))}
        </div>
        <div style={{ padding: '10px 20px', borderTop: '1px solid #e2e8f0', fontSize: 11, color: '#94a3b8' }}>
          在庫の書き換え・商品マスタの登録/更新/削除・入出庫を中心に記録しています（全操作の網羅ではありません）
        </div>
      </div>
    </>
  )
}
