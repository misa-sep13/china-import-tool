/**
 * 月次管理表（発生ベース会計）の設計。
 *
 * 税理士に見てもらうための説明ページ。ログイン無しで開ける公開版
 * （/accounting-design-public）と、管理画面内から開く版の中身は同じ。
 *
 * 中身は docs/月次管理表_発生ベース会計_設計.md と同じ。直すときは
 * 両方を直すこと（片方だけ直すと、渡したURLの説明と手元の設計がずれる）。
 */

const C = {
  ink: '#0f172a',
  sub: '#475569',
  faint: '#64748b',
  line: '#e2e8f0',
  card: '#ffffff',
  bg: '#f8fafc',
  accent: '#1d4ed8',
  warn: '#b45309',
  warnBg: '#fffbeb',
}

const H2 = ({ n, children }) => (
  <h2 style={{
    fontSize: 19, fontWeight: 700, color: C.ink, margin: '34px 0 12px',
    display: 'flex', alignItems: 'baseline', gap: 10,
  }}>
    <span style={{
      fontSize: 12, fontWeight: 700, color: C.accent,
      border: `1px solid ${C.accent}`, borderRadius: 4,
      padding: '1px 6px', flexShrink: 0,
    }}>{n}</span>
    {children}
  </h2>
)

const Card = ({ children, style }) => (
  <div style={{
    background: C.card, border: `1px solid ${C.line}`, borderRadius: 10,
    padding: '14px 16px', ...style,
  }}>{children}</div>
)

const Note = ({ children }) => (
  <div style={{
    background: C.warnBg, border: '1px solid #fde68a', borderRadius: 10,
    padding: '12px 14px', color: C.warn, fontSize: 13.5, lineHeight: 1.9,
    margin: '12px 0',
  }}>{children}</div>
)

const th = {
  textAlign: 'left', fontSize: 12, fontWeight: 700, color: C.faint,
  borderBottom: `2px solid ${C.line}`, padding: '7px 10px', whiteSpace: 'nowrap',
}
const td = {
  fontSize: 13, color: C.ink, borderBottom: `1px solid ${C.line}`,
  padding: '7px 10px', verticalAlign: 'top',
}
const tdNum = {
  ...td, textAlign: 'right', fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap',
}

// セルに { num: ... } を渡すと右寄せ・等幅数字になる
const Table = ({ head, rows, widths }) => (
  <div style={{ overflowX: 'auto', margin: '10px 0 4px' }}>
    <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 420 }}>
      <thead>
        <tr>{head.map((h, i) => (
          <th key={i} style={{ ...th, width: widths?.[i] }}>{h}</th>
        ))}</tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i}>{r.map((c, j) => {
            const isNum = c && typeof c === 'object' && 'num' in c
            return <td key={j} style={isNum ? tdNum : td}>{isNum ? c.num : c}</td>
          })}</tr>
        ))}
      </tbody>
    </table>
  </div>
)

const P = ({ children, style }) => (
  <p style={{ fontSize: 14, lineHeight: 1.95, color: C.sub, margin: '10px 0', ...style }}>
    {children}
  </p>
)

const B = ({ children }) => <b style={{ color: C.ink }}>{children}</b>

const H3 = ({ children }) => (
  <h3 style={{ fontSize: 15, fontWeight: 700, color: C.ink, margin: '26px 0 2px' }}>
    {children}
  </h3>
)

const listStyle = {
  fontSize: 14, lineHeight: 2.1, color: C.sub, paddingLeft: 22, margin: '10px 0',
}

export default function MonthlyAccountingDesignPage() {
  return (
    <div style={{ background: C.bg, minHeight: '100vh' }}>
      <div style={{ maxWidth: 860, margin: '0 auto', padding: '26px 18px 70px' }}>

        <div style={{ borderBottom: `3px solid ${C.ink}`, paddingBottom: 14, marginBottom: 6 }}>
          <h1 style={{ fontSize: 25, fontWeight: 800, color: C.ink, margin: 0, lineHeight: 1.45 }}>
            月次管理表（発生ベース会計）設計
          </h1>
          <div style={{ fontSize: 12.5, color: C.faint, marginTop: 8 }}>
            作成 2026-11-17 ／ 状態：<b style={{ color: C.warn }}>設計のみ。実装は未着手</b>
          </div>
        </div>

        <H2 n="1">何を解決したいか</H2>
        <P>
          いまの試算表は、<B>タオタロウにデポジットした日</B>で仕入が計上されています。
          デポジットは「まとめて入金する前払金」であって、その月に仕入れたものではありません。
          そのため月ごとに利益の見え方が大きく振れます。
        </P>
        <Note>
          例：11/5に30万円チャージ → 11月の原価が30万円増える。<br />
          その30万円で実際に買った商品が12月に届いて1月に売れても、原価は11月に立っている。
        </Note>
        <P>
          これを、<B>その月に実際に発生したものだけを拾う形（発生ベース）</B>に組み替えます。
          あわせて、いま暫定で入っている数字（送料はツール登録値、店舗別内訳書なし）を実額に置き換え、
          根拠書類も同じ場所からダウンロードできるようにします。
        </P>

        <H2 n="2">原価を何から組み立てるか</H2>
        <P>調査の結果、<B>必要な数字はすべてツールから取れる</B>ことが分かりました。</P>
        <Card>
          <Table
            head={['要素', '取得元', '発生日', '状態']}
            rows={[
              ['商品代', 'タオタロウ入出金（区分：商品購入）', '注文日', '取得済'],
              ['値引・価格調整・数量調整・オーダー削除', '同上（同じ注文IDに相殺）', '調整日', '取得済'],
              ['中国国内送料', <code key="a">fees.send_price</code>, '便の出荷日', '取得済'],
              ['代行手数料', <code key="b">fees.server_fee</code>, '便の出荷日', '取得済'],
              ['国際送料', <code key="c">fees.freight</code>, '便の出荷日', '取得済'],
              ['通関手数料', <code key="d">fees.customs_fee</code>, '便の出荷日', '取得済'],
              ['関税・消費税', '輸入許可書（41件をDBに保存済）', <B key="e">輸入許可日</B>, '取得済'],
              ['タオタロウ月会費', 'タオタロウ入出金（区分：その他）', '毎月1日', '取得済'],
              ['チャージ', '同（区分：管理員操作）', '—', <B key="f">費用ではない</B>],
            ]}
          />
        </Card>

        <H3>分かったこと（重要）</H3>
        <P>
          <B>デポジットの明細に国際運賃は3件（計3,524元）しか落ちていません。</B>
          実際の送料は<B>便ごとの fees</B> に入っていて、直近16便で<B>合計14,588元（約36万円）</B>。
          差額は埼玉りそなのリアルタイム口座から直接引き落とされています。
        </P>
        <Card>
          <Table
            head={['配送依頼', '日付', '重量', '送料計（元）']}
            rows={[
              ['721710', '11-09', { num: '131kg' }, { num: '2,065.50' }],
              ['720456', '11-02', { num: '121kg' }, { num: '1,035.05' }],
              ['718557', '10-22', { num: '182kg' }, { num: '2,489.80' }],
              ['718382', '10-21', { num: '220kg' }, { num: '1,876.70' }],
              ['716670', '10-13', { num: '83kg' }, { num: '932.30' }],
              ['712752', '09-16', { num: '213kg' }, { num: '1,915.00' }],
              ['（他10便）', '', { num: '' }, { num: '' }],
            ]}
          />
        </Card>
        <P>
          <B>按分に銀行明細は要りません。</B>
          便ごとの金額と、その便に何が何個入っているかはツールが持っているので、
          原価への按分はツール内で完結します。
          マネーフォワードは「いつ・いくら払ったか」の裏取りに使います。
        </P>

        <H3>タオタロウ入出金の区分（2026-06-08〜11-17／1,000件）</H3>
        <Card>
          <Table
            head={['区分', '件数', '金額（元）', '会計上の扱い']}
            rows={[
              ['商品購入', { num: '711' }, { num: '−201,524' }, '仕入（原価）'],
              ['オーダー削除', { num: '112' }, { num: '+30,662' }, '仕入の戻し'],
              ['数量調整', { num: '51' }, { num: '—' }, '仕入の修正'],
              ['管理員操作', { num: '51' }, { num: '+173,308' },
                <B key="g">前払金（資産）の増減。費用ではない</B>],
              ['価格調整', { num: '43' }, { num: '—' }, '仕入の修正'],
              ['値引交渉', { num: '24' }, { num: '+11,560' }, '仕入の値引'],
              ['その他', { num: '5' }, { num: '−6,134' },
                <span key="h"><B>月会費</B>（毎月1日・30,000円ちょうど）。固定費、按分しない</span>],
              ['国際運賃', { num: '3' }, { num: '−3,524' }, '仕入諸掛（按分）'],
            ]}
          />
        </Card>

        <H2 n="3">発生日をどう決めるか</H2>
        <P>候補は「輸入許可日」と「商品の到着日」です。</P>
        <P>
          <B>輸入許可日を採用します。</B>
          理由は単純で、<B>到着日の実データが無い</B>（輸入許可書41件すべて到着日が空）ためです。
          輸入許可日は41件すべて入っています。実務上も両者は数日しか違わないので、
          月次の利益の見え方はほとんど変わりません。
        </P>
        <Card>
          <Table
            head={['区分', '計上する日']}
            widths={['45%']}
            rows={[
              ['商品代・調整', '注文日'],
              ['送料・手数料', '便の出荷日'],
              ['関税・消費税', '輸入許可日'],
              ['月会費', '毎月1日（按分しない）'],
              ['チャージ', '計上しない（前払金の増減）'],
            ]}
          />
        </Card>

        <H2 n="4">書類の保存</H2>
        <P>税理士がいつでもダウンロードできる場所を1つにします。</P>
        <Card>
          <Table
            head={['書類', 'いまの状態']}
            widths={['38%']}
            rows={[
              ['輸入許可書', <B key="i">41件をDBに保存済（PDF・計4.7MB／平均118KB）</B>],
              ['RMS店舗別内訳書', '未保存。これが無いので売上が暫定'],
              ['ヤマト運輸の送料請求書', '未保存。いまはツール登録値で暫定'],
              ['タオタロウの請求・明細', 'APIから取得可（保存は未実装）'],
            ]}
          />
        </Card>
        <P>
          <B>容量は問題ありません。</B>現在 245MB / 5GB（8.9%）。
          許可書は平均118KBなので、月10件増えても年間14MB程度です。
        </P>

        <H2 n="5">画面の形</H2>
        <ul style={listStyle}>
          <li>楽天とAmazonを<B>同じ場所</B>に置く（別タブでよい）</li>
          <li>月を選ぶと、その月の発生ベースの損益が出る</li>
          <li>デポジットの内訳（商品代・中国国内送料・代行手数料・国際送料・通関料・月会費・チャージ）を分解して見せる</li>
          <li>在庫金額を併記（月末在庫を持つ仕組みは既にある）</li>
          <li>根拠書類はその月の行からダウンロードできる</li>
        </ul>

        <H3>マネーフォワードとの関係</H3>
        <ul style={listStyle}>
          <li>税理士は<B>この管理表を直接見る</B>。入力は税理士が行う</li>
          <li>MFに自動連携している明細（埼玉りそなの国際送料引き落としなど）を<B>ツール側に取り込む</B></li>
          <li>取り込み方：<B>CSVは確実</B>。API連携も可能だが、<B>使える範囲は未確認</B></li>
        </ul>

        <H2 n="6">既にある部品</H2>
        <Card>
          <Table
            head={['テーブル / 機能', '状態']}
            widths={['34%']}
            rows={[
              [<code key="j">invoices</code>,
                <span key="k">按分計算のロジックあり。<B>登録0件</B>（使われていない）</span>],
              [<code key="l">import_permits</code>, 'PDFをDBに保存。41件'],
              [<code key="m">inventory_snapshots</code>, '月末在庫金額'],
              [<code key="n">material_costs</code>, '資材原価'],
              [<code key="o">daily_sales</code>, '日別売上'],
            ]}
          />
        </Card>
        <P>
          <code>invoices</code> の按分ロジックが既にあるので、<B>ゼロからではありません。</B>
        </P>

        <H2 n="7">着手順</H2>
        <ol style={listStyle}>
          <li><B>デポジットの内訳分解</B>（←ここから）</li>
          <li>便ごとの <code>fees</code> を取り込み、便の中身に按分</li>
          <li>輸入許可書の関税・消費税を輸入許可日で計上</li>
          <li>月次の集計画面（楽天／Amazon）</li>
          <li>書類保存（RMS店舗別内訳書・ヤマト請求書）</li>
          <li>MFからの取込（CSV → API）</li>
        </ol>

        <H2 n="8">未確認・未決</H2>
        <ul style={listStyle}>
          <li>MF APIで何が取れるか（CSVは確実）</li>
          <li>RMS店舗別内訳書の取得方法（手動DLか、APIがあるか）</li>
          <li>ヤマト請求書の取得方法</li>
          <li>輸入許可書の到着日を今後埋めるか（埋めれば到着日ベースも選べる）</li>
          <li>期首・期末の在庫をどう締めるか</li>
        </ul>

        <div style={{
          marginTop: 40, paddingTop: 16, borderTop: `1px solid ${C.line}`,
          fontSize: 12, color: C.faint, lineHeight: 1.9,
        }}>
          このページは設計の説明で、数字は 2026-11-17 時点の調査結果です。
          実際の月次の金額は、実装後に管理表の画面で確認してください。
        </div>
      </div>
    </div>
  )
}
