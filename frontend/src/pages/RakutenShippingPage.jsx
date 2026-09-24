import { useCallback, useMemo, useState } from 'react'
import api from '../api/client'
import { matchesQuery } from '../searchUtil'

/**
 * 楽天の発送処理。
 *
 * RMSの画面は一度に299件しか発送完了メールを送れない（この店舗だけの不具合）。
 * 伝票番号のCSVはこれまでどおり上げて、そのあとの
 *   ・ちゃんと入ったかの確認
 *   ・発送完了報告（＝発送完了メール）
 * をここでやる。APIは画面を通らないので299件の制限を受けない。
 *
 * いまは確認まで。発送完了報告は、この画面で送付先IDと発送明細IDが
 * 取れていることを確かめてから付ける。指定せずに報告すると発送情報が
 * 「追加」になり、伝票番号が二重に並ぶため。
 */

const C = {
  line: '#e5e7eb', sub: '#64748b', text: '#0f172a',
  good: '#16a34a', warn: '#b45309', bad: '#dc2626', key: '#2563eb',
}

// 発送完了報告で使う配送会社コード。表示用
const CARRIER = {
  '1001': 'ヤマト', '1002': '佐川', '1003': '日本郵便', '1004': '西濃',
  '1028': 'Rakuten EXPRESS', '1030': 'クロネコゆうパケット', '1000': 'その他',
}

const th = {
  padding: '6px 8px', textAlign: 'left', fontSize: 11, color: C.sub,
  background: '#f8fafc', whiteSpace: 'nowrap',
}
const td = { padding: '6px 8px', fontSize: 12, borderTop: `1px solid ${C.line}` }

export default function RakutenShippingPage() {
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [days, setDays] = useState(45)
  const [group, setGroup] = useState('ALL')
  const [onlyMissing, setOnlyMissing] = useState(false)
  const [q, setQ] = useState('')

  const load = useCallback(async () => {
    setBusy(true)
    setErr('')
    try {
      const r = await api.get('/rakuten/shipping/targets', { params: { days } })
      setData(r.data)
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally {
      setBusy(false)
    }
  }, [days])

  const orders = data?.orders || []
  const shown = useMemo(() => orders.filter(o => {
    if (group !== 'ALL' && String(o.sub_status_id ?? '') !== group) return false
    if (onlyMissing && o.has_number) return false
    if (q.trim() && !matchesQuery(q, [o.order_number, o.orderer,
      ...(o.shipments || []).map(s => s.shipping_number)])) return false
    return true
  }), [orders, group, onlyMissing, q])

  const missing = orders.filter(o => !o.has_number).length
  const diag = data?.diagnostics

  return (
    <div style={{ padding: 2, minWidth: 0 }}>
      <h2 style={{ fontSize: 18, marginBottom: 4 }}>🚚 楽天 発送処理</h2>
      <div style={{ fontSize: 12, color: C.sub, marginBottom: 12 }}>
        伝票番号のCSVを上げたあと、ちゃんと入ったかをここで確認します。
        発送待ちの注文だけを出しています。
      </div>

      {err && (
        <div style={{
          background: '#fef2f2', border: '1px solid #fecaca', color: '#991b1b',
          padding: 10, borderRadius: 6, marginBottom: 10, fontSize: 13,
        }}>{err}</div>
      )}

      <div className="card" style={{
        marginBottom: 12, display: 'flex', gap: 12, alignItems: 'center',
        flexWrap: 'wrap',
      }}>
        <label style={{ fontSize: 12, color: C.sub }}>
          注文日から
          <input type="number" min={1} max={90} value={days}
            onChange={e => setDays(Number(e.target.value))}
            style={{ width: 60, margin: '0 4px' }} />
          日ぶん
        </label>
        <button className="btn btn-primary" onClick={load} disabled={busy}>
          {busy ? '読み込み中…（数十秒かかります）' : '読み込む'}
        </button>
        {data && (
          <>
            <span style={{ fontSize: 13 }}>
              発送待ち <b>{data.total}</b>件
              {missing > 0 && (
                <span style={{ color: C.bad, fontWeight: 700 }}>
                  　伝票番号なし {missing}件
                </span>
              )}
            </span>
            <label style={{
              fontSize: 12, color: C.sub, display: 'flex', alignItems: 'center',
              gap: 4,
            }}>
              <input type="checkbox" checked={onlyMissing}
                onChange={e => setOnlyMissing(e.target.checked)}
                style={{ width: 'auto' }} />
              伝票番号が入っていないものだけ
            </label>
            <input value={q} onChange={e => setQ(e.target.value)}
              placeholder="注文番号・お名前・伝票番号で絞り込み"
              className="search-input-ja" style={{ width: 240 }} />
          </>
        )}
      </div>

      {/* サブステータス。本日発送分・あざみ分・在庫切れ1 など */}
      {data && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
          <Tab on={group === 'ALL'} onClick={() => setGroup('ALL')}
            label="すべて" count={orders.length} />
          {(data.groups || []).map(g => (
            <Tab key={g.id || 'none'} on={group === g.id}
              onClick={() => setGroup(g.id)}
              label={g.name || `サブステータス ${g.id}`} count={g.count} />
          ))}
        </div>
      )}

      {/* 項目名が仕様と違っていたら、ここで気づけるようにしておく。
          発送完了報告には送付先IDと発送明細IDが要る */}
      {diag && (
        <div style={{
          marginBottom: 12, fontSize: 12, padding: '6px 10px', borderRadius: 6,
          background: diag.with_shipping_detail_id > 0 ? '#f0fdf4' : '#fffbeb',
          border: `1px solid ${diag.with_shipping_detail_id > 0 ? '#bbf7d0' : '#fcd34d'}`,
          color: diag.with_shipping_detail_id > 0 ? '#166534' : '#92400e',
        }}>
          発送完了報告に要る値：{data.total}件のうち
          送付先IDが取れたもの {diag.with_basket_id}件、
          発送明細IDが取れたもの {diag.with_shipping_detail_id}件。
          {diag.with_shipping_detail_id === 0
            ? '発送明細IDが取れていません。このまま報告すると発送情報が二重に登録されるので、報告は付けられません。'
            : diag.with_shipping_detail_id < data.total
              ? `残り ${data.total - diag.with_shipping_detail_id}件はまだ発送情報がありません（伝票番号が未入力の注文です）。それ以外は発送完了報告に出せます。`
              : '全件そろっています。発送完了報告まで作れます。'}
        </div>
      )}

      {data && (
        <div className="card" style={{ padding: 0, overflow: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                {['注文番号', '注文日', 'サブステータス', 'お名前', '配送会社',
                  'お荷物伝票番号', '発送日', '送付先ID', '発送明細ID'].map(h => (
                    <th key={h} style={th}>{h}</th>
                  ))}
              </tr>
            </thead>
            <tbody>
              {shown.length === 0 && (
                <tr><td style={{ ...td, color: C.sub, padding: 20 }} colSpan={9}>
                  出す注文がありません。
                </td></tr>
              )}
              {shown.map(o => {
                const ships = (o.shipments && o.shipments.length) ? o.shipments : [{}]
                return ships.map((s, i) => (
                  <tr key={`${o.order_number}-${i}`}
                    style={{ background: o.has_number ? undefined : '#fff7ed' }}>
                    <td style={{ ...td, fontFamily: 'monospace', fontSize: 11 }}>
                      {i === 0 ? o.order_number : ''}
                    </td>
                    <td style={{ ...td, whiteSpace: 'nowrap', color: C.sub }}>
                      {i === 0 ? o.order_date : ''}
                    </td>
                    <td style={{ ...td, whiteSpace: 'nowrap' }}>
                      {i === 0
                        ? (o.sub_status_name
                          || (o.sub_status_id ? `サブステータス ${o.sub_status_id}` : '—'))
                        : ''}
                    </td>
                    <td style={{ ...td, whiteSpace: 'nowrap' }}>
                      {i === 0 ? o.orderer : ''}
                    </td>
                    <td style={{ ...td, whiteSpace: 'nowrap' }}>
                      {CARRIER[s.delivery_company] || s.delivery_company || '—'}
                    </td>
                    <td style={{
                      ...td, fontFamily: 'monospace', fontSize: 11,
                      color: s.shipping_number ? C.text : C.bad,
                      fontWeight: s.shipping_number ? 400 : 700,
                    }}>
                      {s.shipping_number || '未入力'}
                    </td>
                    <td style={{ ...td, whiteSpace: 'nowrap', color: C.sub }}>
                      {s.shipping_date || '—'}
                    </td>
                    <td style={{ ...td, color: C.sub, fontSize: 11 }}>
                      {s.basket_id ?? '—'}
                    </td>
                    <td style={{ ...td, color: C.sub, fontSize: 11 }}>
                      {s.shipping_detail_id ?? '—'}
                    </td>
                  </tr>
                ))
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function Tab({ on, onClick, label, count }) {
  return (
    <button onClick={onClick} className="btn btn-sm"
      style={{
        fontSize: 12, padding: '3px 10px',
        background: on ? '#2563eb' : '#f1f5f9',
        color: on ? '#fff' : '#334155',
        border: `1px solid ${on ? '#2563eb' : C.line}`,
      }}>
      {label}（{count}）
    </button>
  )
}
