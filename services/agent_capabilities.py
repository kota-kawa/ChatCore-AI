from __future__ import annotations

import re
from dataclasses import dataclass


# エージェントアクションを定義するデータクラス
# Dataclass defining an agent action
@dataclass(frozen=True)
class AgentAction:
    label: str
    action: str
    target: str
    description: str


# エージェントページ情報を定義するデータクラス
# Dataclass defining agent page information
@dataclass(frozen=True)
class AgentPage:
    label: str
    path_pattern: re.Pattern[str]
    route: str
    summary: str
    features: tuple[str, ...]
    actions: tuple[AgentAction, ...]


# エージェントが実行可能なツール/コマンドを表すデータクラス
# Dataclass representing tools/commands executable by the agent
@dataclass(frozen=True)
class AgentTool:
    command: str
    description: str
    args: str
    verifies: str
    risk: str = "low"


# 全ページで共通で利用可能なグローバルアクションの定義
# Definition of global actions available across all pages
GLOBAL_ACTIONS: tuple[AgentAction, ...] = (
    AgentAction("チャットを開く", "navigate", "/", "メインのAIチャット画面へ移動する。"),
    AgentAction("プロンプト共有を開く", "navigate", "/prompt_share", "公開プロンプトの検索・投稿画面へ移動する。"),
    AgentAction("メモを開く", "navigate", "/memo", "保存済みメモの作成・閲覧画面へ移動する。"),
    AgentAction("設定を開く", "navigate", "/settings", "プロフィール、外観、Passkey、投稿したプロンプトへ移動する。"),
    AgentAction("ログインを開く", "navigate", "/login", "ログイン・登録画面へ移動する。"),
)

# エージェントが実行できるツールのリスト
# List of tools that the agent can execute
AGENT_TOOLS: tuple[AgentTool, ...] = (
    AgentTool("navigation.openPage", "ChatCore内の指定ページへ移動する。", '{"path": "/settings"}', "URLパスが指定値へ移動する。"),
    AgentTool("chat.fillSetupMessage", "チャット開始欄にメッセージを入力する。", '{"text": "相談内容"}', "#setup-info の値が text になる。"),
    AgentTool("chat.sendSetupMessage", "チャット開始欄の内容を送信する。", "{}", "送信ボタンをクリックできる。", risk="medium"),
    AgentTool("chat.openPromptComposer", "チャット画面の新規プロンプト作成モーダルを開く。", "{}", "#newPromptModal が表示される。"),
    AgentTool("chat.toggleTaskOrder", "タスク並び替え編集を切り替える。", "{}", "#edit-task-order-btn をクリックできる。"),
    AgentTool("chat.showChatHistory", "これまでのチャット画面へ進む。", "{}", "#access-chat-btn をクリックできる。"),
    AgentTool("prompt.search", "プロンプト共有で検索語を入力して検索する。", '{"query": "メール返信"}', "#searchInput の値が query になり検索ボタンをクリックできる。"),
    AgentTool("prompt.openComposer", "プロンプト投稿モーダルを開く。", "{}", "#postModal が表示される。"),
    AgentTool("prompt.openLogin", "プロンプト共有ページのログイン/登録導線を開く。", "{}", "#login-btn をクリックできる。"),
    AgentTool("prompt.scrollResults", "プロンプト一覧へスクロールする。", "{}", "#prompt-feed-section へスクロールできる。"),
    AgentTool("settings.openSection", "設定ページの指定セクションを開く。", '{"section": "security"}', "指定 data-section のナビ項目をクリックできる。"),
    AgentTool("memo.fillForm", "メモ作成フォームへ値を入力する。", '{"ai_response": "...", "title": "..."}', "指定されたフォーム値が反映される。"),
    AgentTool("memo.save", "メモを保存する。", "{}", "保存ボタンをクリックできる。", risk="medium"),
)

# 実行可能なエージェントコマンドのセット
# Set of allowed agent commands
ALLOWED_AGENT_COMMANDS = frozenset(tool.command for tool in AGENT_TOOLS)

# エージェントコマンドのリスクレベルのマップ
# Map of risk levels for agent commands
AGENT_COMMAND_RISKS = {tool.command: tool.risk for tool in AGENT_TOOLS}


# アプリケーション内の全ページの定義リスト
# Definition list of all pages in the application
PAGES: tuple[AgentPage, ...] = (
    AgentPage(
        label="チャット",
        path_pattern=re.compile(r"^/$"),
        route="/",
        summary="AIと会話し、チャットルーム、タスクテンプレート、モデル選択、未保存チャットを使えるメイン画面。",
        features=(
            "入力欄に相談内容を書いて送信できる。",
            "AIモデルを選択できる。",
            "タスクカードをクリックして定型プロンプトを即実行できる。",
            "新しいプロンプト/タスクを作成できる。",
            "タスクの並び替え、編集、削除、詳細表示ができる。",
            "ログイン中は過去のチャット履歴へ移動できる。",
        ),
        actions=(
            AgentAction("メッセージ入力", "input", "#setup-info", "チャット開始前の相談内容を入力する。"),
            AgentAction("メッセージ送信", "click", ".setup-send-btn", "入力内容をAIへ送信する。"),
            AgentAction("モデル選択", "click", ".model-select-trigger", "モデル選択メニューを開く。"),
            AgentAction("新規プロンプト作成", "click", "#openNewPromptModal", "新しいプロンプト作成モーダルを開く。"),
            AgentAction("タスク並び替え", "click", "#edit-task-order-btn", "タスクの並び順編集を切り替える。"),
            AgentAction("タスク一覧展開", "click", "#toggle-tasks-btn", "折りたたまれたタスク一覧を展開/収納する。"),
            AgentAction("チャット履歴", "click", "#access-chat-btn", "これまでのチャットを見る。"),
        ),
    ),
    AgentPage(
        label="プロンプト共有",
        path_pattern=re.compile(r"^/prompt_share/?$"),
        route="/prompt_share",
        summary="公開プロンプトを検索、カテゴリ絞り込み、詳細表示、保存、いいね、ブックマーク、共有、投稿できる画面。",
        features=(
            "キーワードで公開プロンプトを検索できる。",
            "カテゴリで絞り込める。",
            "プロンプト詳細を開いて本文や例を確認できる。",
            "ログイン中はプロンプトを投稿、保存、いいね、ブックマークできる。",
            "共有リンクを作成してコピーできる。",
        ),
        actions=(
            AgentAction("検索語入力", "input", "#searchInput", "公開プロンプトの検索キーワードを入力する。"),
            AgentAction("検索実行", "click", "#searchButton", "入力したキーワードで検索する。"),
            AgentAction("投稿モーダル", "click", "#heroOpenPostModal", "新しいプロンプト投稿モーダルを開く。"),
            AgentAction("ログイン", "click", "#login-btn", "ログイン/登録ページへ進む。"),
            AgentAction("結果へスクロール", "scroll", "#prompt-feed-section", "検索結果/プロンプト一覧へ移動する。"),
        ),
    ),
    AgentPage(
        label="投稿したプロンプト",
        path_pattern=re.compile(r"^/prompt_share/manage"),
        route="/prompt_share/manage",
        summary="自分の投稿プロンプトを管理する画面。",
        features=("投稿済みプロンプトの確認・編集・削除ができる。",),
        actions=(AgentAction("プロンプト共有へ戻る", "navigate", "/prompt_share", "公開プロンプト画面へ移動する。"),),
    ),
    AgentPage(
        label="メモ",
        path_pattern=re.compile(r"^/memo/?$"),
        route="/memo",
        summary="AIの回答をメモとして保存し、最近のメモの閲覧・コピー・共有ができる画面。",
        features=(
            "AI回答、タイトルを入力してメモ保存できる。",
            "最近のメモを開いて詳細を確認できる。",
            "メモ本文をコピーできる。",
            "共有リンクを作成してコピー/ネイティブ共有できる。",
        ),
        actions=(
            AgentAction("AI回答", "input", "[name='ai_response']", "保存したいAI回答を入力する。"),
            AgentAction("タイトル", "input", "[name='title']", "メモタイトルを入力する。"),
            AgentAction("メモ保存", "click", "button[type='submit']", "メモを保存する。"),
        ),
    ),
    AgentPage(
        label="設定",
        path_pattern=re.compile(r"^/settings/?$"),
        route="/settings",
        summary="プロフィール、外観テーマ、投稿したプロンプト、保存したプロンプト、通知、セキュリティ/Passkeyを管理する画面。",
        features=(
            "プロフィール、メール、自己紹介、AI向けプロフィール文脈を編集できる。",
            "ライト/ダーク/システム連動テーマを切り替えられる。",
            "投稿したプロンプトと保存したプロンプトを管理できる。",
            "Passkey登録と保存済みPasskey管理ができる。",
        ),
        actions=(
            AgentAction("プロフィール設定", "click", "[data-section='profile']", "プロフィール設定タブを開く。"),
            AgentAction("外観", "click", "[data-section='appearance']", "外観タブを開く。"),
            AgentAction("投稿したプロンプト", "click", "[data-section='prompts']", "投稿したプロンプトタブを開く。"),
            AgentAction("保存したプロンプト", "click", "[data-section='prompt-list']", "保存したプロンプトタブを開く。"),
            AgentAction("通知設定", "click", "[data-section='notifications']", "通知設定タブを開く。"),
            AgentAction("セキュリティ", "click", "[data-section='security']", "セキュリティ/Passkeyタブを開く。"),
        ),
    ),
    AgentPage(
        label="ログイン",
        path_pattern=re.compile(r"^/login/?$"),
        route="/login",
        summary="メール認証、Google認証、Passkeyでログイン/登録する画面。",
        features=("メールアドレスで認証コードを受け取れる。", "GoogleログインとPasskeyログインを使える。"),
        actions=(
            AgentAction("メール入力", "input", "#email", "ログイン用メールアドレスを入力する。"),
            AgentAction("Googleログイン", "click", "#googleAuthBtn", "Google認証を開始する。"),
            AgentAction("認証コード送信", "click", ".submit-btn", "メール認証コードを送る。"),
        ),
    ),
)


# 指定されたURLパスに一致するエージェントページ情報を取得する
# Retrieve the agent page information that matches the specified URL path
def get_page_capability(pathname: str) -> AgentPage | None:
    # 登録されたページ定義を走査して、正規表現パターンにマッチするか判定する
    # Iterate through registered page definitions to check if they match the regular expression pattern
    for page in PAGES:
        if page.path_pattern.search(pathname or ""):
            return page
    return None


# エージェント向けの機能カタログ・コンテキスト文字列を組み立てる
# Construct the capability catalog context string for the agent
def build_capability_context(pathname: str = "") -> str:
    # 現在のパスに対応するページ情報を取得する
    # Get page information corresponding to the current path
    current = get_page_capability(pathname)
    lines = ["【ChatCore 機能カタログ】"]
    lines.append("全ページ共通: 左下のAIエージェントから、現在ページの説明、機能案内、画面操作の提案/実行ができます。")
    lines.append("主要ページ:")
    # 各ページの情報をテキスト化して追加する
    # Textify and add information for each page
    for page in PAGES:
        marker = "（現在のページ）" if current == page else ""
        lines.append(f"- {page.label} {page.route}{marker}: {page.summary}")
        for feature in page.features:
            lines.append(f"  - {feature}")

    lines.append("\n共通ナビゲーション:")
    # グローバルアクションの情報を追加する
    # Add information for global actions
    for action in GLOBAL_ACTIONS:
        lines.append(f"- {action.label}: action={action.action}, target={action.target}, {action.description}")

    lines.append("\n型付きアクションAPI（CSSセレクタより優先して使う）:")
    # エージェントツールの情報を追加する
    # Add information for agent tools
    for tool in AGENT_TOOLS:
        lines.append(
            f"- command={tool.command}; args={tool.args}; risk={tool.risk}; "
            f"{tool.description} 検証: {tool.verifies}"
        )

    # 現在のページで利用可能な特定アクションを追加する
    # Add specific actions available on the current page
    if current:
        lines.append(f"\n現在ページで優先して使える操作: {current.label}")
        for action in current.actions:
            lines.append(
                f"- {action.label}: action={action.action}, target={action.target}, {action.description}"
            )
    return "\n".join(lines)
