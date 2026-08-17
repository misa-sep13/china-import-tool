import { useState } from 'react'
import api from '../api/client'

export default function LoginPage({ onLoggedIn }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [bookmarkUrl, setBookmarkUrl] = useState(null)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await api.post('/auth/login', { username: username.trim(), password })
      localStorage.setItem('auth_token', res.data.token)
      localStorage.setItem('auth_role', res.data.role)
      // 次回から二度と入力しなくていいように、トークン入りのURLを見せる。
      // これをブックマークしておけば、そのリンクを開くだけで自動的にログインされる。
      const url = new URL(window.location.origin + window.location.pathname)
      url.searchParams.set('auth', res.data.token)
      setBookmarkUrl(url.toString())
    } catch (err) {
      setError(err.response?.data?.detail || 'ログインに失敗しました')
    } finally {
      setLoading(false)
    }
  }

  if (bookmarkUrl) {
    return (
      <div style={{
        minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: '#0f1729', padding: 16,
      }}>
        <div className="card" style={{ width: 480, maxWidth: '100%', padding: 28 }}>
          <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 8 }}>✅ ログインしました</div>
          <p style={{ fontSize: 13, color: '#475569', lineHeight: 1.6, marginBottom: 12 }}>
            下のリンクを<b>ブックマークして</b>ください。次回からはこのブックマークを開くだけで、
            パスワードを入力せずそのまま使えます（このブラウザ限定）。
          </p>
          <div style={{
            fontSize: 12, fontFamily: 'monospace', background: '#f1f5f9', border: '1px solid #e2e8f0',
            borderRadius: 6, padding: 10, wordBreak: 'break-all', marginBottom: 12,
          }}>
            {bookmarkUrl}
          </div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
            <button
              className="btn btn-secondary"
              onClick={() => navigator.clipboard?.writeText(bookmarkUrl)}
            >
              リンクをコピー
            </button>
            <a href={bookmarkUrl} className="btn btn-primary" style={{ textDecoration: 'none' }}>
              このリンクを開く
            </a>
          </div>
          <p style={{ fontSize: 11, color: '#94a3b8' }}>
            ※他人に共有しないでください。このリンクを知っていれば誰でもログインできます。
          </p>
        </div>
      </div>
    )
  }

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: '#0f1729',
    }}>
      <form onSubmit={handleSubmit} className="card" style={{ width: 320, padding: 28 }}>
        <div style={{ fontSize: 20, fontWeight: 700, marginBottom: 4 }}>🇨🇳 中国輸入管理</div>
        <div style={{ fontSize: 13, color: '#64748b', marginBottom: 20 }}>ログインしてください</div>
        <div className="form-group">
          <label>ユーザー名</label>
          <input value={username} onChange={e => setUsername(e.target.value)} autoFocus />
        </div>
        <div className="form-group" style={{ marginTop: 10 }}>
          <label>パスワード</label>
          <input type="password" value={password} onChange={e => setPassword(e.target.value)} />
        </div>
        {error && <p className="error-msg" style={{ marginTop: 10 }}>{error}</p>}
        <button className="btn btn-primary" type="submit" disabled={loading} style={{ width: '100%', marginTop: 16 }}>
          {loading ? 'ログイン中...' : 'ログイン'}
        </button>
      </form>
    </div>
  )
}
