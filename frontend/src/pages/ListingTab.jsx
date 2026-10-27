import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import api from '../api/client'
import ListingEditor from './ListingEditor'

/**
 * Amazon 商品登録（リサーチの3つ目のタブ）。
 *
 * これまでの登録画面は楽天用のドラフトを流用していて、リサーチで調べた
 * 情報が何ひとつ出ていなかった。ここでは競合リサーチシートを直接の元にし、
 * 判断根拠（販売個数・レビュー・粗利率）を見ながら出品内容を仕上げられる。
 *
 * シートの「🏷 出品原稿をつくる」がまだ使われていないため、タイトル・
 * 検索キーワード・要点はこの画面でも書けるようにしてある。
 */

const C = {
  line: '#e5e7eb', sub: '#64748b', text: '#0f172a',
  good: '#16a34a', warn: '#b45309', bad: '#dc2626',
  key: '#2563eb', soft: '#f8fafc',
}

const card = {
  background: '#fff', border: `1px solid ${C.line}`,
  borderRadius: 8, padding: 14,
}
const label = {
  display: 'block', fontSize: 12, color: C.sub, marginBottom: 4, fontWeight: 600,
}
const input = {
  width: '100%', padding: '7px 9px', border: `1px solid ${C.line}`,
  borderRadius: 6, fontSize: 13, boxSizing: 'border-box', color: C.text,
}

const bytes = s => new TextEncoder().encode(s || '').length

export default function ListingTab() {
  const [rows, setRows] = useState([])
  const [openId, setOpenId] = useState(null)      // listing_id
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [onlyReady, setOnlyReady] = useState(false)

  // 発番しただけではGS1に登録されない。溜まったら一括で届け出るので、
  // 未登録の件数をここに出しておく
  const [gs1, setGs1] = useState(null)
  // 出品に使うブランド。Amazonのブランド登録が通るまでは「ノーブランド品」で
  // 出すしかないので、通った時点でここを切り替える
  const [brand, setBrand] = useState(null)

  const load = useCallback(async () => {
    setErr('')
    try {
      const [r, g, st] = await Promise.all([
        api.get('/amazon-listings'),
        api.get('/amazon-research/jan/gs1-pending').catch(() => null),
        api.get('/amazon-research/settings').catch(() => null),
      ])
      setRows(r.data.rows || [])
      setGs1(g ? g.data : null)
      if (st) setBrand({ name: st.data.brand_name || '' })
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    }
  }, [])

  const saveBrand = async (next) => {
    setBrand(next)
    try {
      await api.put('/amazon-research/settings', { brand_name: next.name })
      await load()
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    }
  }
  useEffect(() => { load() }, [load])

  // ツールの外（Amazonの登録テンプレート等）で振ったJANを台帳へ入れる。
  // 入れておかないと、次の発番が同じ番号から始まってぶつかる
  const [bulk, setBulk] = useState('')
  const [bulkOpen, setBulkOpen] = useState(false)
  const importBulk = async () => {
    if (!bulk.trim()) return
    setBusy(true); setErr('')
    try {
      const r = await api.post('/amazon-research/jan/import-bulk',
        { text: bulk })
      const d = r.data
      alert(`台帳に入れました：${d['入れた']}件`
        + `／すでにあった：${d['すでにあった']}件`
        + (d['読めなかった'].length
          ? `\n読めなかった行：\n${d['読めなかった'].join('\n')}` : '')
        + ((d['前のアカウントの番号'] || []).length
          ? '\n\n前のAmazonアカウントで使った番号なので入れませんでした'
            + `（GS1に別商品として登録されています）：\n`
            + d['前のアカウントの番号'].join('\n') : ''))
      setBulk('')
      await load()
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  // スプレッドシートで直接登録した商品は、出品フローを通らないので
  // 商品マスタに行ができない。Excelから作る・直す
  const [impMsg, setImpMsg] = useState('')
  const importMaster = async (fileList) => {
    const files = [...(fileList || [])]
    if (!files.length) return
    setBusy(true); setErr(''); setImpMsg('読み込んでいます…')
    try {
      const fd = new FormData()
      files.forEach(f => fd.append('files', f))
      const r = await api.post('/amazon-listings/master/import-excel', fd,
        { headers: { 'Content-Type': 'multipart/form-data' } })
      const d = r.data
      setImpMsg(`商品マスタに作った ${d['作った'].length}件`
        + ` / 直した ${d['直した'].length}件`
        + (d['読めなかった'].length
          ? `\n読めなかった：${d['読めなかった'].join(' / ')}` : ''))
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
      setImpMsg('')
    } finally { setBusy(false) }
  }

  const gs1Export = async () => {
    setBusy(true); setErr('')
    try {
      const r = await api.get('/amazon-research/jan/gs1-export',
        { responseType: 'blob' })
      const url = URL.createObjectURL(r.data)
      const a = document.createElement('a')
      a.href = url
      a.download = `gs1_${new Date().toISOString().slice(0, 10)}.xlsx`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  const gs1Done = async () => {
    if (!confirm(`未登録の${gs1.count}件に「GS1へ届け出済み」の印を付けます。`
      + 'よろしいですか？')) return
    setBusy(true); setErr('')
    try {
      await api.post('/amazon-research/jan/gs1-done', {})
      await load()
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  const start = async (researchId) => {
    setBusy(true); setErr('')
    try {
      const r = await api.post(`/amazon-listings/sync/${researchId}`)
      await load()
      setOpenId(r.data.id)
    } catch (e) {
      setErr(e.response?.data?.detail || e.message)
    } finally { setBusy(false) }
  }

  const shown = useMemo(
    () => {
      const base = onlyReady ? rows.filter(r => r.listing_id) : rows
      // SKU順。a019 → a016 → … → a01 と、数の大きいものが上。
      // 文字のまま並べると a1 < a10 < a2 になるので、数字は数として見る。
      // まだ採番していないものは、これからのものなので一番上に出す
      const key = (r) => (r.parent_sku || '').trim()
      const parts = (v) => (v.toLowerCase().match(/\d+|\D+/g) || [])
      return [...base].sort((a, b) => {
        const ka = key(a), kb = key(b)
        if (!ka && !kb) return 0
        if (!ka) return -1
        if (!kb) return 1
        const pa = parts(ka), pb = parts(kb)
        for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
          const x = pa[i], y = pb[i]
          if (x === undefined) return 1
          if (y === undefined) return -1
          const nx = /^\d+$/.test(x), ny = /^\d+$/.test(y)
          if (nx && ny) {
            if (Number(x) !== Number(y)) return Number(y) - Number(x)
          } else if (x !== y) {
            return x < y ? -1 : 1
          }
        }
        return 0
      })
    },
    [rows, onlyReady])

  if (openId) {
    return <ListingEditor listingId={openId}
      onBack={() => { setOpenId(null); load() }} />
  }

  return (
    <div style={{ overflow: 'auto', height: '100%', padding: 2, minWidth: 0 }}>
      {err && <Err text={err} />}

      <div style={{ ...card, marginBottom: 10, display: 'flex',
        alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 13 }}>
          採用したリサーチ <b>{rows.length}</b> 件 ／ 登録を始めたもの{' '}
          <b>{rows.filter(r => r.listing_id).length}</b> 件
        </div>
        <label style={{ fontSize: 12, color: C.sub, display: 'flex',
          alignItems: 'center', gap: 5 }}>
          <input type="checkbox" checked={onlyReady}
            onChange={e => setOnlyReady(e.target.checked)} />
          登録を始めたものだけ
        </label>
        <div style={{ marginLeft: 'auto', fontSize: 12, color: C.sub }}>
          粗利率は競合リサーチシートと同じ計算です
        </div>
      </div>

      {brand && (
        <div style={{ ...card, marginBottom: 10, background: '#f0fdf4',
          borderColor: '#86efac', display: 'flex', alignItems: 'center',
          gap: 10, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: '#166534' }}>
            🏷 ブランド
          </span>
          <input value={brand.name}
            placeholder="Aqualiora"
            onChange={e => setBrand({ ...brand, name: e.target.value })}
            style={{ ...input, width: 170, fontSize: 12, padding: '3px 6px' }} />
          <button className="btn btn-secondary" style={{ fontSize: 12 }}
            disabled={busy || !brand.name.trim()}
            onClick={() => saveBrand({ ...brand, name: brand.name.trim() })}>
            保存
          </button>
          <span style={{ fontSize: 11, color: C.sub, width: '100%' }}>
            これから出すものは「{brand.name.trim() || 'Aqualiora'}」で登録されます。
            商品ごとに別のブランドにしたいときだけ、その商品の「ブランド名」に入れてください
            （空ならここの値を使います）。
          </span>
        </div>
      )}

      {gs1 && gs1.count > 0 && (
        <div style={{ ...card, marginBottom: 10, background: '#fffbeb',
          borderColor: '#fde68a', display: 'flex', alignItems: 'center',
          gap: 10, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 13, color: '#92400e' }}>
            GS1へ未登録のJANが <b>{gs1.count}</b> 件あります
            （発番しただけでは登録されません）
          </span>
          <button className="btn btn-secondary" style={{ fontSize: 12 }}
            onClick={gs1Export} disabled={busy}>
            📄 一括登録フォームを書き出す
          </button>
          <button className="btn btn-secondary" style={{ fontSize: 12 }}
            onClick={gs1Done} disabled={busy}>
            ✅ 届け出済みにする
          </button>
          {/* 空のまま出る欄は商品の種類で決まるので、毎回ここで迷う。
              どこへ渡せば埋まるかまで書いておく */}
          <span style={{ fontSize: 11, color: C.sub, width: '100%',
            lineHeight: 1.7 }}>
            カナ・取扱品目コード・JICFS分類・GPC分類・内容量は商品ごとに違うので
            空のまま出ます。<b>書き出したファイルをそのままクロコに渡せば、
            空いている欄を埋めて返してくれます。</b>
            埋まったファイルをGS1の画面へ上げてください。
          </span>
        </div>
      )}

      {/* スプレッドシートで直接登録した商品を商品マスタへ入れる口。
          入れておかないと、その商品だけ発注・在庫から外れる */}
      <div className="card" style={{ marginBottom: 10 }}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center',
          flexWrap: 'wrap' }}>
          <span style={{ fontSize: 13 }}>
            📥 Amazonの登録Excelから商品マスタを作る・直す
          </span>
          <input type="file" accept=".xlsm,.xlsx" multiple disabled={busy}
            onChange={e => { importMaster(e.target.files); e.target.value = '' }}
            style={{ fontSize: 12 }} />
        </div>
        <div style={{ fontSize: 11, color: C.sub, marginTop: 6,
          lineHeight: 1.7 }}>
          スプレッドシートで直接登録した商品は、ツールの出品フローを
          通らないので商品マスタに入りません。そのExcelをそのまま選べば、
          SKU・商品名・色・販売価格を入れます。
          <b>すでにある商品は、古い名前を上書きします。</b>
          仕入URL・原価・入数など、こちらでしか持っていない情報は触りません。
        </div>
        {impMsg && (
          <div style={{ fontSize: 12, color: C.text, marginTop: 6,
            whiteSpace: 'pre-wrap' }}>{impMsg}</div>
        )}
      </div>

      {/* ツールの外で振ったJANを台帳へ入れる口。入れておかないと、
          次の発番が同じ番号から始まってぶつかる */}
      {!gs1 ? null : (
        <div className="card" style={{ marginBottom: 10 }}>
          <button className="btn btn-sm btn-secondary" style={{ fontSize: 12 }}
            onClick={() => setBulkOpen(v => !v)}>
            {bulkOpen ? '閉じる' : '🔢 外で振ったJANを台帳に入れる'}
          </button>
          {bulkOpen && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: 11, color: C.sub, marginBottom: 6,
                lineHeight: 1.7 }}>
                1行に「JAN（タブ）SKU（タブ）商品名」。SKUと商品名は省けます。
                Amazonの登録テンプレートに直接書いた番号など、ツールの外で
                使った番号をここに入れておくと、次の発番がぶつかりません。
              </div>
              <textarea value={bulk} onChange={e => setBulk(e.target.value)}
                rows={6} placeholder={'4573603981268\ta01\t観葉植物パキラ'}
                style={{ width: '100%', fontSize: 12,
                  fontFamily: 'monospace' }} />
              <button className="btn btn-primary" style={{ fontSize: 12,
                marginTop: 6 }} onClick={importBulk} disabled={busy}>
                台帳に入れる
              </button>
            </div>
          )}
        </div>
      )}

      <div style={{ display: 'grid', gap: 8 }}>
        {shown.map(r => (
          <ListRow key={r.research_id} r={r} busy={busy}
            onStart={() => start(r.research_id)}
            onOpen={() => setOpenId(r.listing_id)} />
        ))}
        {!shown.length && (
          <div style={{ ...card, color: C.sub, fontSize: 13, lineHeight: 1.7 }}>
            出せるリサーチがありません。<br />
            リサーチシートで枠の状態を<b>「採用」</b>にすると、ここに出てきます
            （採用・発注済み・画像依頼済み・商品登録済みが対象です）。
          </div>
        )}
      </div>
    </div>
  )
}

function Err({ text }) {
  return (
    <div style={{ background: '#fef2f2', border: '1px solid #fecaca',
      color: '#991b1b', padding: 10, borderRadius: 6, marginBottom: 10,
      fontSize: 13, whiteSpace: 'pre-wrap' }}>{text}</div>
  )
}

/** 一覧の1行。リサーチの判断根拠と、原稿の仕上がり具合を出す */
function ListRow({ r, onStart, onOpen, busy }) {
  const done = !!r.listing_id
  const st = {
    draft: { l: '下書き', c: C.sub },
    prepared: { l: '準備済み', c: C.key },
    ready: { l: '出品待ち', c: C.key },
    submitted: { l: '送信済み', c: C.good },
    live: { l: '公開中', c: C.good },
    failed: { l: '失敗', c: C.bad },
  }[r.listing_status] || null

  return (
    <div style={{ ...card, display: 'flex', gap: 12, alignItems: 'flex-start' }}>
      {r.rival_image
        ? <img src={r.rival_image} alt="" style={{ width: 56, height: 56,
            objectFit: 'contain', border: `1px solid ${C.line}`, borderRadius: 6,
            flexShrink: 0, background: '#fff' }} />
        : <div style={{ width: 56, height: 56, border: `1px dashed ${C.line}`,
            borderRadius: 6, flexShrink: 0 }} />}

      <div style={{ flex: 1, minWidth: 0 }}>
        {/* 主役は自社の情報。SKUと商品名が一目で分かるようにする */}
        <div style={{ display: 'flex', gap: 8, alignItems: 'baseline',
          flexWrap: 'wrap' }}>
          <span style={{ fontFamily: 'monospace', fontSize: 14,
            fontWeight: 700, color: r.parent_sku ? C.key : C.sub }}>
            {r.parent_sku || 'SKU未採番'}
          </span>
          <span style={{ fontSize: 13, fontWeight: 600, color: C.text,
            whiteSpace: 'nowrap', overflow: 'hidden',
            textOverflow: 'ellipsis', maxWidth: 520 }}
            title={r.own_title || r.research_title}>
            {r.own_title || r.research_title || '(名前なし)'}
          </span>
        </div>

        {/* 子SKUと、出品後に付いた自社ASIN */}
        {(r.skus?.length > 0 || r.asins?.length > 0) && (
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap',
            fontSize: 11, color: C.sub, marginTop: 3 }}>
            {r.skus?.length > 0 && (
              <span style={{ fontFamily: 'monospace' }}>
                SKU {r.skus.slice(0, 3).join(' / ')}
                {r.skus.length > 3 ? ` ほか${r.skus.length - 3}` : ''}
              </span>
            )}
            {r.asins?.length > 0 && (
              <span style={{ fontFamily: 'monospace', color: C.good,
                fontWeight: 600 }}>
                ASIN {r.asins.slice(0, 3).join(' / ')}
                {r.asins.length > 3 ? ` ほか${r.asins.length - 3}` : ''}
              </span>
            )}
          </div>
        )}

        <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap',
          fontSize: 12, color: C.sub, marginTop: 5 }}>
          {/* ここから下は競合の数字。判断材料として小さく残す */}
          <span>競合ASIN{' '}
            {r.rival_asin
              ? <a href={`https://www.amazon.co.jp/dp/${r.rival_asin}`}
                  target="_blank" rel="noreferrer"
                  style={{ fontWeight: 700 }}>{r.rival_asin}</a>
              : <b style={{ color: C.sub }}>—</b>}
          </span>
          {r.urls_1688?.length > 0 && (
            <span>仕入元{' '}
              {r.urls_1688.slice(0, 3).map((u, i) => (
                <a key={i} href={u} target="_blank" rel="noreferrer"
                  style={{ fontWeight: 700, marginRight: 6 }}>
                  1688{r.urls_1688.length > 1 ? `(${i + 1})` : ''}
                </a>
              ))}
            </span>
          )}
          <span>月間 <b style={{ color: C.text }}>{r.monthly_sales ?? '—'}</b>個</span>
          <span>レビュー <b style={{ color: C.text }}>{r.review_count ?? '—'}</b>件
            {r.review_rate ? ` ★${r.review_rate}` : ''}</span>
          <span>売価 <b style={{ color: C.text }}>
            {r.price ? `¥${r.price.toLocaleString()}` : '—'}</b></span>
          <span>粗利率 <b style={{
            color: r.profit_rate == null ? C.sub
              : r.profit_rate >= 30 ? C.good
                : r.profit_rate >= 20 ? C.warn : C.bad,
          }}>{r.profit_rate == null ? '—' : `${r.profit_rate}%`}</b>
            {r.cost_missing?.length
              ? <span style={{ color: C.warn }}>（{r.cost_missing.join('・')}が未入力）</span>
              : null}
          </span>
        </div>

        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 6 }}>
          <Chip on={r.has_title} label="タイトル" />
          <Chip on={r.has_keywords} label="検索KW" />
          <Chip on={r.bullet_count > 0} label={`要点${r.bullet_count || 0}行`} />
          {r.child_count > 0 &&
            <Chip on label={`バリエーション${r.child_count}`} />}
          {r.status_label && (
            <span style={{ fontSize: 11, color: '#2563eb', fontWeight: 600,
              padding: '2px 8px', border: '1px solid #bfdbfe',
              background: '#eff6ff', borderRadius: 10 }}>
              {r.status_label}
            </span>
          )}
          {st && <span style={{ fontSize: 11, color: st.c, fontWeight: 600,
            padding: '2px 8px', border: `1px solid ${st.c}`, borderRadius: 10 }}>
            {st.l}</span>}
        </div>
      </div>

      <button className={`btn ${done ? 'btn-primary' : 'btn-secondary'}`}
        disabled={busy} onClick={done ? onOpen : onStart}
        style={{ flexShrink: 0, whiteSpace: 'nowrap' }}>
        {done ? '開く' : '登録を始める'}
      </button>
    </div>
  )
}

function Chip({ on, label }) {
  return (
    <span style={{
      fontSize: 11, padding: '2px 7px', borderRadius: 10,
      background: on ? '#ecfdf5' : C.soft,
      color: on ? C.good : C.sub,
      border: `1px solid ${on ? '#a7f3d0' : C.line}`,
    }}>{on ? '✓' : '—'} {label}</span>
  )
}

export { C, card, label, input, bytes, Err }
