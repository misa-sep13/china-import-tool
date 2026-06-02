import { Routes, Route, NavLink } from 'react-router-dom'
import OrderPage from './pages/OrderPage'
import ProductsPage from './pages/ProductsPage'
import SettingsPage from './pages/SettingsPage'
import './App.css'

function App() {
  return (
    <div className="app">
      <nav className="sidebar">
        <div className="sidebar-title">🇨🇳 中国輸入管理</div>
        <NavLink to="/" end className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
          📦 発注管理
        </NavLink>
        <NavLink to="/products" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
          🏷️ 商品マスタ
        </NavLink>
        <NavLink to="/settings" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
          ⚙️ 設定
        </NavLink>
      </nav>
      <main className="main-content">
        <Routes>
          <Route path="/" element={<OrderPage />} />
          <Route path="/products" element={<ProductsPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </div>
  )
}

export default App
