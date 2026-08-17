import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000/api',
})

// ログインが有効な間だけトークンを付与する。未設定時は何もしない
// （認証が無効化されている今までどおりの運用のときはヘッダーなしで通る）。
api.interceptors.request.use(config => {
  const token = localStorage.getItem('auth_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// 401が返ってきたらトークンが無効（未ログイン/期限切れ）なのでログイン画面へ。
// 就労支援の公開ページ(/welfare/work-public)はログイン不要のページなので対象外。
api.interceptors.response.use(
  res => res,
  err => {
    const isLoginCall = err.config?.url?.includes('/auth/login')
    if (err.response?.status === 401 && !isLoginCall && window.location.pathname !== '/welfare/work-public') {
      localStorage.removeItem('auth_token')
      localStorage.removeItem('auth_role')
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login'
      }
    }
    return Promise.reject(err)
  }
)

export default api
