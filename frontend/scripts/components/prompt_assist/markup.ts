import { PROMPT_ASSIST_TARGET_META } from "./constants";
import type { PromptAssistTarget } from "./types";

export function createPromptAssistMarkup(target: PromptAssistTarget) {
  const meta = PROMPT_ASSIST_TARGET_META[target];
  return `
    <section class="prompt-assist" data-assist-target="${target}" aria-label="AIによるプロンプト作成">
      <div class="prompt-assist__head">
        <span class="prompt-assist__icon" aria-hidden="true"><i class="bi bi-stars"></i></span>
        <div class="prompt-assist__head-copy">
          <strong class="prompt-assist__title" data-assist-title>${meta.title}</strong>
          <small class="prompt-assist__lead" data-assist-lead>${meta.lead}</small>
        </div>
      </div>
      <label class="prompt-assist__brief">
        <span class="prompt-assist__brief-label" data-assist-brief-label>${meta.briefLabel}</span>
        <textarea
          class="prompt-assist__brief-input"
          data-assist-brief
          rows="3"
          placeholder="${meta.briefPlaceholder}"
        ></textarea>
      </label>
      <div class="prompt-assist__run-row">
        <button type="button" class="prompt-assist__run" data-assist-run>
          <i class="bi bi-stars" aria-hidden="true"></i>
          <span>AIで作成</span>
        </button>
      </div>
      <div class="prompt-assist__loading" data-assist-loading hidden aria-live="polite">
        <span class="prompt-assist__spinner" aria-hidden="true"></span>
        <span>AIがプロンプトを作成しています…</span>
      </div>
      <p class="prompt-assist__status" data-assist-status hidden></p>
      <section class="prompt-assist__preview" data-assist-preview hidden aria-live="polite">
        <p class="prompt-assist__summary" data-assist-summary></p>
        <ul class="prompt-assist__warnings" data-assist-warnings hidden></ul>
        <div class="prompt-assist__result" data-assist-result></div>
        <div class="prompt-assist__preview-actions">
          <button type="button" class="prompt-assist__apply" data-assist-apply>
            <i class="bi bi-check2-circle" aria-hidden="true"></i>
            <span>反映する</span>
          </button>
          <button type="button" class="prompt-assist__retry" data-assist-retry>やり直す</button>
        </div>
      </section>
    </section>
  `;
}
