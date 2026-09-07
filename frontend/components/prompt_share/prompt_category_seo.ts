import type { Locale } from "../../lib/i18n/config";
import { localizePublicPath, localizedAbsoluteUrl } from "../../lib/seo";
import {
  getCategoryLabel,
  PROMPT_CATEGORY_KEYS
} from "../../scripts/prompt_share/prompt_category_registry";

// カテゴリ別の公開ページに掲載する、検索意図に対応した説明文。
// Search-intent focused copy used by each public category page.
export type PromptCategorySeoCopy = {
  title: string;
  heading: string;
  description: string;
  intro: string;
  examplesHeading: string;
  examples: readonly string[];
  tipHeading: string;
  tip: string;
};

type LocalizedPromptCategorySeoCopy = Record<Locale, PromptCategorySeoCopy>;

// カテゴリはレジストリの安定キーで管理し、ラベル変更や表示言語の追加でURLを変えない。
// Stable registry keys keep URLs unchanged when labels or display languages change.
export const PROMPT_CATEGORY_SEO_COPY: Record<string, LocalizedPromptCategorySeoCopy> = {
  writing: {
    ja: {
      title: "文章作成のAIプロンプト | Chat Coreプロンプト共有",
      heading: "文章作成に使えるAIプロンプト",
      description: "メール、記事、企画書、要約などの文章作成に役立つAIプロンプトを探せます。実用的な例を読んで、自分の用途に合わせて使えます。",
      intro: "文章の目的、読み手、トーンをAIに伝え、書き始めから推敲までの作業を整えるカテゴリです。短い依頼から複雑な構成づくりまで、再利用しやすい指示文を集めています。",
      examplesHeading: "文章作成で探せるプロンプトの例",
      examples: ["ビジネスメールを丁寧で簡潔に書き直す", "記事の構成と見出しを作る", "長い文章を要点を残して要約する"],
      tipHeading: "文章作成プロンプトを使うコツ",
      tip: "誰に向けた文章か、目的、文字数、文体を最初に指定すると、修正の少ない出力を得やすくなります。"
    },
    en: {
      title: "AI Writing Prompts | Chat Core Prompt Library",
      heading: "AI prompts for writing",
      description: "Find AI prompts for emails, articles, proposals, summaries, and other writing tasks. Review practical examples and adapt them to your own work.",
      intro: "This category helps you tell an AI the purpose, audience, and tone of a piece of writing, from the first draft through revision. Browse reusable instructions for simple requests and detailed structures.",
      examplesHeading: "Writing prompt examples",
      examples: ["Rewrite a business email to be clear and polite", "Create an article outline and headings", "Summarize a long document without losing its key points"],
      tipHeading: "How to use writing prompts",
      tip: "State the audience, purpose, length, and tone up front. Clear constraints usually produce an answer that needs less editing."
    }
  },
  coding: {
    ja: {
      title: "開発・プログラミングのAIプロンプト | Chat Core",
      heading: "開発・プログラミングに使えるAIプロンプト",
      description: "コード生成、レビュー、デバッグ、設計整理に使えるAIプロンプトを探せます。開発作業を効率化する再利用可能な指示文を集めています。",
      intro: "実装したい機能やエラーの状況を整理し、AIからコード・設計案・改善点を引き出すカテゴリです。言語やフレームワークを指定したプロンプトも見つけられます。",
      examplesHeading: "開発で探せるプロンプトの例",
      examples: ["既存コードを読みやすくリファクタリングする", "エラーログから原因と修正案を整理する", "APIやデータモデルの設計をレビューする"],
      tipHeading: "開発プロンプトを使うコツ",
      tip: "対象コード、実行環境、期待する挙動、制約を一緒に渡し、変更範囲とテスト方法も指定すると安全に進められます。"
    },
    en: {
      title: "AI Coding and Development Prompts | Chat Core",
      heading: "AI prompts for coding and development",
      description: "Find AI prompts for code generation, reviews, debugging, and design work. Reusable instructions can help you move through development tasks faster.",
      intro: "Use this category to describe a feature or error clearly and ask an AI for code, design ideas, or improvements. You can find prompts tailored to languages and frameworks.",
      examplesHeading: "Development prompt examples",
      examples: ["Refactor existing code for readability", "Turn an error log into likely causes and fixes", "Review an API or data model design"],
      tipHeading: "How to use coding prompts",
      tip: "Include the relevant code, runtime, expected behavior, and constraints. Ask for the change scope and tests to keep the work controlled."
    }
  },
  business: {
    ja: {
      title: "仕事・ビジネスのAIプロンプト | Chat Core",
      heading: "仕事・ビジネスに使えるAIプロンプト",
      description: "会議、企画、営業、資料作成など仕事に役立つAIプロンプトを探せます。日々の業務を整理し、成果物を早く形にできます。",
      intro: "会議の準備や情報整理、提案のたたき台づくりなど、仕事の考える時間を短くするカテゴリです。チームで共有しやすい実務向けのプロンプトを集めています。",
      examplesHeading: "仕事で探せるプロンプトの例",
      examples: ["会議メモから決定事項と担当を抽出する", "顧客向け提案書の骨子を作る", "業務の手順をわかりやすく文書化する"],
      tipHeading: "仕事のプロンプトを使うコツ",
      tip: "最終成果物の形式、読み手、期限、守るべき社内ルールを明示すると、実務にそのまま使いやすい回答になります。"
    },
    en: {
      title: "AI Work and Business Prompts | Chat Core",
      heading: "AI prompts for work and business",
      description: "Find AI prompts for meetings, planning, sales, and business documents. Organize everyday work and turn ideas into useful deliverables faster.",
      intro: "This category shortens the thinking time around meeting preparation, information organization, and proposal drafts. The prompts are practical and easy to share with a team.",
      examplesHeading: "Business prompt examples",
      examples: ["Extract decisions and owners from meeting notes", "Build an outline for a customer proposal", "Document a work process so others can follow it"],
      tipHeading: "How to use business prompts",
      tip: "Specify the deliverable format, audience, deadline, and internal rules. Those details make the output easier to use in real work."
    }
  },
  learning: {
    ja: {
      title: "学習・教育のAIプロンプト | Chat Core",
      heading: "学習・教育に使えるAIプロンプト",
      description: "勉強計画、理解の確認、教材づくりに役立つAIプロンプトを探せます。自分の理解度に合わせた学び方を考えるために使えます。",
      intro: "難しい内容をかみくだいたり、問題を作ったり、学習の進み方を振り返ったりするカテゴリです。学ぶ人にも教える人にも役立つプロンプトを集めています。",
      examplesHeading: "学習で探せるプロンプトの例",
      examples: ["難しい用語を身近な例で説明する", "目標と空き時間から勉強計画を作る", "理解度を確認する練習問題を作る"],
      tipHeading: "学習プロンプトを使うコツ",
      tip: "現在の理解度と、答えをすぐに見たいか自分で考えたいかを伝えると、学習に合ったヒントの出し方になります。"
    },
    en: {
      title: "AI Learning and Education Prompts | Chat Core",
      heading: "AI prompts for learning and education",
      description: "Find AI prompts for study plans, comprehension checks, and teaching materials. Use them to shape a learning approach around your current level.",
      intro: "Use this category to simplify difficult ideas, create exercises, and reflect on your progress. The prompts are useful for learners and educators alike.",
      examplesHeading: "Learning prompt examples",
      examples: ["Explain a difficult term with a familiar example", "Build a study plan from a goal and available time", "Create practice questions to check understanding"],
      tipHeading: "How to use learning prompts",
      tip: "Share your current level and whether you want a direct answer or time to think. The AI can then adjust the hints and explanation."
    }
  },
  research: {
    ja: {
      title: "調査・分析のAIプロンプト | Chat Core",
      heading: "調査・分析に使えるAIプロンプト",
      description: "情報収集、比較、論点整理、データの読み解きに使えるAIプロンプトを探せます。調査の観点をそろえ、考える材料を整理できます。",
      intro: "調べたい問いを分解し、複数の情報を比較しながら結論までの論点を整理するカテゴリです。調査の抜け漏れを減らすための指示文を集めています。",
      examplesHeading: "調査・分析で探せるプロンプトの例",
      examples: ["複数の選択肢を同じ基準で比較する", "記事や資料から主張と根拠を抜き出す", "データの傾向と追加で確認すべき点を整理する"],
      tipHeading: "調査プロンプトを使うコツ",
      tip: "対象範囲、比較軸、出典の扱い、判断に使う基準を最初に定め、事実と推測を分けて出すよう依頼してください。"
    },
    en: {
      title: "AI Research and Analysis Prompts | Chat Core",
      heading: "AI prompts for research and analysis",
      description: "Find AI prompts for information gathering, comparisons, issue mapping, and data interpretation. Structure the angles of an investigation and organize evidence.",
      intro: "Break a question into parts, compare sources or options, and organize the reasoning that leads to a conclusion. These prompts help reduce gaps in research.",
      examplesHeading: "Research prompt examples",
      examples: ["Compare several options using the same criteria", "Extract claims and evidence from articles or reports", "Identify data trends and questions that need follow-up"],
      tipHeading: "How to use research prompts",
      tip: "Define the scope, comparison axes, source expectations, and decision criteria. Ask the AI to separate facts from inferences."
    }
  },
  ideation: {
    ja: {
      title: "アイデア・企画のAIプロンプト | Chat Core",
      heading: "アイデア・企画に使えるAIプロンプト",
      description: "企画の発想、ブレインストーミング、施策の整理に役立つAIプロンプトを探せます。考えを広げ、実行できる案へ絞り込めます。",
      intro: "思いつきを増やし、視点を変え、実現性や効果を比べながら企画を形にするカテゴリです。ひとりで考えるときにもチームで議論するときにも使えます。",
      examplesHeading: "アイデア・企画で探せるプロンプトの例",
      examples: ["制約条件から複数の企画案を発想する", "アイデアを対象者と価値に分解する", "企画のリスクと検証方法を洗い出す"],
      tipHeading: "企画プロンプトを使うコツ",
      tip: "目的、対象者、使える資源、避けたいことを伝えたあと、発散と評価の段階を分けるとアイデアを扱いやすくなります。"
    },
    en: {
      title: "AI Ideation and Planning Prompts | Chat Core",
      heading: "AI prompts for ideas and planning",
      description: "Find AI prompts for brainstorming, planning, and organizing initiatives. Expand your thinking, then narrow ideas into actions you can test.",
      intro: "Generate possibilities, change perspectives, and shape a plan while comparing feasibility and impact. These prompts work for solo thinking and team discussions.",
      examplesHeading: "Ideation prompt examples",
      examples: ["Generate several plans from a set of constraints", "Break an idea down into audience and value", "List risks and ways to validate a plan"],
      tipHeading: "How to use ideation prompts",
      tip: "Give the goal, audience, available resources, and boundaries. Separate the divergent idea stage from the evaluation stage."
    }
  },
  creative: {
    ja: {
      title: "創作・ロールプレイのAIプロンプト | Chat Core",
      heading: "創作・ロールプレイに使えるAIプロンプト",
      description: "物語、キャラクター、世界観づくりやロールプレイに使えるAIプロンプトを探せます。創作の設定を広げ、表現を試せます。",
      intro: "登場人物の個性や物語の展開を考えたり、設定に沿った会話を楽しんだりするカテゴリです。創作の相棒として使える指示文を集めています。",
      examplesHeading: "創作で探せるプロンプトの例",
      examples: ["キャラクターの背景と行動原理を作る", "舞台設定に合う物語の展開を考える", "決めた役柄を保ったまま会話する"],
      tipHeading: "創作プロンプトを使うコツ",
      tip: "役割、舞台、雰囲気、避けたい表現を具体的に設定し、出力の長さや視点も決めると世界観を保ちやすくなります。"
    },
    en: {
      title: "AI Creative Writing and Role-play Prompts | Chat Core",
      heading: "AI prompts for creative work and role-play",
      description: "Find AI prompts for stories, characters, world-building, and role-play. Expand creative settings and explore different ways to express them.",
      intro: "Develop character traits and plot turns, or enjoy a conversation that stays inside a chosen setting. These prompts make the AI a creative partner.",
      examplesHeading: "Creative prompt examples",
      examples: ["Create a character background and motivations", "Develop a plot turn that fits a setting", "Hold a conversation while staying in character"],
      tipHeading: "How to use creative prompts",
      tip: "Set the role, setting, mood, and boundaries clearly. Choosing the output length and point of view helps preserve the world you are building."
    }
  },
  language: {
    ja: {
      title: "翻訳・語学のAIプロンプト | Chat Core",
      heading: "翻訳・語学に使えるAIプロンプト",
      description: "翻訳、英文チェック、会話練習、語彙学習に役立つAIプロンプトを探せます。目的やレベルに合う言語学習を進められます。",
      intro: "文章を自然な別言語へ置き換えたり、表現の違いを学んだり、会話を練習したりするカテゴリです。用途に合わせた言語の指示文を集めています。",
      examplesHeading: "翻訳・語学で探せるプロンプトの例",
      examples: ["相手と目的に合う自然な翻訳を作る", "外国語の文章を添削して理由を説明する", "旅行や仕事の場面を想定して会話練習する"],
      tipHeading: "語学プロンプトを使うコツ",
      tip: "学習レベル、地域、相手との関係、直訳と自然さのどちらを優先するかを指定すると、目的に合う表現になります。"
    },
    en: {
      title: "AI Translation and Language Prompts | Chat Core",
      heading: "AI prompts for translation and languages",
      description: "Find AI prompts for translation, proofreading, conversation practice, and vocabulary study. Learn in a way that matches your goal and level.",
      intro: "Translate writing naturally, learn differences in expression, or practice a conversation in context. Browse language instructions for a range of situations.",
      examplesHeading: "Language prompt examples",
      examples: ["Produce a natural translation for a specific audience", "Correct a foreign-language passage and explain why", "Practice a travel or workplace conversation"],
      tipHeading: "How to use language prompts",
      tip: "Specify your level, region, relationship with the reader, and whether literal accuracy or natural phrasing matters more."
    }
  },
  daily_life: {
    ja: {
      title: "暮らし・相談のAIプロンプト | Chat Core",
      heading: "暮らし・相談に使えるAIプロンプト",
      description: "日常の計画、家事、旅行、生活上の相談に使えるAIプロンプトを探せます。状況を整理して、現実的な選択肢を考えられます。",
      intro: "日々の予定や困りごとを整理し、無理なく実行できる選択肢を考えるカテゴリです。暮らしの小さな判断を言葉にする手助けになります。",
      examplesHeading: "暮らし・相談で探せるプロンプトの例",
      examples: ["予定と好みから旅行の計画を立てる", "家にある材料で献立を考える", "悩みを整理して次にできることを見つける"],
      tipHeading: "暮らしのプロンプトを使うコツ",
      tip: "予算、時間、場所、好み、避けたい条件を具体的に伝え、最後は自分で確認・判断する前提で選択肢を出してもらいましょう。"
    },
    en: {
      title: "AI Everyday Life and Advice Prompts | Chat Core",
      heading: "AI prompts for everyday life and advice",
      description: "Find AI prompts for daily planning, household tasks, travel, and life questions. Organize a situation and think through realistic options.",
      intro: "Turn everyday plans and small problems into clear options that fit your life. This category helps put practical decisions into words.",
      examplesHeading: "Everyday life prompt examples",
      examples: ["Plan a trip from a schedule and preferences", "Create meals from ingredients already at home", "Sort through a concern and identify next steps"],
      tipHeading: "How to use everyday life prompts",
      tip: "Include your budget, time, location, preferences, and boundaries. Use the options as input for your own final check and decision."
    }
  },
  hobby: {
    ja: {
      title: "趣味・エンタメのAIプロンプト | Chat Core",
      heading: "趣味・エンタメに使えるAIプロンプト",
      description: "ゲーム、音楽、映画、読書などの趣味を広げるAIプロンプトを探せます。おすすめ探しや感想の整理、遊び方の工夫に使えます。",
      intro: "好きな作品や遊びをもっと楽しむために、情報を整理したり新しい切り口を見つけたりするカテゴリです。趣味の時間を深めるプロンプトを集めています。",
      examplesHeading: "趣味・エンタメで探せるプロンプトの例",
      examples: ["好みから作品や遊びを提案する", "読んだ本や観た作品の感想を整理する", "趣味の練習メニューや上達計画を作る"],
      tipHeading: "趣味のプロンプトを使うコツ",
      tip: "好きなものの具体例、経験レベル、使える時間を伝えると、一般的なおすすめより自分に合った提案を得やすくなります。"
    },
    en: {
      title: "AI Hobby and Entertainment Prompts | Chat Core",
      heading: "AI prompts for hobbies and entertainment",
      description: "Find AI prompts for games, music, films, books, and other interests. Use them for recommendations, reflection, and better ways to enjoy a hobby.",
      intro: "Organize what you like, find a new angle, and make time for a favorite activity more rewarding. These prompts are built around everyday enjoyment.",
      examplesHeading: "Hobby prompt examples",
      examples: ["Recommend works or activities from your preferences", "Organize your thoughts about a book or film", "Create a practice routine or improvement plan"],
      tipHeading: "How to use hobby prompts",
      tip: "Give specific examples of what you like, your experience level, and your available time. The suggestions will be more personal than generic lists."
    }
  },
  other: {
    ja: {
      title: "その他のAIプロンプト | Chat Coreプロンプト共有",
      heading: "その他の用途に使えるAIプロンプト",
      description: "既存のカテゴリに当てはまらない用途のAIプロンプトを探せます。さまざまな試行錯誤から生まれた再利用可能な指示文を見つけられます。",
      intro: "新しい使い方や複数の目的にまたがるプロンプトを集めたカテゴリです。目的がはっきりしていないときも、公開例から使い道のヒントを探せます。",
      examplesHeading: "その他の用途で探せるプロンプトの例",
      examples: ["複数の作業を一つの手順にまとめる", "自分の状況に合う質問の形を作る", "新しいAIの使い方を試すための指示を作る"],
      tipHeading: "その他のプロンプトを使うコツ",
      tip: "まず達成したいことと完成形を言葉にし、入力例を一つ添えてからAIに不足している条件を質問させると整理しやすくなります。"
    },
    en: {
      title: "Other AI Prompts | Chat Core Prompt Library",
      heading: "AI prompts for other uses",
      description: "Find AI prompts for uses that do not fit another category. Explore reusable instructions created through a wide range of experiments.",
      intro: "This category collects new approaches and prompts that span several goals. When you are not sure where to start, public examples can suggest a direction.",
      examplesHeading: "Other prompt examples",
      examples: ["Combine several tasks into one repeatable procedure", "Shape a question around a specific situation", "Create an instruction for trying a new AI workflow"],
      tipHeading: "How to use other prompts",
      tip: "Describe the goal and finished form first, add one input example, and ask the AI to identify missing constraints."
    }
  }
};

export function isPromptCategoryKey(value: string): boolean {
  return PROMPT_CATEGORY_KEYS.includes(value);
}

export function getPromptCategorySeoCopy(category: string, locale: Locale): PromptCategorySeoCopy | null {
  return PROMPT_CATEGORY_SEO_COPY[category]?.[locale] ?? null;
}

export function getPromptCategoryPath(category: string, locale: Locale): string {
  return localizePublicPath(`/prompt_share/category/${encodeURIComponent(category)}`, locale);
}

export function getPromptCategoryUrl(category: string, locale: Locale): string {
  return localizedAbsoluteUrl(getPromptCategoryPath(category, locale), locale);
}

export function getPromptCategoryLabel(category: string, locale: Locale): string {
  return getCategoryLabel(category, locale);
}
