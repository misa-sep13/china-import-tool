import { Routes, Route, NavLink } from 'react-router-dom'
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
import './App.css'

function App() {
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
          🛒 発注管理
        </NavLink>
        <NavLink to="/rakuten/stock" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
          📦 在庫・損益
        </NavLink>
        <NavLink to="/rakuten/products" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
          🏷️ 商品マスタ
        </NavLink>
        <NavLink to="/rakuten/settings" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
          ⚙️ 楽天設定
        </NavLink>
      </nav>
      <main className="main-content">
        <Routes>
          <Route path="/" element={<OrderPage />} />
          <Route path="/stock" element={<StockPage />} />
          <Route path="/analytics" element={<AnalyticsPage />} />
          <Route path="/products" element={<ProductsPage />} />
          <Route path="/invoices" element={<InvoicePage />} />
          <Route path="/price-adjust" element={<PriceAdjustPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/rakuten/orders" element={<RakutenOrderPage />} />
          <Route path="/rakuten/stock" element={<RakutenStockPage />} />
          <Route path="/rakuten/products" element={<RakutenProductsPage />} />
          <Route path="/rakuten/settings" element={<RakutenSettingsPage />} />
        </Routes>
      </main>
    </div>
  )
}

export default App
