import React from 'react'
import ReactDOM from 'react-dom/client'
import { HashRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App.jsx'
import ErrorBoundary from './components/ErrorBoundary.jsx'
import './index.css'

// 既定のままだと、画面を切り替えるたび・ウィンドウに戻るたびに
// すべての一覧を取り直す。楽天の商品マスタだけで342KBあり、
// これがSupabaseの通信量を押し上げていた。
// 1分以内の取り直しはやめ、ウィンドウに戻っただけでは取り直さない。
// 保存や取り込みのあとは invalidateQueries で明示的に取り直しているので、
// 新しくしたはずの数字が古いまま、ということにはならない。
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      refetchOnWindowFocus: false,
    },
  },
})

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <HashRouter>
          <App />
        </HashRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  </React.StrictMode>
)
