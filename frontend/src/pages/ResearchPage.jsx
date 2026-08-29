import { useEffect, useRef, useState } from 'react'
import api from '../api/client'
import ScoutPanel from '../components/ScoutPanel'

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
