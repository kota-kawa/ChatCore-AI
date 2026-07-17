// ヘルプセンターのカテゴリ・FAQ定義。
// 回答はプレーンテキストで保持し、ページ表示とFAQPage構造化データの両方で使う。
// Help center category and FAQ definitions.
// Answers are stored as plain text and reused for both rendering and FAQPage structured data.

// FAQ回答内の補足リンク / Supplementary link inside an FAQ answer
export type HelpLink = {
  href: string;
  label: string;
  external?: boolean;
};

// FAQ1件分の型 / Type for a single FAQ entry
export type HelpQa = {
  question: string;
  answers: string[];
  link?: HelpLink;
};

// カテゴリ1件分の型 / Type for a single help category
export type HelpCategory = {
  id: string;
  icon: string;
  title: string;
  items: HelpQa[];
};

export const HELP_CATEGORIES: HelpCategory[] = [
  {
    id: "getting-started",
    icon: "bi-stars",
    title: "はじめての方へ",
    items: [
      {
        question: "ChatCore-AIは無料で使えますか？",
        answers: [
          "はい、アカウント登録も基本機能の利用もすべて無料です。クレジットカードの登録は不要です。",
          "将来有料の機能を提供する場合は、内容と料金を事前にサービス上でお知らせします。"
        ]
      },
      {
        question: "アカウント登録の方法を教えてください",
        answers: [
          "登録ページでメールアドレスとパスワードを入力する方法と、Googleアカウントでそのままログインする方法があります。どちらも数分で完了します。"
        ],
        link: { href: "/register", label: "新規登録ページへ" }
      },
      {
        question: "スマートフォンでも使えますか？",
        answers: [
          "はい、アプリのインストールは不要で、スマートフォン・タブレット・PCのブラウザからそのまま利用できます。画面は端末のサイズに合わせて自動で最適化されます。"
        ]
      }
    ]
  },
  {
    id: "chat",
    icon: "bi-chat-square-text",
    title: "AIチャット",
    items: [
      {
        question: "AIチャットの始め方を教えてください",
        answers: [
          "ログイン後のホーム画面で、入力欄に質問や相談したい内容を入力して送信するだけです。調べもの、文章の下書き、アイデア出しなど、日本語で自然に話しかけられます。"
        ],
        link: { href: "/", label: "AIチャットを開く" }
      },
      {
        question: "会話の履歴は保存されますか？",
        answers: [
          "はい、会話はアカウントに保存され、あとから見返したり続きから再開したりできます。不要になった会話は削除できます。"
        ]
      },
      {
        question: "AIの回答はどのくらい正確ですか？",
        answers: [
          "AIの応答には誤りが含まれることがあります。特に最新の出来事や専門的な内容については、重要な判断の前に情報源を確認することをおすすめします。",
          "医療・法律・金融など専門的な判断が必要な事項は、専門家にご相談ください。"
        ]
      }
    ]
  },
  {
    id: "prompt-memo",
    icon: "bi-journal-text",
    title: "プロンプト共有・メモ",
    items: [
      {
        question: "プロンプト共有とはどんな機能ですか？",
        answers: [
          "他のユーザーが作った便利なプロンプト（AIへの指示文）を探したり、自分のプロンプトを公開したりできる機能です。公開したプロンプトは他のユーザーも閲覧・利用できるため、個人情報や機密情報は含めないようご注意ください。"
        ],
        link: { href: "/prompt_share", label: "プロンプト共有を見る" }
      },
      {
        question: "メモはどのように使えますか？",
        answers: [
          "チャットで得た回答や自分の考えをメモとして保存し、あとから整理・見返しができます。共有リンクを発行して、特定のメモを他の人に見せることもできます。"
        ],
        link: { href: "/memo", label: "メモを開く" }
      }
    ]
  },
  {
    id: "account",
    icon: "bi-person-gear",
    title: "アカウントとセキュリティ",
    items: [
      {
        question: "パスワードを入力せずにログインできますか？",
        answers: [
          "はい、Passkey（パスキー）に対応しています。設定画面のセキュリティからPasskeyを追加すると、指紋・顔認証や端末のロック解除で安全にログインできます。"
        ]
      },
      {
        question: "登録したメールアドレスを変更したい",
        answers: [
          "ログイン後の設定画面にあるセキュリティの「メールアドレス変更」から行えます。現在のメールアドレスで確認したあと、新しいメールアドレスにも確認コードが届く2段階の流れで安全に変更できます。"
        ]
      },
      {
        question: "アカウントを削除するとデータはどうなりますか？",
        answers: [
          "設定画面の「アカウント削除」からいつでも削除できます。削除すると、保存されていた会話・メモ・プロンプトなどのデータも削除されます。詳しくはプライバシーポリシーをご覧ください。"
        ],
        link: { href: "/privacy#retention", label: "プライバシーポリシー：保存期間と削除" }
      }
    ]
  },
  {
    id: "troubleshooting",
    icon: "bi-tools",
    title: "トラブルシューティング",
    items: [
      {
        question: "ログインできません",
        answers: [
          "メールアドレスとパスワードに誤りがないかご確認ください。パスワードを忘れた場合は、ログインページからパスワードの再設定ができます。",
          "Googleアカウントで登録した場合は、同じGoogleアカウントの「Googleでログイン」をご利用ください。"
        ],
        link: { href: "/login", label: "ログインページへ" }
      },
      {
        question: "AIの応答が返ってこない・エラーになります",
        answers: [
          "一時的な混雑や通信状況の影響が考えられます。少し時間をおいてから再度お試しください。ページの再読み込みで解消することもあります。",
          "解消しない場合は、下記のお問い合わせ先までお知らせください。"
        ]
      }
    ]
  }
];
