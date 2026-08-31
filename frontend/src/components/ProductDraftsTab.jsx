import { useState, useEffect, useCallback } from 'react'
import api from '../api/client'

const card = { background: '#fff', borderRadius: 8, padding: 16, border: '1px solid #e5e7eb' }
const btnPrimary = { background: '#2563eb', color: '#fff', border: 'none', borderRadius: 6, padding: '8px 16px', cursor: 'pointer', fontWeight: 600, fontSize: 13 }
const btnSecondary = { background: '#f1f5f9', color: '#334155', border: '1px solid #cbd5e1', borderRadius: 6, padding: '8px 16px', cursor: 'pointer', fontSize: 13 }
const btnSmall = { background: '#f1f5f9', border: '1px solid #cbd5e1', borderRadius: 4, padding: '2px 8px', cursor: 'pointer', fontSize: 12 }
const inputStyle = { border: '1px solid #d1d5db', borderRadius: 6, padding: '6px 10px', fontSize: 13, width: '100%', boxSizing: 'border-box' }
const label = { fontSize: 11, color: '#64748b', fontWeight: 600, display: 'block', marginBottom: 2 }

const STATUS_LABEL = { draft: '作成中', ready: '登録待ち', registered: '登録済み' }
const STATUS_COLOR = { draft: '#f59e0b', ready: '#2563eb', registered: '#16a34a' }

export default function ProductDraftsTab() {
  const [drafts, setDrafts] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [openId, setOpenId] = useState(null)
  const [genEnabled, setGenEnabled] = useState(false)
  const [statusFilter, setStatusFilter] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await api.get('/product-drafts', { params: statusFilter ? { status: statusFilter } : {} })
      setDrafts(res.data || [])
    } catch (e) {
      setError(e.response?.data?.detail || '読み込みに失敗しました')
    } finally {
      setLoading(false)
    }
  }, [statusFilter])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    api.get('/product-drafts/meta/status')
      .then(r => setGenEnabled(!!r.data.generator_enabled))
      .catch(() => setGenEnabled(false))
  }, [])

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12, flexWrap: 'wrap' }}>
        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)} style={{ ...inputStyle, width: 160 }}>
          <option value="">すべて</option>
          <option value="draft">作成中</option>
          <option value="ready">登録待ち</option>
          <option value="registered">登録済み</option>
        </select>
        <button style={btnSecondary} onClick={load} disabled={loading}>{loading ? '読込中...' : '更新'}</button>
        <span style={{ fontSize: 12, color: '#64748b' }}>{drafts.length}件</span>
        {!genEnabled && (
          <span style={{ fontSize: 12, color: '#b45309' }}>
            ※ 文章の自動生成はANTHROPIC_API_KEYを設定すると使えます
          </span>
        )}
      </div>

      {error && <div style={{ color: '#dc2626', fontSize: 13, marginBottom: 10 }}>{error}</div>}

      {drafts.length === 0 && !loading && (
        <div style={{ ...card, color: '#64748b', fontSize: 13 }}>
          採用した商品はまだありません。「ピックアップ済み」タブで商品の「採用」を押すとここに入ります。
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {drafts.map(d => (
          <DraftRow
            key={d.id}
            draft={d}
            open={openId === d.id}
            onToggle={() => setOpenId(openId === d.id ? null : d.id)}
            onChanged={load}
            genEnabled={genEnabled}
          />
        ))}
      </div>
    </div>
  )
}

function DraftRow({ draft, open, onToggle, onChanged, genEnabled }) {
  const [form, setForm] = useState(draft)
  const [saving, setSaving] = useState(false)
  const [generating, setGenerating] = useState('')
  const [genError, setGenError] = useState('')
  const [history, setHistory] = useState(null)

  useEffect(() => { setForm(draft) }, [draft])

  const set = (k) => (e) => setForm(p => ({ ...p, [k]: e.target.value }))

  const save = async (patch = {}) => {
    setSaving(true)
    try {
      const body = { ...form, ...patch }
      delete body.id; delete body.created_at; delete body.updated_at
      // サーバーが返すだけの項目。送るとバリデーションで弾かれる
      delete body.registered_at; delete body.register_error
      // 空の行は送らない。名前が無いバリエーションは作れない
      if (Array.isArray(body.variants)) {
        body.variants = body.variants.filter(v => (v.label || '').trim())
      }
      if (body.price === '') body.price = null
      if (body.supplier_price_cny === '') body.supplier_price_cny = null
      await api.put(`/product-drafts/${draft.id}`, body)
      await onChanged()
    } catch (e) {
      alert('保存に失敗しました: ' + (e.response?.data?.detail || e.message))
    } finally {
      setSaving(false)
    }
  }

  const generate = async (kind) => {
    setGenerating(kind)
    setGenError('')
    try {
      const res = await api.post(`/product-drafts/${draft.id}/generate`, { kind, apply: true })
      const g = res.data.generated || {}
      setForm(p => ({
        ...p,
        rakuten_title: g.title ?? p.rakuten_title,
        description_pc: g.description ?? p.description_pc,
      }))
      await onChanged()
    } catch (e) {
      setGenError(e.response?.data?.detail || '生成に失敗しました')
    } finally {
      setGenerating('')
    }
  }

  const loadHistory = async () => {
    if (history) { setHistory(null); return }
    try {
      const res = await api.get(`/product-drafts/${draft.id}/generations`)
      setHistory(res.data || [])
    } catch { setHistory([]) }
  }

  const remove = async () => {
    if (!confirm(`「${draft.sku || draft.rakuten_title || 'このドラフト'}」を削除します。よろしいですか？`)) return
    await api.delete(`/product-drafts/${draft.id}`)
    await onChanged()
  }

  return (
    <div style={card}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer' }} onClick={onToggle}>
        {draft.rival_image_url && (
          <img src={draft.rival_image_url} alt="" style={{ width: 44, height: 44, objectFit: 'contain', background: '#fafafa', borderRadius: 4 }} />
        )}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#111827', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {draft.sku ? <span style={{ fontFamily: 'monospace', marginRight: 8 }}>{draft.sku}</span> : null}
            {draft.rakuten_title || draft.rival_title || '(商品名未設定)'}
          </div>
          <div style={{ fontSize: 11, color: '#94a3b8' }}>参考: {draft.rival_shop_name || '-'}</div>
        </div>
        <span style={{
          fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 4,
          color: '#fff', background: STATUS_COLOR[draft.status] || '#94a3b8',
        }}>
          {STATUS_LABEL[draft.status] || draft.status}
        </span>
        <span style={{ fontSize: 12, color: '#64748b' }}>{open ? '▲' : '▼'}</span>
      </div>

      {open && (
        <div style={{ marginTop: 14, borderTop: '1px solid #e5e7eb', paddingTop: 14 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 10 }}>
            <div><span style={label}>SKU</span><input style={inputStyle} value={form.sku || ''} onChange={set('sku')} /></div>
            <div><span style={label}>販売価格（円）</span><input style={inputStyle} type="number" value={form.price ?? ''} onChange={set('price')} /></div>
            <div>
              <span style={label}>楽天ジャンルID</span>
              <input style={inputStyle} value={form.genre_id || ''} onChange={set('genre_id')}
                placeholder="空なら登録時にライバル商品から取ります" />
            </div>
            <div><span style={label}>説明担当者</span><input style={inputStyle} value={form.assignee || ''} onChange={set('assignee')} /></div>
          </div>

          <div style={{ marginTop: 12 }}>
            <span style={label}>楽天商品名</span>
            <textarea style={{ ...inputStyle, minHeight: 50 }} value={form.rakuten_title || ''} onChange={set('rakuten_title')} />
            {genEnabled && (
              <button style={{ ...btnSmall, marginTop: 4 }} disabled={!!generating} onClick={() => generate('title')}>
                {generating === 'title' ? '生成中...' : '✨ タイトルを生成'}
              </button>
            )}
          </div>

          <div style={{ marginTop: 12 }}>
            <span style={label}>商品説明（PC）</span>
            <textarea style={{ ...inputStyle, minHeight: 120, fontFamily: 'monospace', fontSize: 12 }} value={form.description_pc || ''} onChange={set('description_pc')} />
            {genEnabled && (
              <button style={{ ...btnSmall, marginTop: 4 }} disabled={!!generating} onClick={() => generate('description')}>
                {generating === 'description' ? '生成中...' : '✨ 説明文を生成'}
              </button>
            )}
          </div>
          {genError && <div style={{ color: '#dc2626', fontSize: 12, marginTop: 6 }}>{genError}</div>}

          <ImageEditor draftId={draft.id} label={label} btnSmall={btnSmall} />

          <VariantEditor form={form} setForm={setForm} label={label}
            inputStyle={inputStyle} btnSmall={btnSmall} />

          <div style={{ marginTop: 16, background: '#f8fafc', borderRadius: 6, padding: 12 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: '#334155', marginBottom: 8 }}>仕入れ情報（1688）</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 10 }}>
              <div><span style={label}>アリババURL</span><input style={inputStyle} value={form.supplier_url || ''} onChange={set('supplier_url')} /></div>
              <div><span style={label}>中国語商品名</span><input style={inputStyle} value={form.supplier_name_cn || ''} onChange={set('supplier_name_cn')} /></div>
              <div><span style={label}>色・サイズ等の仕様</span><input style={inputStyle} value={form.supplier_spec || ''} onChange={set('supplier_spec')} /></div>
              <div><span style={label}>仕入単価（元）</span><input style={inputStyle} type="number" step="0.01" value={form.supplier_price_cny ?? ''} onChange={set('supplier_price_cny')} /></div>
            </div>
            <div style={{ marginTop: 8 }}>
              <span style={label}>商品備考（発注時の指示など）</span>
              <textarea style={{ ...inputStyle, minHeight: 50 }} value={form.supplier_note || ''} onChange={set('supplier_note')} />
            </div>
          </div>

          <div style={{ marginTop: 12, background: '#fffbeb', borderRadius: 6, padding: 12 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: '#92400e', marginBottom: 8 }}>
              参考にしたライバル商品（そのまま流用せず、文章生成の材料として使います）
            </div>
            <div style={{ fontSize: 12, marginBottom: 6 }}>
              {draft.rival_url
                ? <a href={draft.rival_url} target="_blank" rel="noreferrer">{draft.rival_title || draft.rival_url}</a>
                : (draft.rival_title || '-')}
              {draft.rival_price ? <span style={{ color: '#64748b', marginLeft: 8 }}>¥{draft.rival_price.toLocaleString()}</span> : null}
            </div>
            <span style={label}>ライバルの商品説明</span>
            <textarea style={{ ...inputStyle, minHeight: 80, fontSize: 12 }} value={form.rival_caption || ''} onChange={set('rival_caption')} placeholder="自動取得できなかった場合はここに貼り付けてください" />
          </div>

          <div style={{ marginTop: 12 }}>
            <span style={label}>社内メモ</span>
            <textarea style={{ ...inputStyle, minHeight: 50 }} value={form.memo || ''} onChange={set('memo')} />
          </div>

          <div style={{ marginTop: 14, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <button style={btnPrimary} onClick={() => save()} disabled={saving}>{saving ? '保存中...' : '保存'}</button>
            <select style={{ ...inputStyle, width: 150 }} value={form.status || 'draft'} onChange={e => save({ status: e.target.value })}>
              <option value="draft">作成中</option>
              <option value="ready">登録待ち</option>
              <option value="registered">登録済み</option>
            </select>
            <button style={btnSecondary} onClick={loadHistory}>{history ? '生成履歴を閉じる' : '生成履歴'}</button>
            <button style={{ ...btnSecondary, marginLeft: 'auto', color: '#dc2626' }} onClick={remove}>削除</button>
          </div>

          {history && (
            <div style={{ marginTop: 12, borderTop: '1px dashed #e5e7eb', paddingTop: 10 }}>
              {history.length === 0 && <div style={{ fontSize: 12, color: '#94a3b8' }}>まだ生成していません</div>}
              {history.map(h => (
                <div key={h.id} style={{ marginBottom: 10, fontSize: 12 }}>
                  <div style={{ color: '#94a3b8' }}>
                    {h.created_at?.slice(0, 16).replace('T', ' ')}・{h.kind}・{h.model}
                  </div>
                  <div style={{ whiteSpace: 'pre-wrap', background: '#f8fafc', padding: 8, borderRadius: 4, marginTop: 2 }}>{h.output}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}


/**
 * バリエーション（色違いなど）の入力。
 *
 * 楽天は「軸（カラー）」と「枝（ホワイト・ネイビー）」で持つので、
 * その形のまま入れてもらう。軸が空なら単品として登録する。
 */
function VariantEditor({ form, setForm, label, inputStyle, btnSmall }) {
  const rows = form.variants || []
  const axis = form.variant_axis || ''

  const setRows = next => setForm(f => ({ ...f, variants: next }))
  const setRow = (i, key, v) =>
    setRows(rows.map((r, n) => (n === i ? { ...r, [key]: v } : r)))

  return (
    <div style={{ marginTop: 16, background: '#f8fafc', borderRadius: 6, padding: 12 }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: '#334155', marginBottom: 8 }}>
        バリエーション（色違い・サイズ違い）
      </div>

      <div style={{ maxWidth: 260 }}>
        <span style={label}>軸の名前</span>
        <input style={inputStyle} value={axis} placeholder="カラー / サイズ など"
          onChange={e => setForm(f => ({ ...f, variant_axis: e.target.value }))} />
      </div>
      <div style={{ fontSize: 11, color: '#64748b', marginTop: 4 }}>
        空にすると単品として登録します。
      </div>

      {axis && (
        <>
          <table style={{ width: '100%', marginTop: 10, fontSize: 13 }}>
            <thead>
              <tr style={{ color: '#64748b', fontSize: 11 }}>
                <th style={{ textAlign: 'left' }}>選択肢の名前</th>
                <th style={{ textAlign: 'left', width: 130 }}>枝のID（英数字）</th>
                <th style={{ textAlign: 'left', width: 110 }}>価格（空=共通）</th>
                <th style={{ width: 40 }} />
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td style={{ paddingRight: 6 }}>
                    <input style={inputStyle} value={r.label || ''} placeholder="ホワイト"
                      onChange={e => setRow(i, 'label', e.target.value)} />
                  </td>
                  <td style={{ paddingRight: 6 }}>
                    <input style={inputStyle} value={r.suffix || ''} placeholder="white"
                      onChange={e => setRow(i, 'suffix', e.target.value)} />
                  </td>
                  <td style={{ paddingRight: 6 }}>
                    <input style={inputStyle} type="number" value={r.price ?? ''}
                      onChange={e => setRow(i, 'price',
                        e.target.value === '' ? null : Number(e.target.value))} />
                  </td>
                  <td>
                    <button style={btnSmall}
                      onClick={() => setRows(rows.filter((_, n) => n !== i))}>×</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <button style={{ ...btnSmall, marginTop: 8 }}
            onClick={() => setRows([...rows, { label: '', suffix: '', price: null }])}>
            ＋ 選択肢を追加
          </button>

          {form.sku && rows.some(r => r.label) && (
            <div style={{ fontSize: 11, color: '#64748b', marginTop: 8 }}>
              楽天にはこの形で登録されます：
              {rows.filter(r => r.label).map((r, i) => (
                <span key={i} style={{ marginLeft: 6, fontFamily: 'monospace' }}>
                  {form.sku}_{r.suffix || `v${i + 1}`}
                </span>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}


/**
 * 商品画像。
 *
 * R-Cabinetへの書き込みはCompassにログインしたブラウザからしかできず、
 * ここからは直接送れない。画像はいったんサーバーへ預けておき、登録の
 * ときに手元のPCがR-Cabinetへ上げる。
 */
function ImageEditor({ draftId, label, btnSmall }) {
  const [images, setImages] = useState([])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const load = async () => {
    try {
      const r = await api.get(`/product-drafts/${draftId}/images`)
      setImages(r.data)
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    }
  }
  useEffect(() => { load() }, [draftId])

  const add = async (files) => {
    setBusy(true); setErr('')
    try {
      for (const f of files) {
        const b64 = await new Promise((resolve, reject) => {
          const rd = new FileReader()
          rd.onload = () => resolve(String(rd.result).split(',')[1])
          rd.onerror = reject
          rd.readAsDataURL(f)
        })
        await api.post(`/product-drafts/${draftId}/images`,
          { file_name: f.name, mime: f.type || 'image/jpeg', data: b64 })
      }
      await load()
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  const remove = async (id) => {
    setBusy(true)
    try {
      await api.delete(`/product-drafts/${draftId}/images/${id}`)
      await load()
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  return (
    <div style={{ marginTop: 16, background: '#f8fafc', borderRadius: 6, padding: 12 }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: '#334155', marginBottom: 8 }}>
        商品画像
      </div>

      <div
        onDragOver={e => e.preventDefault()}
        onDrop={e => { e.preventDefault(); add([...e.dataTransfer.files]) }}
        style={{ border: '2px dashed #cbd5e1', borderRadius: 6, padding: 16,
          textAlign: 'center', color: '#64748b', fontSize: 13, background: '#fff' }}>
        ここに画像をドラッグ＆ドロップ、または
        <label style={{ color: '#2563eb', cursor: 'pointer', marginLeft: 4 }}>
          ファイルを選ぶ
          <input type="file" accept="image/*" multiple style={{ display: 'none' }}
            onChange={e => { add([...e.target.files]); e.target.value = '' }} />
        </label>
      </div>

      {err && <div style={{ color: '#dc2626', fontSize: 12, marginTop: 6 }}>{err}</div>}
      {busy && <div style={{ fontSize: 12, color: '#64748b', marginTop: 6 }}>処理中…</div>}

      {images.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 12 }}>
          {images.map(i => (
            <div key={i.id} style={{ width: 110, fontSize: 11 }}>
              <div style={{ position: 'relative' }}>
                <img
                  src={i.cabinet_url
                    ? `https://image.rakuten.co.jp/misora-mart/cabinet${i.cabinet_url}`
                    : `${api.defaults.baseURL}/product-drafts/${draftId}/images/${i.id}/preview`}
                  alt={i.file_name}
                  style={{ width: '100%', height: 110, objectFit: 'cover',
                    borderRadius: 4, border: '1px solid #e2e8f0', background: '#fff' }} />
                <button onClick={() => remove(i.id)} title="消す"
                  style={{ position: 'absolute', top: 2, right: 2, border: 'none',
                    background: 'rgba(0,0,0,.6)', color: '#fff', borderRadius: 3,
                    cursor: 'pointer', lineHeight: 1, padding: '2px 5px' }}>×</button>
              </div>
              <div style={{ marginTop: 3, overflow: 'hidden',
                textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={i.file_name}>
                {i.file_name}
              </div>
              <div style={{ color: i.cabinet_url ? '#16a34a' : '#94a3b8' }}>
                {i.cabinet_url ? '楽天へ登録済み' : `${Math.round((i.size || 0) / 1024)}KB`}
              </div>
            </div>
          ))}
        </div>
      )}

      <div style={{ fontSize: 11, color: '#64748b', marginTop: 8 }}>
        登録するときに、SKU名のフォルダを作ってR-Cabinetへ上げます。
        1枚2MBまでです。
      </div>
    </div>
  )
}
