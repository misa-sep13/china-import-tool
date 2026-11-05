// 就労支援在庫の「この1週間の入荷」の出しかた。
// 管理画面と公開ページの両方で同じ形にしたいので、ここに置く。
//
// 年は同じ年のことしか出ないので省く。「11/4入荷」の形にする。
export const arrivalLabel = (d) => {
  const [, m, day] = (d || '').split('-')
  return m ? `${Number(m)}/${Number(day)}入荷` : '入荷'
}
