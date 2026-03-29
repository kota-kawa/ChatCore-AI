import Head from "next/head";
import Script from "next/script";
import { useEffect, useState } from "react";

function PromptManageHeader() {
  return (
    <header className="main-header">
      <div className="container">
        <h1 className="logo">Prompt Manager</h1>
      </div>
    </header>
  );
}

function PromptManageMain() {
  return (
    <main className="container main-container">
      <div className="header-bar">
        <h2 className="section-title">My Prompts</h2>
      </div>
      <div id="promptList" className="prompt-grid"></div>
    </main>
  );
}

function EditPromptModal() {
  return (
    <div id="editModal" className="modal" tabIndex={-1}>
      <div className="modal-dialog modal-dialog-centered modal-dialog-scrollable">
        <div className="modal-content">
          <div className="modal-header">
            <h5 className="modal-title">
              <i className="bi bi-pencil-square me-2"></i>プロンプト編集
            </h5>
            <button type="button" className="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>

          <div className="modal-body">
            <form id="editForm" className="modal-form">
              <input type="hidden" id="editPromptId" />

              <div className="form-group">
                <label htmlFor="editTitle" className="form-label">
                  タイトル
                </label>
                <input type="text" className="form-control input-field" id="editTitle" required />
              </div>

              <div className="form-group">
                <label htmlFor="editCategory" className="form-label">
                  カテゴリ
                </label>
                <input type="text" className="form-control input-field" id="editCategory" required />
              </div>

              <div className="form-group">
                <label htmlFor="editContent" className="form-label">
                  内容
                </label>
                <textarea className="form-control input-field" id="editContent" rows={5} required></textarea>
              </div>

              <div className="form-group">
                <label htmlFor="editInputExamples" className="form-label">
                  入力例
                </label>
                <textarea className="form-control input-field" id="editInputExamples" rows={3}></textarea>
              </div>

              <div className="form-group">
                <label htmlFor="editOutputExamples" className="form-label">
                  出力例
                </label>
                <textarea className="form-control input-field" id="editOutputExamples" rows={3}></textarea>
              </div>

              <div className="form-actions">
                <button type="submit" className="btn btn-primary w-100">
                  <i className="bi bi-save me-2"></i>更新する
                </button>
              </div>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}

function PromptManagePageContent() {
  return (
    <>
      <PromptManageHeader />
      <PromptManageMain />
      <EditPromptModal />
    </>
  );
}

export default function PromptManagePage() {
  const [bootstrapReady, setBootstrapReady] = useState(false);

  useEffect(() => {
    document.body.classList.add("prompt-manage-page");
    return () => {
      document.body.classList.remove("prompt-manage-page");
    };
  }, []);

  useEffect(() => {
    if (bootstrapReady) {
      import("../../scripts/entries/prompt_manage");
    }
  }, [bootstrapReady]);

  return (
    <>
      <Head>
        <meta charSet="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>マイプロンプト管理</title>
        <link rel="icon" type="image/webp" href="/static/favicon.webp" />
        <link rel="icon" type="image/png" href="/static/favicon.png" />
        <link
          href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"
          rel="stylesheet"
        />
        <link
          rel="stylesheet"
          href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.5/font/bootstrap-icons.css"
        />
        <link
          href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@300;400;500;600;700&display=swap"
          rel="stylesheet"
        />
        <link rel="stylesheet" href="/prompt_share/static/css/pages/prompt_manage.bundle.css" />
      </Head>

      <div className="prompt-manage-page">
        <PromptManagePageContent />
      </div>

      <Script
        src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"
        strategy="afterInteractive"
        onLoad={() => setBootstrapReady(true)}
      />
    </>
  );
}
