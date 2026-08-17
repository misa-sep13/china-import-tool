import { useState } from 'react'
import api from '../api/client'

export default function LoginPage({ onLoggedIn }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await api.post('/auth/login', { username: username.trim(), password })
      localStorage.setItem('auth_token', res.data.token)
      localStorage.setItem('auth_role', res.data.role)
      onLoggedIn(res.data.role)
    } catch (err) {
      setError(err.response?.data?.detail || 'ログインに失敗しました')
    } finally {
      setLoading(false)
    }
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
