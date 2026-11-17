import { useEffect, useState } from 'react'
import DepositBreakdownPage from './DepositBreakdownPage'
import FreightByShipmentPage from './FreightByShipmentPage'
import MonthlyAccountingDesignPage from './MonthlyAccountingDesignPage'

/**
 * 月次管理表。会計まわりを1枚にまとめた画面。
 *
 * 試算表がタオタロウへデポジットした日で計上されていて、月ごとの利益の
 * 見え方が振れる。その月に実際に発生したぶんだけを拾う形（発生ベース）に
 * 組み替えるための画面。
 *
 * タブは作れた順に中身が入る。まだ作っていないタブは、何が要るかを
 * その場に書いておく（別の場所に散らすと、どこまで出来たか分からなくなる）。
 *
 * 設計の全体像は docs/月次管理表_発生ベース会計_設計.md にもある。
 */

const TABS = [
  { key: 'summary',  label: '📈 月次サマリー' },
  { key: 'deposit',  label: '💰 デポジット内訳' },
  { key: 'freight',  label: '🚢 便ごとの送料' },
  { key: 'stock',    label: '📦 在庫金額' },
  { key: 'docs',     label: '📑 書類' },
  { key: 'design',   label: '📘 設計' },
]

function Coming({ title, what, need, order }) {
  return (
    <div className="card" style={{ maxWidth: 720 }}>
      <h2 style={{ margin: '0 0 4px', fontSize: 18 }}>{title}</h2>
      <div style={{ fontSize: 12, color: '#b45309', fontWeight: 700, marginBottom: 12 }}>
        まだ作っていません（着手順 {order}）
      </div>
      <div style={{ fontSize: 14, color: '#475569', lineHeight: 1.95 }}>
        <b style={{ color: '#0f172a' }}>ここに出るもの</b>
        <ul style={{ paddingLeft: 20, margin: '6px 0 14px' }}>
          {what.map((t, i) => <li key={i}>{t}</li>)}
        </ul>
        <b style={{ color: '#0f172a' }}>そのために要るもの</b>
        <ul style={{ paddingLeft: 20, margin: '6px 0 0' }}>
          {need.map((t, i) => <li key={i}>{t}</li>)}
        </ul>
      </div>
    </div>
  )
}

export default function AccountingPage() {
  // タブはURLのハッシュに残す。税理士に「このタブを見てください」と
  // URLごと渡せるようにするため
  const [tab, setTab] = useState(() => {
    const m = (window.location.hash || '').match(/[?&]tab=([a-z]+)/)
    return TABS.some(t => t.key === m?.[1]) ? m[1] : 'deposit'
  })

  useEffect(() => {
    const h = window.location.hash || ''
    const base = h.split('?')[0] || '#/accounting'
    const next = `${base}?tab=${tab}`
    if (h !== next) window.history.replaceState(null, '', next)
  }, [tab])

  return (
    <div>
      <h1 style={{ margin: '0 0 4px' }}>📊 月次管理表</h1>
      <div style={{ fontSize: 13, color: '#475569', lineHeight: 1.9, marginBottom: 14 }}>
        その月に実際に発生したぶんだけを拾う形（発生ベース）に組み替えるための画面です。
        チャージ（前払金）は原価に入れません。
      </div>

      <div style={{ display: 'flex', gap: 8, overflowX: 'auto',
        paddingBottom: 10, marginBottom: 14, borderBottom: '1px solid #e2e8f0' }}>
        {TABS.map(t => (
          <button key={t.key}
            className={`btn ${tab === t.key ? 'btn-primary' : 'btn-secondary'}`}
            style={{ whiteSpace: 'nowrap' }}
            onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'deposit' && <DepositBreakdownPage />}

      {tab === 'design' && (
        <div style={{ margin: '-14px -14px 0' }}>
          <MonthlyAccountingDesignPage />
        </div>
      )}

      {tab === 'summary' && (
        <Coming
          order="4"
          title="月次サマリー"
          what={[
            '月ごとの売上・原価・粗利（楽天／Amazon）',
            '原価の内訳：商品代・中国国内送料・代行手数料・国際送料・通関料・関税',
            '固定費（タオタロウ月会費など）は原価と分けて表示',
          ]}
          need={[
            '便ごとの送料の按分（このタブの「🚢 便ごとの送料」）',
            '輸入許可書の関税・消費税を輸入許可日で計上',
            'RMS店舗別内訳書（いま売上が暫定なのはこれが無いため）',
          ]}
        />
      )}

      {tab === 'freight' && <FreightByShipmentPage />}

      {tab === 'stock' && (
        <Coming
          order="4"
          title="在庫金額"
          what={[
            '月末在庫の金額（楽天／Amazon／就労支援）',
            '期首・期末の差分',
          ]}
          need={[
            'inventory_snapshots の運用ルール（いつ締めるか）を決める',
            '発生ベースの原価が先に固まっていること',
          ]}
        />
      )}

      {tab === 'docs' && (
        <Coming
          order="5"
          title="書類"
          what={[
            '輸入許可書（41件はすでにDBに保存済み）',
            'RMS店舗別内訳書',
            'ヤマト運輸の送料請求書',
            'タオタロウの請求・明細',
            'その月の行からまとめてダウンロードできる形',
          ]}
          need={[
            'RMS店舗別内訳書とヤマト請求書の取得方法を決める（手動アップロードか、APIか）',
            '容量は問題なし（現在 245MB / 5GB。許可書は平均118KB）',
          ]}
        />
      )}
    </div>
  )
}
