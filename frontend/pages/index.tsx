import Head from "next/head";
import { useEffect } from "react";
import defaultTasks from "../data/default_tasks.json";

type DefaultTask = {
  name?: string;
  prompt_template?: string;
  response_rules?: string;
  output_skeleton?: string;
  input_examples?: string;
  output_examples?: string;
};

type TaskCardProps = {
  task: DefaultTask;
};

function normalizeTaskName(task: DefaultTask) {
  if (typeof task.name === "string" && task.name.trim()) {
    return task.name.trim();
  }
  if (task.name !== undefined && task.name !== null) {
    return String(task.name);
  }
  return "無題";
}

function TaskCard({ task }: TaskCardProps) {
  const taskName = normalizeTaskName(task);
  const promptTemplate = task.prompt_template || "プロンプトテンプレートはありません";
  const responseRules = task.response_rules || "";
  const outputSkeleton = task.output_skeleton || "";
  const inputExamples = task.input_examples || "";
  const outputExamples = task.output_examples || "";

  return (
    <div className="task-wrapper">
      <div
        className="prompt-card"
        data-task={taskName}
        data-prompt_template={promptTemplate}
        data-response_rules={responseRules}
        data-output_skeleton={outputSkeleton}
        data-input_examples={inputExamples}
        data-output_examples={outputExamples}
        data-is_default="true"
      >
        <div className="header-container">
          <div className="task-header">{taskName}</div>
          <button type="button" className="btn btn-outline-success btn-md task-detail-toggle">
            <i className="bi bi-caret-down"></i>
          </button>
        </div>
      </div>
    </div>
  );
}

function SetupContainer() {
  return (
    <div id="setup-container">
      <form className="setup-form" id="setup-form">
        <h2 style={{ textAlign: "center", marginBottom: "1.5rem" }}>Chat Core</h2>

        <div className="form-group">
          <label className="form-label">現在の状況・作業環境（入力なしでもOK）</label>
          <textarea
            id="setup-info"
            rows={4}
            placeholder="例：大学生、リモートワーク中　／　自宅のデスク、周囲は静か"
          ></textarea>
        </div>

        <div className="form-group">
          <label className="form-label">AIモデル選択</label>
          <select id="ai-model" defaultValue="openai/gpt-oss-120b">
            <option value="openai/gpt-oss-120b">
              GROQ | GPT-OSS 120B（標準・高品質な応答）
            </option>
            <option value="gpt-5-mini-2025-08-07">
              OPENAI | GPT-5 MINI（高品質・推論が必要な作業向け）
            </option>
            <option value="gemini-2.5-flash">GEMINI | 2.5 FLASH（軽い作業向け）</option>
          </select>
        </div>

        <div className="task-selection-header">
          <p id="task-selection-text">実行したいタスクを選択（クリックで即実行）</p>
          <button
            id="openNewPromptModal"
            className="circle-button new-prompt-modal-btn"
            type="button"
            data-tooltip="新しいプロンプトを作成"
            data-tooltip-placement="bottom"
            style={{ display: "none" }}
          >
            <i className="bi bi-plus-lg"></i>
          </button>
        </div>

        <div className="task-selection tasks-collapsed" id="task-selection">
          {(defaultTasks as DefaultTask[]).map((task, index) => (
            <TaskCard key={`${normalizeTaskName(task)}-${index}`} task={task} />
          ))}
        </div>

        <div style={{ textAlign: "center", marginTop: "0.2rem" }}>
          <button id="access-chat-btn" type="button" className="primary-button" style={{ display: "none" }}>
            <i className="bi bi-chat-left-text"></i> これまでのチャットを見る
          </button>
        </div>
      </form>
    </div>
  );
}

function TaskDetailModal() {
  return (
    <div
      id="io-modal"
      style={{ display: "none" }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="taskDetailTitle"
      aria-hidden="true"
      tabIndex={-1}
    >
      <div className="io-modal-content" id="io-modal-content"></div>
    </div>
  );
}

function ChatContainer() {
  return (
    <div id="chat-container" style={{ display: "none" }}>
      <div className="chat-header">
        <div className="header-left">
          <button
            id="back-to-setup"
            className="icon-button"
            data-tooltip="タスク選択に戻る"
            data-tooltip-placement="bottom"
          >
            <i className="bi bi-arrow-left"></i>
          </button>
          <span>Chat Core</span>
        </div>
        <div className="header-right">
          <button
            id="share-chat-btn"
            className="icon-button chat-share-btn"
            type="button"
            data-tooltip="このチャットを共有"
            data-tooltip-placement="bottom"
          >
            <i className="bi bi-share"></i>
          </button>
        </div>
      </div>

      <div className="chat-main">
        <div className="sidebar" id="chat-room-sidebar">
          <button id="new-chat-btn" className="new-chat-btn">
            <i className="bi bi-plus-lg"></i> 新規チャット
          </button>
          <div id="chat-room-list"></div>
        </div>

        <div className="chat-area">
          <button
            id="sidebar-toggle"
            className="icon-button sidebar-toggle chat-sidebar-toggle"
            data-tooltip="チャット一覧を表示"
            data-tooltip-placement="left"
          >
            <i className="bi bi-arrow-bar-right"></i>
          </button>

          <div className="chat-messages" id="chat-messages"></div>

          <div className="input-container">
            <div className="input-wrapper">
              <input type="text" id="user-input" placeholder="メッセージを入力..." />
              <button
                type="button"
                id="send-btn"
                aria-label="送信"
                data-tooltip="メッセージを送信"
                data-tooltip-placement="top"
              >
                <i className="bi bi-send"></i>
              </button>
            </div>
          </div>

          <chat-action-menu></chat-action-menu>
        </div>
      </div>
    </div>
  );
}

function NewPromptModal() {
  return (
    <div id="newPromptModal" className="new-prompt-modal" style={{ display: "none" }}>
      <div className="new-prompt-modal-content">
        <button
          type="button"
          className="new-modal-close-btn"
          id="newModalCloseBtn"
          aria-label="モーダルを閉じる"
        >
          &times;
        </button>

        <div className="new-prompt-modal__hero">
          <div className="new-prompt-modal__hero-copy">
            <p className="new-prompt-modal__eyebrow">Prompt Composer</p>
            <h2>新しいプロンプトを追加</h2>
            <p className="new-prompt-modal__lead">
              AI 補助を使いながら、短時間で実用的なタスクに整えられます。
            </p>
          </div>
          <div className="new-prompt-modal__hero-badges" aria-hidden="true">
            <span>Draft</span>
            <span>Polish</span>
            <span>Examples</span>
          </div>
        </div>

        <form className="new-post-form" id="newPostForm">
          <div className="form-group">
            <label htmlFor="new-prompt-title">タイトル</label>
            <input type="text" id="new-prompt-title" placeholder="プロンプトのタイトルを入力" required />
          </div>

          <div className="form-group">
            <label htmlFor="new-prompt-content">プロンプト内容</label>
            <textarea
              id="new-prompt-content"
              rows={5}
              placeholder="具体的なプロンプト内容を入力"
              required
            ></textarea>
          </div>

          <div id="newPromptAssistRoot"></div>
          <p id="newPromptSubmitStatus" className="composer-status" hidden></p>

          <div className="form-group form-group--toggle">
            <label className="composer-toggle" htmlFor="new-guardrail-checkbox">
              <input type="checkbox" id="new-guardrail-checkbox" />
              <span className="composer-toggle__copy">
                <strong>入出力例を追加する</strong>
                <small>AI 提案の再現性を高めるための例を持たせます。</small>
              </span>
            </label>
          </div>

          <div id="new-guardrail-fields">
            <div className="form-group">
              <label htmlFor="new-prompt-input-example">入力例（プロンプト内容とは別にしてください）</label>
              <textarea
                id="new-prompt-input-example"
                rows={3}
                placeholder="例: 夏休みの思い出をテーマにした短いエッセイを書いてください。"
              ></textarea>
            </div>
            <div className="form-group">
              <label htmlFor="new-prompt-output-example">出力例</label>
              <textarea
                id="new-prompt-output-example"
                rows={3}
                placeholder="例: 夏休みのある日、私は家族と一緒に海辺へ出かけました..."
              ></textarea>
            </div>
          </div>

          <button type="submit" className="submit-btn">
            <i className="bi bi-upload"></i> 投稿する
          </button>
        </form>
      </div>
    </div>
  );
}

function TaskEditModal() {
  return (
    <div id="taskEditModal" className="custom-modal" style={{ display: "none" }}>
      <div className="custom-modal-dialog">
        <div className="custom-modal-content">
          <div className="custom-modal-header">
            <h5 className="custom-modal-title">タスク編集</h5>
            <button type="button" className="custom-modal-close" id="closeTaskEditModal">
              ×
            </button>
          </div>

          <div className="custom-modal-body">
            <form id="taskEditForm">
              <div className="custom-form-group">
                <label htmlFor="taskName" className="custom-form-label">
                  <span style={{ color: "green" }}>タイトル</span>
                </label>
                <input
                  type="text"
                  className="custom-form-control"
                  id="taskName"
                  name="name"
                  placeholder="例：メール作成"
                />
                <div className="custom-form-text">タスクの名前を入力してください。</div>
              </div>

              <div className="custom-form-group">
                <label htmlFor="promptTemplate" className="custom-form-label">
                  <span style={{ color: "green" }}>プロンプトテンプレート</span>
                </label>
                <textarea
                  className="custom-form-control"
                  id="promptTemplate"
                  name="prompt_template"
                  rows={2}
                  placeholder="例：メール本文の書き出し..."
                ></textarea>
                <div className="custom-form-text">タスク実行時に使用するプロンプトテンプレートです。</div>
              </div>

              <div className="custom-form-group">
                <label htmlFor="responseRules" className="custom-form-label">
                  <span style={{ color: "green" }}>回答ルール</span>
                </label>
                <textarea
                  className="custom-form-control"
                  id="responseRules"
                  name="response_rules"
                  rows={2}
                  placeholder="例：不足情報があれば先に確認する。結論から先に書く。"
                ></textarea>
                <div className="custom-form-text">回答時に優先させたいルールを任意で指定します。</div>
              </div>

              <div className="custom-form-group">
                <label htmlFor="outputSkeleton" className="custom-form-label">
                  <span style={{ color: "green" }}>出力テンプレート</span>
                </label>
                <textarea
                  className="custom-form-control"
                  id="outputSkeleton"
                  name="output_skeleton"
                  rows={2}
                  placeholder={"例：## 結論\n## 詳細\n## 次の一手"}
                ></textarea>
                <div className="custom-form-text">回答の骨組みを任意で指定します。</div>
              </div>

              <div className="custom-form-group">
                <label htmlFor="inputExamples" className="custom-form-label">
                  <span style={{ color: "green" }}>入力例</span>
                </label>
                <textarea
                  className="custom-form-control"
                  id="inputExamples"
                  name="input_examples"
                  rows={2}
                  placeholder="例：今日の天気は？"
                ></textarea>
                <div className="custom-form-text">ユーザーが入力する例です。</div>
              </div>

              <div className="custom-form-group">
                <label htmlFor="outputExamples" className="custom-form-label">
                  <span style={{ color: "green" }}>出力例</span>
                </label>
                <textarea
                  className="custom-form-control"
                  id="outputExamples"
                  name="output_examples"
                  rows={2}
                  placeholder="例：晴れです。"
                ></textarea>
                <div className="custom-form-text">タスク実行時の出力例です。</div>
              </div>
            </form>
          </div>

          <div className="custom-modal-footer">
            <button type="button" className="custom-btn-secondary" id="cancelTaskEditModal">
              キャンセル
            </button>
            <button type="button" className="custom-btn-primary" id="saveTaskChanges">
              保存
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function ChatShareModal() {
  return (
    <div
      id="chat-share-modal"
      className="chat-share-modal"
      role="dialog"
      aria-modal="true"
      aria-hidden="true"
      aria-labelledby="chat-share-title"
      style={{ display: "none" }}
    >
      <div className="chat-share-modal__content">
        <div className="chat-share-modal__header">
          <h5 id="chat-share-title">チャットを共有</h5>
          <button
            type="button"
            id="chat-share-close-btn"
            className="chat-share-close-btn"
            aria-label="共有モーダルを閉じる"
          >
            <i className="bi bi-x-lg"></i>
          </button>
        </div>

        <p className="chat-share-modal__desc">
          共有リンクを作成すると、このチャットルームの履歴をURL経由で閲覧できます。
        </p>

        <div className="chat-share-link-row">
          <input
            type="text"
            id="chat-share-link-input"
            readOnly
            placeholder="共有リンクを準備しています"
          />
        </div>

        <p id="chat-share-status" className="chat-share-status">
          共有するチャットルームを選択してください。
        </p>

        <div className="chat-share-actions">
          <button
            type="button"
            id="chat-share-copy-btn"
            className="primary-button chat-share-icon-btn"
            aria-label="リンクをコピー"
            title="リンクをコピー"
          >
            <i className="bi bi-files" aria-hidden="true"></i>
          </button>
          <button
            type="button"
            id="chat-share-web-btn"
            className="primary-button chat-share-icon-btn"
            aria-label="端末で共有"
            title="端末で共有"
          >
            <i className="bi bi-box-arrow-up-right" aria-hidden="true"></i>
          </button>
        </div>

        <div className="chat-share-sns">
          <a id="chat-share-sns-x" target="_blank" rel="noopener noreferrer" href="#">
            <svg className="share-x-icon" viewBox="0 0 24 24" aria-hidden="true">
              <path
                fill="currentColor"
                d="M18.901 1.153h3.68l-8.04 9.188L24 22.847h-7.406l-5.8-7.584-6.63 7.584H.48l8.6-9.83L0 1.154h7.594l5.243 6.932L18.901 1.153Zm-1.291 19.49h2.039L6.486 3.24H4.298L17.61 20.643Z"
              ></path>
            </svg>
            <span>X</span>
          </a>
          <a id="chat-share-sns-line" target="_blank" rel="noopener noreferrer" href="#">
            <i className="bi bi-chat-dots"></i>
            <span>LINE</span>
          </a>
          <a id="chat-share-sns-facebook" target="_blank" rel="noopener noreferrer" href="#">
            <i className="bi bi-facebook"></i>
            <span>Facebook</span>
          </a>
        </div>
      </div>
    </div>
  );
}

function HomePageContent() {
  return (
    <>
      <action-menu></action-menu>

      <div
        id="auth-buttons"
        style={{ display: "none", position: "fixed", top: 10, right: 10, zIndex: 2000 }}
      >
        <button id="login-btn" className="auth-btn">
          <i className="bi bi-person-circle"></i>
          <span>ログイン / 登録</span>
        </button>
      </div>

      <user-icon id="userIcon" style={{ display: "none" }}></user-icon>

      <SetupContainer />
      <TaskDetailModal />
      <ChatContainer />
      <NewPromptModal />
      <TaskEditModal />
      <ChatShareModal />
    </>
  );
}

export default function HomePage() {
  useEffect(() => {
    document.body.classList.add("chat-page");
    import("../scripts/entries/chat");
    return () => {
      document.body.classList.remove("chat-page");
      document.body.classList.remove("sidebar-visible");
    };
  }, []);

  return (
    <>
      <Head>
        <meta charSet="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
        <title>ChatCore-AI</title>
        <link rel="icon" type="image/webp" href="/static/favicon.webp" />
        <link rel="icon" type="image/png" href="/static/favicon.png" />
        <link rel="apple-touch-icon" sizes="180x180" href="/static/apple-touch-icon.png" />
      </Head>
      <div className="chat-page-shell">
        <HomePageContent />
      </div>
    </>
  );
}
