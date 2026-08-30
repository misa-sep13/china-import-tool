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
  // 中のスクリプトはこれを見て保存先とAPIの向き先を決める。
  //
  // onLoadでは遅い（中のスクリプトが先に走ってしまう）ので、
  // srcを付ける前の空のiframeに書き込んでおく。about:blank の段階なら
  // 同一オリジンとして触れるため、この順番なら確実に間に合う。
  const injectConfig = () => {
    // 親側にも置く。iframeへ直接書いた値は、srcを入れた瞬間の
    // ナビゲーションで消えてしまうため、中のスクリプトは親を見に来る。
    window.__ARS_API__ = api.defaults.baseURL || ''
    window.__ARS_TOKEN__ = localStorage.getItem('auth_token') || ''
    const win = frameRef.current?.contentWindow
    if (!win) return
    try {
      win.__ARS_API__ = window.__ARS_API__
      win.__ARS_TOKEN__ = window.__ARS_TOKEN__
    } catch {
      /* 別オリジンなら触れないが、同じサイトから配信しているので通常は通る */
    }
  }

  const V = __BUILD_ID__
  const sheetUrl = `${import.meta.env.BASE_URL}research/sheet.html?v=${V}`
  const scoutUrl = `${import.meta.env.BASE_URL}research/scout.html?v=${V}`
  const url = tab === 'sheet' ? sheetUrl : scoutUrl

  // srcを空にしておき、設定を書き込んでから読み込ませる
  useEffect(() => {
    const f = frameRef.current
    if (!f) return
    setReady(false)
    injectConfig()
    f.src = url
  }, [url])

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
        <a className="btn btn-secondary" href={url} target="_blank" rel="noreferrer"
          style={{ marginLeft: 'auto', textDecoration: 'none' }}>
          新しいタブで開く
        </a>
      </div>

      {/* どちらも配布版のHTMLをそのまま使う。作り直すと見た目も機能も変わるため。
          保存先とAPIの向き先だけ、埋め込み側から差し替えている */}
      <div style={{
        flex: 1, minHeight: 0, border: '1px solid #e5e7eb',
        borderRadius: 8, overflow: 'hidden', background: '#fff',
      }}>
        <iframe
          key={tab}
          ref={frameRef}
          title={tab === 'sheet' ? '競合リサーチシート' : 'セラースカウト'}
          style={{ width: '100%', height: '100%', border: 'none', display: 'block' }}
          onLoad={() => { injectConfig(); setReady(true) }}
        />
      </div>
    </div>
  )
}
