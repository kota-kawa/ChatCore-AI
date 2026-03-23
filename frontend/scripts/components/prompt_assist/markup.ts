import {
  PROMPT_ASSIST_ACTION_META,
  PROMPT_ASSIST_ACTION_ORDER,
  PROMPT_ASSIST_TARGET_META,
} from "./constants";
import type { PromptAssistTarget } from "./types";

export function createPromptAssistMarkup(panelId: string, target: PromptAssistTarget) {
  const targetMeta = PROMPT_ASSIST_TARGET_META[target];
  const actions = PROMPT_ASSIST_ACTION_ORDER.map((action) => {
    const meta = PROMPT_ASSIST_ACTION_META[action];
    return `
      <button
        type="button"
        class="prompt-assist__action"
        data-assist-action="${action}"
        data-accent="${meta.accent}"
      >
        <span class="prompt-assist__action-icon" aria-hidden="true">
          <i class="${meta.icon}"></i>
        </span>
        <span class="prompt-assist__action-label">${meta.label}</span>
      </button>
    `;
  }).join("");

  return `
    <section class="prompt-assist" data-assist-target="${target}" aria-label="AI入力補助">
      <button
        type="button"
        class="prompt-assist__toggle"
        data-assist-toggle
        aria-expanded="false"
        aria-controls="${panelId}"
        title="${targetMeta.toggleLabel}"
      >
        <span class="prompt-assist__toggle-glow" aria-hidden="true"></span>
        <span class="prompt-assist__toggle-icon" aria-hidden="true">
          <i class="bi bi-stars"></i>
        </span>
        <span class="prompt-assist__toggle-copy">
          <strong>AI Assist</strong>
          <small>磨く・補う・整える</small>
        </span>
        <span class="prompt-assist__toggle-ping" aria-hidden="true"></span>
      </button>
      <div class="prompt-assist__panel" id="${panelId}" data-assist-panel hidden>
        <div class="prompt-assist__panel-sheen" aria-hidden="true"></div>
        <div class="prompt-assist__hero">
          <div class="prompt-assist__hero-copy">
            <p class="prompt-assist__eyebrow">AI Input Assist</p>
            <h3 class="prompt-assist__title">${targetMeta.title}</h3>
            <p class="prompt-assist__lead">${targetMeta.lead}</p>
          </div>
          <div class="prompt-assist__hero-actions">
            <span class="prompt-assist__model">GPT OSS 20B</span>
            <button type="button" class="prompt-assist__close" data-assist-close aria-label="AI入力補助を閉じる">
              <i class="bi bi-x-lg"></i>
            </button>
          </div>
        </div>
        <section class="prompt-assist__meter" aria-label="入力状況">
          <div class="prompt-assist__meter-bar">
            <span class="prompt-assist__meter-fill" data-assist-meter-fill></span>
          </div>
          <div class="prompt-assist__meter-meta">
            <span class="prompt-assist__meter-label" data-assist-meter-label></span>
            <span class="prompt-assist__last-action" data-assist-last-action>入力を確認中</span>
          </div>
        </section>
        <div class="prompt-assist__state-list" data-assist-state-list></div>
        <div class="prompt-assist__actions">${actions}</div>
        <div class="prompt-assist__loading" data-assist-loading hidden aria-live="polite">
          <span class="prompt-assist__loading-orb" aria-hidden="true"></span>
          <div class="prompt-assist__loading-copy">
            <strong>AIが提案を生成中</strong>
            <span>入力の温度感を見ながら、使いやすい形に整えています。</span>
          </div>
        </div>
        <p class="prompt-assist__status" data-assist-status hidden></p>
        <section class="prompt-assist__preview" data-assist-preview hidden>
          <div class="prompt-assist__preview-header">
            <div>
              <p class="prompt-assist__preview-eyebrow">AI Suggestion</p>
              <p class="prompt-assist__summary" data-assist-summary></p>
            </div>
            <button type="button" class="prompt-assist__apply-all" data-assist-apply-all>提案をまとめて反映</button>
          </div>
          <ul class="prompt-assist__warnings" data-assist-warnings hidden></ul>
          <div class="prompt-assist__field-list" data-assist-field-list></div>
        </section>
      </div>
    </section>
  `;
}
