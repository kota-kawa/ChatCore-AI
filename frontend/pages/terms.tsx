import { SeoHead } from "../components/SeoHead";
import { LegalDocument, type LegalSection, type LegalSummaryItem } from "../components/docs/legal_document";
import { absoluteUrl } from "../lib/seo";

const TERMS_TITLE = "利用規約 | ChatCore-AI";

const TERMS_DESCRIPTION =
  "ChatCore-AIの利用規約です。アカウント登録、利用料金、禁止事項、コンテンツの権利、AI生成コンテンツの取り扱いなど、サービスを利用するうえでのルールを説明します。";

// ページ内で繰り返し使う日付は定数にまとめる / Dates reused across the page are kept as constants
const ESTABLISHED_DATE = "2026年7月17日";

// 要点サマリー（正式な内容は本文が優先） / Plain-language summary (the full text below prevails)
const TERMS_SUMMARY: LegalSummaryItem[] = [
  {
    icon: "bi-wallet2",
    title: "無料で使えます",
    text: "アカウント登録も基本機能の利用も無料です。クレジットカードの登録は不要です。"
  },
  {
    icon: "bi-person-check",
    title: "コンテンツはあなたのもの",
    text: "作成したチャット・メモ・プロンプトの権利は利用者に帰属します。"
  },
  {
    icon: "bi-patch-question",
    title: "AIの回答は確認を",
    text: "AIの応答には誤りが含まれることがあります。重要な判断の前には内容をご確認ください。"
  }
];

// 利用規約本文（条文定義） / Terms of service body (article definitions)
const TERMS_SECTIONS: LegalSection[] = [
  {
    id: "article-1",
    number: "第1条",
    heading: "適用",
    body: (
      <>
        <p>
          本規約は、Chat Core（以下「運営者」）が提供するサービス「ChatCore-AI」（以下「本サービス」）の利用条件を定めるものです。利用者は、本サービスを利用することにより、本規約に同意したものとみなされます。
        </p>
        <p>
          個人情報の取り扱いについては、
          <a href="/privacy">プライバシーポリシー</a>をあわせてご確認ください。
        </p>
      </>
    )
  },
  {
    id: "article-2",
    number: "第2条",
    heading: "アカウント登録",
    body: (
      <>
        <p>
          本サービスの利用にはアカウント登録が必要です。登録は、メールアドレスとパスワードによる方法、またはGoogleアカウント連携による方法で行えます。
        </p>
        <ul>
          <li>登録情報は正確な内容を提供してください。</li>
          <li>パスワードなどの認証情報は利用者の責任で管理してください。</li>
          <li>アカウントを第三者に譲渡・貸与することはできません。</li>
        </ul>
      </>
    )
  },
  {
    id: "article-3",
    number: "第3条",
    heading: "利用料金",
    body: (
      <p>
        本サービスの基本機能は無料で利用できます。将来、有料の機能を提供する場合は、その内容と料金を事前に本サービス上で告知します。
      </p>
    )
  },
  {
    id: "article-4",
    number: "第4条",
    heading: "禁止事項",
    body: (
      <>
        <p>利用者は、本サービスの利用にあたり、次の行為を行ってはなりません。</p>
        <ul>
          <li>法令または公序良俗に違反する行為</li>
          <li>第三者の権利（著作権、プライバシー、名誉など）を侵害する行為</li>
          <li>不正アクセス、過度な負荷をかける行為、その他本サービスの運営を妨害する行為</li>
          <li>プロンプト共有などの公開機能に、個人情報や機密情報を投稿する行為</li>
          <li>本サービスを違法・有害なコンテンツの生成に利用する行為</li>
          <li>その他、運営者が不適切と判断する行為</li>
        </ul>
      </>
    )
  },
  {
    id: "article-5",
    number: "第5条",
    heading: "コンテンツの権利",
    body: (
      <>
        <p>
          利用者が本サービス上で作成したチャット・メモ・プロンプトなどのコンテンツの権利は、利用者に帰属します。運営者は、本サービスの提供・維持・改善に必要な範囲でのみ、これらのコンテンツを取り扱います。
        </p>
        <p>
          プロンプト共有機能などで公開したコンテンツは、他の利用者が閲覧・利用できる状態になります。公開の要否は利用者自身の判断で行ってください。
        </p>
      </>
    )
  },
  {
    id: "article-6",
    number: "第6条",
    heading: "AI生成コンテンツの取り扱い",
    body: (
      <>
        <p>
          本サービスのAIチャットは、外部のLLM（大規模言語モデル）APIを利用して応答を生成します。生成される内容の正確性・完全性・有用性について、運営者は保証しません。
        </p>
        <ul>
          <li>AIの応答には事実と異なる内容が含まれることがあります。重要な判断の前には必ず内容を確認してください。</li>
          <li>医療・法律・金融など専門的な判断が必要な事項は、専門家に相談してください。</li>
          <li>AIの応答を利用した結果について、運営者は責任を負いません。</li>
        </ul>
      </>
    )
  },
  {
    id: "article-7",
    number: "第7条",
    heading: "サービスの変更・中断・終了",
    body: (
      <p>
        運営者は、システムの保守、障害の発生、その他やむを得ない事情により、本サービスの全部または一部を予告なく変更・中断・終了することがあります。これにより利用者に生じた損害について、運営者は責任を負いません。
      </p>
    )
  },
  {
    id: "article-8",
    number: "第8条",
    heading: "アカウントの停止・削除",
    body: (
      <>
        <p>
          運営者は、利用者が本規約に違反した場合、事前の通知なくアカウントの利用停止または削除を行うことがあります。
        </p>
        <p>利用者は、設定画面からいつでも自身のアカウントを削除できます。</p>
      </>
    )
  },
  {
    id: "article-9",
    number: "第9条",
    heading: "免責事項",
    body: (
      <>
        <p>
          運営者は、本サービスに事実上または法律上の瑕疵（安全性、信頼性、正確性、完全性、有効性、特定目的への適合性などを含みます）がないことを保証しません。
        </p>
        <p>
          本サービスの利用に関して利用者に生じた損害について、運営者の故意または重過失による場合を除き、運営者は責任を負いません。
        </p>
      </>
    )
  },
  {
    id: "article-10",
    number: "第10条",
    heading: "規約の変更",
    body: (
      <p>
        運営者は、必要と判断した場合、本規約を変更することがあります。重要な変更を行う場合は、本サービス上でお知らせします。変更後の規約は、本ページに掲載した時点から効力を生じます。
      </p>
    )
  },
  {
    id: "article-11",
    number: "第11条",
    heading: "準拠法・裁判管轄",
    body: (
      <p>
        本規約の解釈には日本法を準拠法とします。本サービスに関して紛争が生じた場合は、運営者の所在地を管轄する裁判所を専属的合意管轄とします。
      </p>
    )
  }
];

// 利用規約ページの構造化データ（WebPage・パンくず）
// Structured data for the terms page (WebPage, breadcrumbs)
const termsStructuredData = [
  {
    "@context": "https://schema.org",
    "@type": "WebPage",
    name: TERMS_TITLE,
    url: absoluteUrl("/terms"),
    description: TERMS_DESCRIPTION,
    inLanguage: "ja",
    isPartOf: {
      "@type": "WebSite",
      name: "Chat Core",
      url: absoluteUrl("/")
    }
  },
  {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: [
      { "@type": "ListItem", position: 1, name: "ホーム", item: absoluteUrl("/") },
      { "@type": "ListItem", position: 2, name: "利用規約", item: absoluteUrl("/terms") }
    ]
  }
];

// 利用規約ページ / Terms of service page
export default function TermsPage() {
  return (
    <>
      <SeoHead
        title={TERMS_TITLE}
        description={TERMS_DESCRIPTION}
        canonicalPath="/terms"
        structuredData={termsStructuredData}
      >
        {/* ドキュメント系ページはLPのトークンを共有するため両方のCSSを読み込む
            Document pages load both stylesheets since they share the LP tokens */}
        <link rel="stylesheet" href="/static/css/pages/lp/lp.css" />
        <link rel="stylesheet" href="/static/css/pages/docs/docs.css" />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Shippori+Mincho:wght@500;600;700&display=swap"
          rel="stylesheet"
        />
      </SeoHead>

      <LegalDocument
        kicker="安心して使うために"
        eyebrow="TERMS OF SERVICE"
        title="利用規約"
        lead="ChatCore-AIを気持ちよく使っていただくためのルールです。サービスをご利用いただく前に、ご一読ください。"
        meta={[`制定日：${ESTABLISHED_DATE}`, "運営：Chat Core"]}
        summaryLabel="要点まとめ"
        summary={TERMS_SUMMARY}
        summaryNote="※ この要約は理解を助けるためのものです。正式な内容は以下の本文が優先されます。"
        sections={TERMS_SECTIONS}
      />
    </>
  );
}
