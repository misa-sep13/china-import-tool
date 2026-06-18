import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import axios from 'axios'

const BASE = import.meta.env.VITE_API_URL?.replace('/api', '') || 'http://localhost:8000'

export default function SyncLogsPage() {
  const [autoRefresh, setAutoRefresh] = useState(true)

  const { data, dataUpdatedAt } = useQuery({
    queryKey: ['sync-logs'],
    queryFn: () => axios.get(`${BASE}/api/sync-logs`).then(r => r.data),
    refetchInterval: autoRefresh ? 30000 : false,
  })

  const logs = data?.logs || []

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>在庫同期ログ</h2>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
          <input type="checkbox" checked={autoRefresh} onChange={e => setAutoRefresh(e.target.checked)} />
          30秒自動更新
        </label>
        {dataUpdatedAt && (
          <span style={{ fontSize: 12, color: '#666' }}>
            最終更新: {new Date(dataUpdatedAt).toLocaleTimeString('ja-JP')}
          </span>
        )}
      </div>

      {logs.length === 0 ? (
        <div className="card" style={{ padding: 32, textAlign: 'center', color: '#666' }}>
          ログがありません。注文が入ると表示されます。
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {logs.map((log, i) => (
            <div key={i} className="card" style={{ padding: '12px 16px', borderLeft: log.error ? '4px solid #e53e3e' : '4px solid #38a169' }}>
              <div style={{ fontSize: 12, color: '#666', marginBottom: 6 }}>{log.time}</div>
              {log.error ? (
                <div style={{ color: '#e53e3e', fontSize: 13 }}>エラー: {log.error}</div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <div>
                    <span style={{ fontSize: 12, color: '#666', marginRight: 8 }}>売れた商品:</span>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
                      {Object.entries(log.sold || {}).map(([sku, qty]) => (
                        <span key={sku} style={{ background: '#e6fffa', border: '1px solid #38a169', borderRadius: 4, padding: '2px 8px', fontSize: 13 }}>
                          {sku}: {qty}個
                        </span>
                      ))}
                    </div>
                  </div>
                  <div>
                    <span style={{ fontSize: 12, color: '#666', marginRight: 8 }}>RMS反映予定 (確認中):</span>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
                      {Object.entries(log.rms_would_update || {}).map(([sku, qty]) => (
                        <span key={sku} style={{ background: '#ebf8ff', border: '1px solid #3182ce', borderRadius: 4, padding: '2px 8px', fontSize: 13 }}>
                          {sku}: {qty}個
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
