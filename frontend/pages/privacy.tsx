import { SeoHead } from "../components/SeoHead";
import { LegalDocument, type LegalSection, type LegalSummaryItem } from "../components/docs/legal_document";
import { absoluteUrl } from "../lib/seo";
import { useTranslation } from "../contexts/locale_context";

const PRIVACY_TITLE = "プライバシーポリシー | ChatCore-AI";

const PRIVACY_DESCRIPTION =
  "ChatCore-AIのプライバシーポリシーです。取得する情報の種類、利用目的、外部サービスへの送信、Cookieの利用、データの保存期間と削除方法についてわかりやすく説明します。";

// ページ内で繰り返し使う日付は定数にまとめる / Dates reused across the page are kept as constants
const ESTABLISHED_DATE = "2026年7月17日";

// 要点サマリー（正式な内容は本文が優先） / Plain-language summary (the full text below prevails)
const PRIVACY_SUMMARY: LegalSummaryItem[] = [
  {
    icon: "bi-shield-lock",
    title: "取得は必要最小限",
    text: "サービスの提供に必要な情報だけを取得します。パスワードはハッシュ化して保存します。"
  },
  {
    icon: "bi-cpu",
    title: "AI応答のための送信",
    text: "チャット内容は、応答を生成するために必要な範囲でのみ外部のLLM APIへ送信します。"
  },
  {
    icon: "bi-trash3",
    title: "いつでも削除できます",
    text: "設定画面からアカウントを削除すると、保存されたデータも削除されます。"
  }
];

// プライバシーポリシー本文（セクション定義） / Privacy policy body (section definitions)
const PRIVACY_SECTIONS: LegalSection[] = [
  {
    id: "collection",
    number: "1.",
    heading: "取得する情報",
    body: (
      <>
        <p>本サービス「ChatCore-AI」（以下「本サービス」）は、提供にあたり次の情報を取得します。</p>
        <ul>
          <li>
            <strong>アカウント情報</strong>
            ：メールアドレス、パスワード（ハッシュ化して保存し、平文では保持しません）、Googleアカウントでログインした場合はGoogleから提供されるプロフィール情報（メールアドレス・表示名など）。
          </li>
          <li>
            <strong>コンテンツ</strong>
            ：チャットの会話内容、作成したメモ、投稿したプロンプトなど、利用者が本サービス上で作成・保存した情報。
          </li>
          <li>
            <strong>利用情報</strong>
            ：アクセスログ、Cookieなどの識別子、ブラウザや端末に関する情報。
          </li>
        </ul>
      </>
    )
  },
  {
    id: "purpose",
    number: "2.",
    heading: "利用目的",
    body: (
      <>
        <p>取得した情報は、次の目的でのみ利用します。</p>
        <ul>
          <li>本サービスの提供・維持・改善（AIチャットの応答生成、メモやプロンプトの保存・表示を含む）</li>
          <li>ログイン認証、パスワード再設定、メールアドレス変更などの本人確認</li>
          <li>不正利用の防止と安全性の確保</li>
          <li>利用状況の分析による機能改善</li>
          <li>重要なお知らせの通知</li>
        </ul>
      </>
    )
  },
  {
    id: "third-party",
    number: "3.",
    heading: "外部サービスへの送信",
    body: (
      <>
        <p>
          本サービスは、機能の提供に必要な範囲で次の外部サービスを利用しており、対応する情報が各サービスへ送信されます。
        </p>
        <ul>
          <li>
            <strong>LLM API（Groq、Anthropic Claudeなど）</strong>
            ：AIチャットの応答を生成するため、会話内容が送信されます。応答生成以外の目的で提供することはありません。
          </li>
          <li>
            <strong>Google OAuth</strong>：Googleアカウントでのログインに利用します。
          </li>
          <li>
            <strong>Resend</strong>：確認コードなどのメール送信に利用します。
          </li>
          <li>
            <strong>Google Analytics</strong>
            ：利用状況の分析に利用します。Cookieを通じて匿名化された利用データが収集されます。
          </li>
        </ul>
        <p>法令に基づく場合を除き、上記以外の第三者に個人情報を提供することはありません。</p>
      </>
    )
  },
  {
    id: "cookie",
    number: "4.",
    heading: "Cookieの利用",
    body: (
      <>
        <p>
          本サービスは、ログイン状態の維持、テーマ設定などの環境保存、およびアクセス解析のためにCookieおよび類似の技術を使用します。
        </p>
        <p>
          ブラウザの設定でCookieを無効化できますが、その場合ログインを必要とする機能が利用できなくなることがあります。
        </p>
      </>
    )
  },
  {
    id: "security",
    number: "5.",
    heading: "安全管理措置",
    body: (
      <>
        <p>取得した情報を保護するため、次の措置を講じています。</p>
        <ul>
          <li>通信のTLS暗号化</li>
          <li>パスワードのハッシュ化保存</li>
          <li>Passkey（パスワードレス認証）への対応</li>
          <li>アクセス制御による内部データへのアクセス制限</li>
        </ul>
      </>
    )
  },
  {
    id: "retention",
    number: "6.",
    heading: "保存期間と削除",
    body: (
      <>
        <p>
          アカウント情報およびコンテンツは、アカウントが有効である間、本サービスの提供のために保存されます。
        </p>
        <p>
          設定画面からアカウントを削除すると、保存されたアカウント情報とコンテンツは削除されます。バックアップからの完全な消去には一定の期間を要する場合があります。
        </p>
      </>
    )
  },
  {
    id: "rights",
    number: "7.",
    heading: "利用者の権利",
    body: (
      <>
        <p>
          利用者は、自身の情報について開示・訂正・削除を求めることができます。メールアドレスの変更やアカウントの削除は、ログイン後の設定画面からいつでも行えます。
        </p>
        <p>
          その他のご請求は、<a href="/help#account">ヘルプページ</a>記載のお問い合わせ方法によりご連絡ください。
        </p>
      </>
    )
  },
  {
    id: "changes",
    number: "8.",
    heading: "ポリシーの変更",
    body: (
      <>
        <p>
          本ポリシーの内容は、法令の改正やサービス内容の変更に応じて改定されることがあります。重要な変更を行う場合は、本サービス上でお知らせします。
        </p>
        <p>改定後のポリシーは、本ページに掲載した時点から効力を生じます。</p>
      </>
    )
  },
  {
    id: "contact",
    number: "9.",
    heading: "お問い合わせ",
    body: (
      <p>
        本ポリシーに関するお問い合わせは、
        <a href="https://github.com/kota-kawa/Chat-Core/issues" target="_blank" rel="noopener noreferrer">
          GitHubリポジトリのIssue
        </a>
        よりお寄せください。
      </p>
    )
  }
];

const PRIVACY_SUMMARY_EN: LegalSummaryItem[] = [
  { icon: "bi-shield-lock", title: "Only what is needed", text: "We collect only information needed to provide the Service. Passwords are stored as hashes." },
  { icon: "bi-cpu", title: "Sent only to generate AI responses", text: "Chat content is sent to third-party LLM APIs only as needed to generate a response." },
  { icon: "bi-trash3", title: "You can delete your data", text: "Deleting your account from Settings also deletes the data stored for that account." }
];

const PRIVACY_SECTIONS_EN: LegalSection[] = [
  {
    id: "collection", number: "1.", heading: "Information we collect", body: <><p>ChatCore-AI (the “Service”) collects the following information when you use it:</p><ul><li><strong>Account information:</strong> email address, password hash, display name, and profile image.</li><li><strong>Content:</strong> chats, memos, prompts, comments, and files you choose to save or publish.</li><li><strong>Technical information:</strong> cookies, session identifiers, IP address, browser information, and access logs needed for security and operation.</li><li><strong>Connected-service information:</strong> identifiers and authorization data supplied by Google or another service you choose to connect.</li></ul></>
  },
  {
    id: "purpose", number: "2.", heading: "How we use information", body: <><p>We use information to provide authentication and Service features, generate AI responses, preserve settings and content, prevent abuse, investigate faults, provide support, and improve reliability.</p><p>We do not sell personal information.</p></>
  },
  {
    id: "third-party", number: "3.", heading: "Third-party services", body: <><p>Information may be sent to service providers only as needed to operate the feature you request.</p><ul><li><strong>LLM providers:</strong> chat text, prompts, and relevant attachments used to generate a response.</li><li><strong>Authentication providers:</strong> information needed for sign-in when you choose an external account.</li><li><strong>Email and infrastructure providers:</strong> delivery and hosting data needed to operate the Service.</li></ul><p>Each provider processes information under its own terms and privacy policy. Do not enter personal or confidential information unless necessary.</p></>
  },
  {
    id: "cookie", number: "4.", heading: "Cookies and local storage", body: <p>We use cookies and browser storage for sign-in sessions, security, language, appearance, and other preferences. Disabling them may prevent parts of the Service from working correctly.</p>
  },
  {
    id: "security", number: "5.", heading: "Security", body: <p>We use reasonable technical and organizational safeguards, including access controls, encrypted communications, password hashing, and monitoring. No internet service can guarantee absolute security.</p>
  },
  {
    id: "retention", number: "6.", heading: "Retention and deletion", body: <><p>We retain account information and saved content while your account remains active and as needed to provide the Service. Security logs may be retained for a limited period.</p><p>You may delete content individually or delete your account from Settings. Some records may remain when required by law or in temporary backups until the normal backup cycle completes.</p></>
  },
  {
    id: "rights", number: "7.", heading: "Your choices and rights", body: <p>You may review and update profile information, manage or delete saved content, change language and other preferences, and delete your account. Contact us if you need help exercising applicable privacy rights.</p>
  },
  {
    id: "changes", number: "8.", heading: "Changes to this policy", body: <p>We may update this policy when the Service or legal requirements change. Material changes will be announced in the Service, and the revised policy takes effect when posted here.</p>
  },
  {
    id: "contact", number: "9.", heading: "Contact", body: <p>Questions or requests about this policy may be submitted through the contact channel linked from the Help Center.</p>
  }
];

// プライバシーポリシーページの構造化データ（WebPage・パンくず）
// Structured data for the privacy policy page (WebPage, breadcrumbs)
const privacyStructuredData = [
  {
    "@context": "https://schema.org",
    "@type": "WebPage",
    name: PRIVACY_TITLE,
    url: absoluteUrl("/privacy"),
    description: PRIVACY_DESCRIPTION,
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
      { "@type": "ListItem", position: 2, name: "プライバシーポリシー", item: absoluteUrl("/privacy") }
    ]
  }
];

// プライバシーポリシーページ / Privacy policy page
export default function PrivacyPage() {
  const { locale, t } = useTranslation();
  const english = locale === "en";
  const title = english ? "Privacy Policy | ChatCore-AI" : PRIVACY_TITLE;
  const description = english
    ? "How ChatCore-AI collects, uses, shares, retains, and deletes account information and user content."
    : PRIVACY_DESCRIPTION;
  const structuredData = privacyStructuredData.map((entry) => {
    if (entry["@type"] === "WebPage") return { ...entry, name: title, description, inLanguage: locale };
    if (entry["@type"] === "BreadcrumbList" && english) return { ...entry, itemListElement: [
      { "@type": "ListItem", position: 1, name: "Home", item: absoluteUrl("/") },
      { "@type": "ListItem", position: 2, name: "Privacy Policy", item: absoluteUrl("/privacy") }
    ] };
    return entry;
  });
  return (
    <>
      <SeoHead
        title={title}
        description={description}
        canonicalPath="/privacy"
        structuredData={structuredData}
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
        kicker={english ? "Protecting your information" : "個人情報の保護"}
        eyebrow="PRIVACY POLICY"
        title={english ? "Privacy Policy" : "プライバシーポリシー"}
        lead={english ? "ChatCore-AI collects and uses information only as needed to provide the Service. This page explains what we collect and how we handle it." : "ChatCore-AIは、利用者の情報を「サービスの提供に必要な範囲」でのみ取得・利用します。このページでは、取得する情報とその取り扱いについて説明します。"}
        meta={english ? ["Established: July 17, 2026", "Operator: Chat Core"] : [`制定日：${ESTABLISHED_DATE}`, "運営：Chat Core"]}
        summaryLabel={english ? "Key points" : "要点まとめ"}
        summary={english ? PRIVACY_SUMMARY_EN : PRIVACY_SUMMARY}
        summaryNote={english ? `This summary is provided for convenience. The full policy below controls. ${t("legal.japanesePrevails")}` : "※ この要約は理解を助けるためのものです。正式な内容は以下の本文が優先されます。"}
        sections={english ? PRIVACY_SECTIONS_EN : PRIVACY_SECTIONS}
      />
    </>
  );
}
