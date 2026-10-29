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

  // 季節商品の候補。「いま発注すると届くころ、去年は平月の何倍売れたか」。
  // 去年の実績が溜まっていないうちは候補を出さず、足りないと言う
  const { data: seasonal } = useQuery({
    queryKey: ['seasonal', site || 'rakuten'],
    queryFn: async () =>
      (await api.get('/season/seasonal', { params: { site: site || 'rakuten' } })).data,
    staleTime: 60 * 60 * 1000,
    enabled: !!site,
  })

  const sites = site ? (data?.sites || []).filter((s) => s.site === site)
                     : (data?.sites || [])
  const hasSeasonal = seasonal?.enough_data && seasonal.candidates?.length > 0
  if (!data?.show && !hasSeasonal) return null
  if (!sites.length && !hasSeasonal) return null

  // 帯の色は、出しているサイトのうちいちばん急ぐものに合わせる
  const order = ['urgent', 'soon', 'missed', 'closed']
  const stage = sites.map((s) => s.stage)
    .sort((a, b) => order.indexOf(a) - order.indexOf(b))[0]
  const tone = TONE[stage] || TONE.soon
  const showHoliday = data?.show && sites.length > 0
  const p = data?.period

  return (
    <>
      {showHoliday && (
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
                  <span style={{ fontSize: 13, marginLeft: 8 }}>
                    {s.days_left >= 0 ? `あと${s.days_left}日` : '過ぎました'}
                  </span>
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
      )}

      {hasSeasonal && (
        <div style={{
          background: '#eff6ff', border: '2px solid #2563eb', borderRadius: 8,
          padding: 14, marginBottom: 16, color: '#1e3a8a',
        }}>
          <div style={{ fontWeight: 700, marginBottom: 6 }}>
            🌡️ いま発注すると届くのは {seasonal.arrival_from} 〜 {seasonal.arrival_to} ごろです
          </div>
          <div style={{ fontSize: 13, marginBottom: 8 }}>
            去年の同じ時期（{seasonal.last_year_from} 〜 {seasonal.last_year_to}）に、
            平月より多く売れていた商品です。「上積みの目安」は、平月どおりの
            ペースでは足りなかった個数です。多い順に並べています。
          </div>
          <table style={{ fontSize: 13, borderCollapse: 'collapse', background: '#fff' }}>
            <thead>
              <tr style={{ background: '#dbeafe' }}>
                <th style={{ textAlign: 'left', padding: '4px 10px' }}>SKU</th>
                <th style={{ textAlign: 'left', padding: '4px 10px' }}>商品</th>
                <th style={{ textAlign: 'right', padding: '4px 10px' }}>上積みの目安</th>
                <th style={{ textAlign: 'right', padding: '4px 10px' }}>去年の倍率</th>
                <th style={{ textAlign: 'right', padding: '4px 10px' }}>去年の販売数</th>
              </tr>
            </thead>
            <tbody>
              {seasonal.candidates.slice(0, 15).map((c) => (
                <tr key={c.sku} style={{ borderTop: '1px solid #e5e7eb' }}>
                  <td style={{ padding: '4px 10px', fontFamily: 'monospace' }}>{c.sku}</td>
                  <td style={{ padding: '4px 10px', maxWidth: 360,
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {c.name}
                  </td>
                  <td style={{ padding: '4px 10px', textAlign: 'right', fontWeight: 700 }}>
                    +{c.extra_units}個
                  </td>
                  <td style={{ padding: '4px 10px', textAlign: 'right' }}>
                    {c.ratio}倍
                  </td>
                  <td style={{ padding: '4px 10px', textAlign: 'right' }}>
                    {c.units_last_year}個
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ fontSize: 12, marginTop: 6, opacity: 0.85 }}>
            ※ 発注数には反映していません。見て判断してください。
            在庫切れだった日は数えていません。
          </div>
        </div>
      )}
    </>
  )
}
