import { useQuery } from '@tanstack/react-query'
import api from './client'

/**
 * 就労支援のデータが変わったかどうかだけを、60秒ごとに見る。
 *
 * 施設の画面は開きっぱなしになる。以前は60秒ごとに一覧そのものを
 * 取り直していて、荷受け一覧だけで1回3.5MB、放っておくと月147GBに
 * なっていた（無料枠は5.5GB）。まずここを見て、変わったときだけ
 * 一覧を取り直す。返ってくるのは件数と最終更新時刻だけ。
 *
 * 戻り値を一覧の queryKey に混ぜると、変わったときだけ取り直される。
 */
export function useWelfareVersion(kind) {
  const { data } = useQuery({
    queryKey: ['welfare-version'],
    queryFn: () => api.get('/welfare/version').then(r => r.data),
    refetchInterval: 60000,
    // 繋がらないときは前の値のままにする（一覧を無駄に取り直さない）
    retry: false,
  })
  const v = data?.[kind]
  return v ? `${v.count}:${v.updated_at || ''}` : ''
}
