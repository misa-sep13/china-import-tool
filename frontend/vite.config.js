import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/china-import-tool/',
  define: {
    // research/ 配下の配布版HTMLはビルドの成果物ではないのでハッシュが
    // 付かず、中身を直してもブラウザが古いものを掴み続ける。
    // ビルドごとに変わる値を埋め込み側から付けて、更新を確実に届ける。
    __BUILD_ID__: JSON.stringify(String(Date.now())),
  },
})
