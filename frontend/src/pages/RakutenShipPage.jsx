import CreateSendOrder from './CreateSendOrder'

/**
 * 楽天の配送依頼。
 *
 * 倉庫（タオタロウ）にはAmazon用と楽天用の注文が一緒に入っている。
 * Amazonは「配送依頼・納品プラン」で出すので、ここは楽天の注文だけを出す。
 * 管理番号は楽天のSKU（y…）。Amazonと同じ商品でもSKUが別なので（石鹸置きは
 * Amazon a017_1／楽天 y141_1）、管理番号を見ればどちら用か分かる。
 */
export default function RakutenShipPage() {
  return (
    <div>
      <h1>🚚 配送依頼（楽天）</h1>
      <div className="card" style={{ marginBottom: 16 }}>
        <CreateSendOrder channel="rakuten" />
      </div>
    </div>
  )
}
