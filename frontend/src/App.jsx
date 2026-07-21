import { Routes, Route, NavLink, useLocation } from 'react-router-dom'
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
import RakutenDailySalesPage from './pages/RakutenDailySalesPage'
import AdsPage from './pages/AdsPage'
import InventoryReflectionLogsPage from './pages/InventoryReflectionLogsPage'
import WelfareInventoryPage from './pages/WelfareInventoryPage'
import WelfareWorkPublicPage from './pages/WelfareWorkPublicPage'
import './App.css'

function App() {
  const location = useLocation()
  if (location.pathname === '/welfare/work-public') {
    return (
      <Routes>
        <Route path="/welfare/work-public" element={<WelfareWorkPublicPage />} />
      </Routes>
    )
  }

  return (
    <div className="app">
      <nav className="sidebar">
        <div className="sidebar-title">🇨🇳 中国輸入管理</div>
        <NavLink to="/" end className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
          📦 発注管理
        </NavLink>
        <NavLink to="/stock" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
          📊 全在庫一覧
        </NavLink>
        <NavLink to="/analytics" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
          📈 商品分析
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
        <NavLink to="/settings" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
          ⚙️ 設定
        </NavLink>

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
        <NavLink to="/rakuten/settings" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
          ⚙️ 楽天設定
        </NavLink>
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
        <div style={{ borderTop: '1px solid #2d3748', margin: '16px 0 8px', paddingTop: 8, fontSize: 11, color: '#475569', fontWeight: 700, letterSpacing: 1, paddingLeft: 16 }}>
          就労支援
        </div>
        <NavLink to="/welfare/inventory" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
          📦 就労支援在庫
        </NavLink>
      </nav>
      <main className="main-content">
        <Routes>
          <Route path="/" element={<OrderPage />} />
          <Route path="/stock" element={<StockPage />} />
          <Route path="/analytics" element={<AnalyticsPage />} />
          <Route path="/ads" element={<AdsPage />} />
          <Route path="/products" element={<ProductsPage />} />
          <Route path="/invoices" element={<InvoicePage />} />
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
          <Route path="/welfare/inventory" element={<WelfareInventoryPage />} />
          <Route path="/welfare/work-public" element={<WelfareWorkPublicPage />} />
        </Routes>
      </main>
    </div>
  )
}

export default App
