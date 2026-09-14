import { useEffect, useState } from 'react'
import api from '../api/client'
import { C, card, label, input, Err } from './ListingTab'

/**
 * 商品マスタへの登録。
 *
 * 出品を送っても、これまでツールのAmazon商品マスタには1行も作られず、
 * 出品した商品が発注管理にも在庫管理にも出てこなかった。発注はマスタの
 * 情報を使うので、出品より前に作る。
 *
 * 押す前に必ず対応表を見せる。仕入URLと入数を推測で埋めると、違うものを
 * 違う数だけ発注することになるため。
 */
export default function MasterPanel({ listingId, onClose, onDone }) {
  const [d, setD] = useState(null)
  const [rows, setRows] = useState([])
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [done, setDone] = useState(null)

  useEffect(() => {
    api.get(`/amazon-listings/${listingId}/master-preview`)
      .then(r => {
        setD(r.data)
        setRows(r.data.rows || [])
        setUrl(((r.data.rows || [])[0] || {}).buy_url || '')
      })
      .catch(e => setErr(e.response?.data?.detail || e.message))
  }, [listingId])

  const patch = (i, v) =>
    setRows(rs => rs.map((r, n) => (n === i ? { ...r, ...v } : r)))

  const run = async () => {
    setBusy(true)
    setErr('')
    try {
      const r = await api.post(`/amazon-listings/${listingId}/to-master`, {
        rows: rows.map(x => ({
          sku: x.sku, name: x.name, color: x.color, size: x.size, spec: x.spec,
          buy_url: url || x.buy_url || '',
          price: x.price, set_size: x.set_size,
          selling_price: x.selling_price, cost_jpy: x.cost_jpy,
          fba_fee: x.fba_fee, asin: x.asin,
        })),
        components: d.components || [],
      })
      setDone(r.data)
      if (onDone) onDone()
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally {
      setBusy(false)
    }
  }

  const cell = { padding: '4px 7px', borderTop: `1px solid ${C.line}` }
  const head = { textAlign: 'left', padding: '5px 7px', whiteSpace: 'nowrap' }

  return (
    <div
      style={{
        position: 'fixed', inset: 0, background: 'rgba(15,23,42,.45)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: 20, zIndex: 60,
      }}
      onClick={e => { if (e.target === e.currentTarget && !busy) onClose() }}
    >
      <div style={{
        background: '#fff', borderRadius: 10, width: 'min(1050px, 100%)',
        maxHeight: '90vh', display: 'flex', flexDirection: 'column',
      }}>
        <div style={{ padding: '13px 18px', borderBottom: `1px solid ${C.line}` }}>
          <b style={{ fontSize: 15 }}>📦 商品マスタに登録</b>
          <span style={{ fontSize: 12, color: C.sub, marginLeft: 10 }}>
            発注はここの情報を使います。仕入URLと入数を確かめてください
          </span>
        </div>

        <div style={{ padding: 16, overflow: 'auto', flex: 1 }}>
          {err && <Err text={err} />}
          {!d && !err && (
            <div style={{ fontSize: 13, color: C.sub }}>読み込んでいます…</div>
          )}

          {done && (
            <div style={{
              background: '#f0fdf4', border: '1px solid #bbf7d0', color: '#166534',
              padding: 12, borderRadius: 6, fontSize: 13, lineHeight: 1.8,
            }}>
              <b>商品マスタに登録しました。</b><br />
              新しく作成 {done.created.length}件
              {done.created.length > 0 && `：${done.created.join('、')}`}<br />
              すでにあったので空欄だけ補った {done.updated.length}件
              {done.updated.length > 0 && `：${done.updated.join('、')}`}
              {done.components > 0 && (
                <><br />発注用付属品 {done.components}件も入れました</>
              )}
            </div>
          )}

          {d && !done && (
            <>
              {(d.warnings || []).map((w, i) => (
                <div key={i} style={{
                  background: '#fffbeb', border: '1px solid #fde68a', color: '#92400e',
                  padding: '8px 10px', borderRadius: 6, fontSize: 12, marginBottom: 6,
                }}>⚠ {w}</div>
              ))}

              {(d.url_choices || []).length > 1 && (
                <div style={{ ...card, marginBottom: 10 }}>
                  <div style={label}>発注に使う仕入URL（候補が複数あります）</div>
                  {d.url_choices.map(u => (
                    <label key={u} style={{
                      display: 'flex', gap: 6, fontSize: 12,
                      alignItems: 'center', marginBottom: 3,
                    }}>
                      <input type="radio" name="buyurl" checked={url === u}
                        style={{ width: 'auto', flex: '0 0 auto' }}
                        onChange={() => setUrl(u)} />
                      <span style={{ wordBreak: 'break-all' }}>{u}</span>
                    </label>
                  ))}
                </div>
              )}

              <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ background: '#f1f5f9', color: C.sub }}>
                    {['SKU', '商品名', 'カラー', 'サイズ', '仕入単価(元)', '入数',
                      '売価(円)', 'ASIN', ''].map(h => (
                        <th key={h} style={head}>{h}</th>
                      ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => (
                    <tr key={r.sku}>
                      <td style={{ ...cell, fontWeight: 700 }}>{r.sku}</td>
                      <td style={cell}>
                        <input style={{ ...input, fontSize: 12 }} value={r.name || ''}
                          onChange={e => patch(i, { name: e.target.value })} />
                      </td>
                      <td style={cell}>{r.color || '—'}</td>
                      <td style={cell}>{r.size || '—'}</td>
                      <td style={cell}>
                        <input style={{ ...input, fontSize: 12, width: 80 }}
                          type="number" value={r.price == null ? '' : r.price}
                          onChange={e => patch(i, {
                            price: e.target.value === '' ? null : Number(e.target.value),
                          })} />
                      </td>
                      <td style={cell}>
                        <input style={{ ...input, fontSize: 12, width: 60 }}
                          type="number" value={r.set_size == null ? 1 : r.set_size}
                          onChange={e => patch(i, {
                            set_size: Number(e.target.value) || 1,
                          })} />
                      </td>
                      <td style={cell}>{r.selling_price == null ? '—' : r.selling_price}</td>
                      <td style={cell}>{r.asin || '—'}</td>
                      <td style={{
                        ...cell, whiteSpace: 'nowrap',
                        color: r.exists ? C.warn : C.good,
                      }}>
                        {r.exists ? '既にあります（空欄だけ補う）' : '新規'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {(d.components || []).length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <div style={label}>発注用付属品（在庫には連動しません）</div>
                  <table style={{ fontSize: 12, borderCollapse: 'collapse' }}>
                    <tbody>
                      {d.components.map((c, i) => (
                        <tr key={i}>
                          <td style={cell}>{c.name || '（名前なし）'}</td>
                          <td style={cell}>×{c.qty}</td>
                          <td style={cell}>{c.price == null ? '—' : `${c.price}元`}</td>
                          <td style={{
                            ...cell, wordBreak: 'break-all',
                            color: c.buy_url ? C.text : C.bad,
                          }}>
                            {c.buy_url || 'URLなし（このままだと発注できません）'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>

        <div style={{
          padding: '12px 18px', borderTop: `1px solid ${C.line}`,
          display: 'flex', gap: 8, justifyContent: 'flex-end',
        }}>
          <button className="btn btn-secondary" onClick={onClose} disabled={busy}>
            {done ? '閉じる' : 'やめる'}
          </button>
          {!done && (
            <button className="btn btn-primary" onClick={run}
              disabled={busy || !d || !rows.length}>
              {busy ? '登録しています…' : `この ${rows.length} 件を商品マスタに登録`}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
