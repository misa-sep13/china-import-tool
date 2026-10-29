// 春節・国慶節の「いつまでに発注するか」を出す帯。
//
// 発注数そのものは中国の長期休暇の設定が自動で増やしている。ただ画面には
// 増えた数字しか出ないので、なぜ増えたのか・あと何日で締切かが分からず、
// 「気づいたら間に合わない」になりやすかった。
//
// いちばん大事なのは最終発注日。この日を過ぎた発注は、工場が止まるので
// 休み明けまで届かない。残り日数を大きく出す。
import { useQuery } from '@tanstack/react-query'
import api from '../api/client'

const TONE = {
  urgent: { bg: '#fef2f2', border: '#dc2626', text: '#991b1b', icon: '🏮' },
  soon:   { bg: '#fff7ed', border: '#ea580c', text: '#9a3412', icon: '🏮' },
  missed: { bg: '#f8fafc', border: '#94a3b8', text: '#475569', icon: '🏮' },
  closed: { bg: '#f8fafc', border: '#94a3b8', text: '#475569', icon: '🏮' },
}

// site を渡すとそのサイトぶんだけ出す。省くと両方。
export default function SeasonAlertBanner({ site = null }) {
  const { data } = useQuery({
    queryKey: ['season-alert'],
    queryFn: async () => (await api.get('/season/alert')).data,
    staleTime: 60 * 60 * 1000,   // 1日のうちに変わるものではない
  })

  if (!data?.show) return null
  const sites = site ? (data.sites || []).filter((s) => s.site === site)
                     : (data.sites || [])
  if (!sites.length) return null

  // 帯の色は、出しているサイトのうちいちばん急ぐものに合わせる
  const order = ['urgent', 'soon', 'missed', 'closed']
  const stage = sites.map((s) => s.stage)
    .sort((a, b) => order.indexOf(a) - order.indexOf(b))[0]
  const tone = TONE[stage] || TONE.soon
  const p = data.period

  return (
    <div style={{
      background: tone.bg, border: `2px solid ${tone.border}`,
      borderRadius: 8, padding: 14, marginBottom: 16, color: tone.text,
    }}>
      <div style={{ fontWeight: 700, marginBottom: 6 }}>
        {tone.icon} {p.name}で工場が止まります
        （{p.start} 〜 {p.end} の{p.days}日間）
      </div>

      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', margin: '10px 0' }}>
        {sites.map((s) => (
          <div key={s.site} style={{
            background: '#fff', border: `1px solid ${tone.border}`,
            borderRadius: 6, padding: '8px 12px', minWidth: 190,
          }}>
            <div style={{ fontSize: 12, opacity: 0.8 }}>{s.label}の発注しめきり</div>
            <div style={{ fontSize: 18, fontWeight: 700 }}>
              {s.last_order_day}
              {s.days_left >= 0 ? (
                <span style={{ fontSize: 13, marginLeft: 8 }}>
                  あと{s.days_left}日
                </span>
              ) : (
                <span style={{ fontSize: 13, marginLeft: 8 }}>過ぎました</span>
              )}
            </div>
            <div style={{ fontSize: 12, marginTop: 4 }}>
              {s.days_left >= 0
                ? `これ以降の発注は ${s.resume_arrival} 入荷になります`
                : `いま発注すると ${s.resume_arrival} 入荷です`}
            </div>
            {s.extra_days > 0 && (
              <div style={{ fontSize: 12, marginTop: 4, fontWeight: 600 }}>
                発注数は {s.extra_days}日分 多めに出しています
              </div>
            )}
          </div>
        ))}
      </div>

      <div style={{ fontSize: 13 }}>
        {sites.length === 1 ? sites[0].message : data.message}
        <div style={{ marginTop: 4, opacity: 0.85 }}>
          ※ しめきりを過ぎても発注はできますが、入荷は休み明けになります。
          休暇が終われば発注数は自動で元に戻ります。
        </div>
      </div>
    </div>
  )
}
