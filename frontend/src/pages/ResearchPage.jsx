import { useEffect, useRef, useState } from 'react'
import api from '../api/client'

/**
 * リサーチ（競合リサーチシート ／ セラースカウト）。
 *
 * 競合リサーチシートは、もらったHTML1枚をそのまま iframe で表示している。
 * 見た目も機能も配布版と完全に同じにするため作り直していない。
 * 保存先だけ localStorage から一元管理のサーバーへ差し替えてあり、
 * APIのURLとトークンを window.__ARS_API__ / __ARS_TOKEN__ で渡している。
 */
export default function ResearchPage() {
  const [tab, setTab] = useState('sheet')
  const frameRef = useRef(null)
  const [ready, setReady] = useState(false)

  // iframeの中へ、APIのURLとログイン済みトークンを渡す。
  // シート側はこれがあるときだけサーバーへ保存する（無ければ手元保存のまま動く）
  const injectConfig = () => {
    const win = frameRef.current?.contentWindow
    if (!win) return
    try {
      win.__ARS_API__ = api.defaults.baseURL || ''
      const t = localStorage.getItem('auth_token') || ''
      win.__ARS_TOKEN__ = t
    } catch {
      /* 別オリジンなら触れないが、同じサイトから配信しているので通常は通る */
    }
  }

  useEffect(() => { setReady(false) }, [tab])

  const sheetUrl = `${import.meta.env.BASE_URL}research/sheet.html`

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 40px)' }}>
      <div style={{ display: 'flex', gap: 8, marginBottom: 10, flexShrink: 0 }}>
        {[
          { k: 'sheet', l: '📋 競合リサーチシート' },
          { k: 'scout', l: '🔎 セラースカウト' },
        ].map(t => (
          <button key={t.k} onClick={() => setTab(t.k)}
            className={`btn ${tab === t.k ? 'btn-primary' : 'btn-secondary'}`}>
            {t.l}
          </button>
        ))}
        {tab === 'sheet' && (
          <a className="btn btn-secondary" href={sheetUrl} target="_blank" rel="noreferrer"
            style={{ marginLeft: 'auto', textDecoration: 'none' }}>
            新しいタブで開く
          </a>
        )}
      </div>

      {tab === 'sheet' ? (
        <div style={{
          flex: 1, minHeight: 0, border: '1px solid #e5e7eb',
          borderRadius: 8, overflow: 'hidden', background: '#fff',
        }}>
          <iframe
            ref={frameRef}
            src={sheetUrl}
            title="競合リサーチシート"
            style={{ width: '100%', height: '100%', border: 'none', display: 'block' }}
            onLoad={() => { injectConfig(); setReady(true) }}
          />
          {!ready && (
            <div style={{ padding: 40, textAlign: 'center', color: '#9ca3af' }}>
              読み込み中...
            </div>
          )}
        </div>
      ) : (
        <ScoutPanel />
      )}
    </div>
  )
}

/**
 * セラースカウト。巡回そのものは手元のPCで動かす（Amazonはデータセンターの
 * IPからだと即ブロックされるため、SEO順位チェックと同じ考え方）。
 * ここでは巡回結果を見て、リサーチシートへ送る。
 */
function ScoutPanel() {
  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}>セラースカウト</h3>
      <p style={{ color: '#64748b', fontSize: 13 }}>
        登録したセラーのストアフロントを巡回し、「過去1か月で〇〇点以上購入されました」
        バッジを集めます。SP-APIでは取れない月間販売数がここで手に入ります。
      </p>
      <div style={{
        padding: 16, borderRadius: 8, background: '#fffbeb',
        border: '1px solid #fcd34d', color: '#92400e', fontSize: 13,
      }}>
        <b>準備中です。</b>
        <div style={{ marginTop: 6 }}>
          巡回はブラウザを自動操縦するため、サーバー上では動きません
          （データセンターのIPからだと弾かれます）。
          SEO順位チェックと同じく「手元のPCで巡回 → 結果をサーバーへ送る」形にします。
        </div>
      </div>
    </div>
  )
}
