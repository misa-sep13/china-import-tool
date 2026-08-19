import { Component } from 'react'

// 画面の一部でエラーが起きたとき、アプリ全体が真っ白になるのを防ぐ。
// React はレンダー中の例外を捕まえないと、ツリーごとアンマウントして
// 何も表示しなくなる（原因もその場では分からない）ため、ここで受け止める。
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    console.error('画面の描画中にエラーが発生しました:', error, info)
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 40, textAlign: 'center', color: '#374151' }}>
          <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 8 }}>⚠ 画面の表示中にエラーが発生しました</div>
          <div style={{ fontSize: 13, color: '#6b7280', marginBottom: 16 }}>
            {this.state.error.message || String(this.state.error)}
          </div>
          <button
            onClick={() => window.location.reload()}
            style={{ background: '#2563eb', color: '#fff', border: 'none', borderRadius: 6, padding: '8px 20px', cursor: 'pointer', fontWeight: 600 }}
          >
            再読み込み
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
