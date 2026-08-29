import { useEffect, useState } from 'react'
import { Routes, Route, Navigate, NavLink, useLocation } from 'react-router-dom'
import api from './api/client'
import OrderPage from './pages/OrderPage'
import ProductsPage from './pages/ProductsPage'
import SettingsPage from './pages/SettingsPage'
import InvoicePage from './pages/InvoicePage'
import PriceAdjustPage from './pages/PriceAdjustPage'
import StockPage from './pages/StockPage'
import AnalyticsPage from './pages/AnalyticsPage'
import RakutenOrderPage from './pages/RakutenOrderPage'
import RakutenProductsPage from './pages/RakutenProductsPage'
import RakutenStockPage from './pages/RakutenStockPage'
import RakutenSettingsPage from './pages/RakutenSettingsPage'
import RakutenInvoicePage from './pages/RakutenInvoicePage'
import RakutenSalesPage from './pages/RakutenSalesPage'
import RakutenReviewPage from './pages/RakutenReviewPage'
import KeywordAnalysisPage from './pages/KeywordAnalysisPage'
import SeoPage from './pages/SeoPage'
import RakutenResearchPage from './pages/RakutenResearchPage'
import ResearchPage from './pages/ResearchPage'
import RakutenDailySalesPage from './pages/RakutenDailySalesPage'
import AdsPage from './pages/AdsPage'
import InventoryReflectionLogsPage from './pages/InventoryReflectionLogsPage'
import WelfareInventoryPage from './pages/WelfareInventoryPage'
import WelfareWorkPublicPage from './pages/WelfareWorkPublicPage'
import FbaPlanPage from './pages/FbaPlanPage'
import LoginPage from './pages/LoginPage'
import ActivityHistoryPanel from './components/ActivityHistoryPanel'
import './App.css'

// 外注さんには見せない（APIキー等が見える設定画面）。
// バックエンド側でもAPI自体を403で弾いているので、ここはUI上の導線を隠す・
// URL直打ちでの表示だけを防ぐための二重の壁。
const OWNER_ONLY_PATHS = ['/settings', '/rakuten/settings']

function App() {
  const location = useLocation()

  const [authEnabled, setAuthEnabled] = useState(null) // null=判定中
  const [role, setRole] = useState(() => localStorage.getItem('auth_role'))
  const [historyOpen, setHistoryOpen] = useState(false)

  // ブックマークされたマジックリンク（?auth=トークン）を検出したら、
  // ログイン画面を出さずにそのままトークンを保存してURLから消す。
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const token = params.get('auth')
    if (!token) return
    let tokenRole = null
    try {
      const payload = token.split('.')[0]
      const padded = payload + '='.repeat((4 - (payload.length % 4)) % 4)
      tokenRole = JSON.parse(atob(padded.replace(/-/g, '+').replace(/_/g, '/'))).role
    } catch {
      // デコードに失敗してもトークン自体はサーバー側で検証されるので保存だけしておく
    }
    localStorage.setItem('auth_token', token)
    if (tokenRole) localStorage.setItem('auth_role', tokenRole)
    setRole(tokenRole || localStorage.getItem('auth_role'))
    params.delete('auth')
    const newSearch = params.toString()
    window.history.replaceState({}, '', window.location.pathname + (newSearch ? `?${newSearch}` : ''))
  }, [])

  useEffect(() => {
    api.get('/auth/status')
      .then(r => setAuthEnabled(!!r.data.auth_enabled))
      .catch(() => setAuthEnabled(false)) // 判定できない場合は今までどおり無認証扱い
  }, [])

  // 就労支援の公開ページはログイン不要（施設の作業者が見るページ）
  if (location.pathname === '/welfare/work-public') {
    return (
      <Routes>
        <Route path="/welfare/work-public" element={<WelfareWorkPublicPage />} />
      </Routes>
    )
  }

  if (authEnabled === null) {
    return <div style={{ padding: 40, color: '#64748b' }}>読み込み中...</div>
  }

  const isLoggedIn = !!localStorage.getItem('auth_token')
  if (authEnabled && !isLoggedIn) {
    return <LoginPage onLoggedIn={(r) => { setRole(r); window.location.href = '/' }} />
  }

  const isContractor = authEnabled && role === 'contractor'
  if (isContractor && OWNER_ONLY_PATHS.includes(location.pathname)) {
    return <Navigate to="/" replace />
  }

  const handleLogout = () => {
    localStorage.removeItem('auth_token')
    localStorage.removeItem('auth_role')
    window.location.href = '/'
  }

  return (
    <div className="app">
      <nav className="sidebar">
        <div
          className="sidebar-title"
          style={{ cursor: 'pointer' }}
          title="クリックで更新履歴を表示"
          onClick={() => setHistoryOpen(true)}
        >
          🇨🇳 中国輸入管理
        </div>
        <NavLink to="/" end className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
          📦 発注管理
        </NavLink>
        <NavLink to="/fba-plan" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
          🚢 納品プラン
        </NavLink>
        <NavLink to="/stock" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
          📊 全在庫一覧
        </NavLink>
        <NavLink to="/analytics" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
          📈 商品分析
        </NavLink>
        <NavLink to="/research" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
          🔍 競合リサーチ
        </NavLink>
        <NavLink to="/ads" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
          📢 広告管理
        </NavLink>
        <NavLink to="/products" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
          🏷️ 商品マスタ
        </NavLink>
        <NavLink to="/invoices" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
          📄 仕入管理
        </NavLink>
        <NavLink to="/price-adjust" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
          💹 価格調整
        </NavLink>
        {!isContractor && (
          <NavLink to="/settings" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
            ⚙️ 設定
          </NavLink>
        )}

        {/* 楽天セクション */}
        <div style={{ borderTop: '1px solid #2d3748', margin: '16px 0 8px', paddingTop: 8, fontSize: 11, color: '#475569', fontWeight: 700, letterSpacing: 1, paddingLeft: 16 }}>
          楽天市場
        </div>
        <NavLink to="/rakuten/orders" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
          📦 発注管理
        </NavLink>
        <NavLink to="/rakuten/stock" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
          📊 在庫・損益
        </NavLink>
        <NavLink to="/rakuten/sales" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
          📈 売上管理
        </NavLink>
        <NavLink to="/rakuten/daily-sales" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
          📊 日別販売数
        </NavLink>
        <NavLink to="/rakuten/products" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
          🏷️ 商品マスタ
        </NavLink>
        <NavLink to="/rakuten/invoices" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
          📄 仕入管理
        </NavLink>
        {!isContractor && (
          <NavLink to="/rakuten/settings" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
            ⚙️ 楽天設定
          </NavLink>
        )}
        <NavLink to="/rakuten/inventory-reflections" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
          📥 在庫反映履歴
        </NavLink>
        <NavLink to="/rakuten/review" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
          🎁 レビューキャンペーン
        </NavLink>
        <NavLink to="/rakuten/keyword-analysis" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
          🔍 キーワード分析
        </NavLink>
        <NavLink to="/rakuten/seo" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
          📊 SEO順位
        </NavLink>
        <NavLink to="/rakuten/research" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
          🔎 商品リサーチ
        </NavLink>
        <div style={{ borderTop: '1px solid #2d3748', margin: '16px 0 8px', paddingTop: 8, fontSize: 11, color: '#475569', fontWeight: 700, letterSpacing: 1, paddingLeft: 16 }}>
          就労支援
        </div>
        <NavLink to="/welfare/inventory" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
          📦 就労支援在庫
        </NavLink>

        {authEnabled && (
          <div style={{ marginTop: 'auto', paddingTop: 16, borderTop: '1px solid #2d3748' }}>
            <div style={{ fontSize: 11, color: '#64748b', padding: '4px 16px' }}>
              {role === 'contractor' ? '外注さんとしてログイン中' : 'オーナーとしてログイン中'}
            </div>
            <button
              onClick={handleLogout}
              className="nav-item"
              style={{ background: 'none', border: 'none', width: '100%', textAlign: 'left', cursor: 'pointer' }}
            >
              🚪 ログアウト
            </button>
          </div>
        )}
      </nav>
      <main className="main-content">
        <Routes>
          <Route path="/" element={<OrderPage />} />
          <Route path="/stock" element={<StockPage />} />
          <Route path="/analytics" element={<AnalyticsPage />} />
          <Route path="/ads" element={<AdsPage />} />
          <Route path="/products" element={<ProductsPage />} />
          <Route path="/invoices" element={<InvoicePage />} />
          <Route path="/fba-plan" element={<FbaPlanPage />} />
          <Route path="/price-adjust" element={<PriceAdjustPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/rakuten/orders" element={<RakutenOrderPage />} />
          <Route path="/rakuten/stock" element={<RakutenStockPage />} />
          <Route path="/rakuten/sales" element={<RakutenSalesPage />} />
          <Route path="/rakuten/daily-sales" element={<RakutenDailySalesPage />} />
          <Route path="/rakuten/products" element={<RakutenProductsPage />} />
          <Route path="/rakuten/invoices" element={<RakutenInvoicePage />} />
          <Route path="/rakuten/settings" element={<RakutenSettingsPage />} />
          <Route path="/rakuten/inventory-reflections" element={<InventoryReflectionLogsPage />} />
          <Route path="/rakuten/review" element={<RakutenReviewPage />} />
          <Route path="/rakuten/keyword-analysis" element={<KeywordAnalysisPage />} />
          <Route path="/rakuten/seo" element={<SeoPage />} />
          <Route path="/research" element={<ResearchPage />} />
          <Route path="/rakuten/research" element={<RakutenResearchPage />} />
          <Route path="/welfare/inventory" element={<WelfareInventoryPage />} />
          <Route path="/welfare/work-public" element={<WelfareWorkPublicPage />} />
        </Routes>
      </main>
      <ActivityHistoryPanel open={historyOpen} onClose={() => setHistoryOpen(false)} />
    </div>
  )
}

export default App
