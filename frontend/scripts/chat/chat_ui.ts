// chat_ui.ts  – チャット画面 UI 共通ユーティリティ
// --------------------------------------------------
import hljs from "highlight.js";
import { Marked } from "marked";

import { getSharedDomRefs } from "../core/dom";
import { isRecord } from "../core/runtime_validation";
import { copyTextToClipboard, sanitizeMessageHtml } from "./message_utils";
import { refreshChatShareState } from "./chat_share";

type MarkedParseOptions = {
  async?: boolean;
  gfm?: boolean;
  breaks?: boolean;
};

let markedParser: ((markdown: string, options?: MarkedParseOptions) => string | Promise<string>) | null = null;
let memoMarkedParser: ((markdown: string, options?: MarkedParseOptions) => string | Promise<string>) | null = null;
let markdownEnhancementDisabled = false;
const CODE_COPY_BUTTON_SELECTOR = ".code-block-copy-btn";
const MARKED_HTML_CACHE_LIMIT = 160;
const botMarkdownHtmlCache = new Map<string, string>();
const userMarkdownHtmlCache = new Map<string, string>();
const memoMarkdownHtmlCache = new Map<string, string>();

function rememberMarkdownHtml(cache: Map<string, string>, key: string, value: string) {
  cache.set(key, value);
  if (cache.size <= MARKED_HTML_CACHE_LIMIT) return;
  const oldestKey = cache.keys().next().value;
  if (oldestKey) {
    cache.delete(oldestKey);
  }
}

function readMarkedCodeToken(token: unknown) {
  if (!isRecord(token)) {
    return { text: "", lang: "plaintext" };
  }
  return {
    text: typeof token.text === "string" ? token.text : "",
    lang: typeof token.lang === "string" ? token.lang : "plaintext"
  };
}

function stripInvisibleCharacters(value: string) {
  return value.replace(/[\u200B-\u200D\u2060\uFEFF]/g, "");
}

function escapeHtml(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function isStandaloneLabelLine(line: string) {
  return /^([^:：]{1,24})[：:]$/u.test(line.trim());
}

function toStandaloneLabel(line: string) {
  const match = line.trim().match(/^([^:：]{1,24})[：:]$/u);
  if (!match) return line;
  return `**${match[1].trim()}:**`;
}

function isStandaloneTitleLine(lines: string[], index: number) {
  const trimmed = lines[index].trim();
  if (!trimmed || trimmed.length < 4 || trimmed.length > 44) return false;
  if (/^(#{1,6}\s|[-*>\d`])/.test(trimmed)) return false;
  if (/[。.!?！？]$/.test(trimmed)) return false;

  const prev = index > 0 ? lines[index - 1].trim() : "";
  const next = index < lines.length - 1 ? lines[index + 1].trim() : "";
  if (prev !== "" || next !== "") return false;

  return /[一-龯ぁ-んァ-ヶA-Za-z0-9]/.test(trimmed);
}

function isLikelyKeyValueLine(line: string) {
  const trimmed = line.trim();
  if (!trimmed) return false;
  if (/^[-*>\d]/.test(trimmed)) return false;
  return /^([^:：]{1,24})[：:]\s+.+$/u.test(trimmed);
}

function toKeyValueBullet(line: string) {
  const trimmed = line.trim();
  const match = trimmed.match(/^([^:：]{1,24})[：:]\s+(.+)$/u);
  if (!match) return trimmed;
  const key = match[1].trim();
  const value = match[2].trim();
  return `- **${key}:** ${value}`;
}

function isStandaloneConclusionLine(line: string) {
  return /^(?:結論|まとめ|要約|回答)$/u.test(line.trim());
}

function collapseConsecutiveBlankLines(lines: string[], maxBlankLines = 1) {
  const output: string[] = [];
  let blankCount = 0;

  lines.forEach((line) => {
    if (line.trim().length === 0) {
      blankCount += 1;
      if (blankCount <= maxBlankLines) output.push("");
      return;
    }
    blankCount = 0;
    output.push(line);
  });

  return output;
}

function readBracedGroup(value: string, startIndex: number) {
  if (value[startIndex] !== "{") return null;

  let depth = 0;
  for (let index = startIndex; index < value.length; index += 1) {
    const char = value[index];
    if (char === "{") {
      depth += 1;
      continue;
    }
    if (char !== "}") continue;
    depth -= 1;
    if (depth === 0) {
      return {
        content: value.slice(startIndex + 1, index),
        endIndex: index + 1,
      };
    }
  }

  return null;
}

function replaceLatexFractions(value: string) {
  let output = value;
  for (let pass = 0; pass < 4; pass += 1) {
    const commandIndex = output.search(/\\d?frac\{/);
    if (commandIndex < 0) break;

    const command = output.startsWith("\\dfrac", commandIndex) ? "\\dfrac" : "\\frac";
    const numerator = readBracedGroup(output, commandIndex + command.length);
    if (!numerator) break;
    const denominator = readBracedGroup(output, numerator.endIndex);
    if (!denominator) break;

    output = [
      output.slice(0, commandIndex),
      `(${numerator.content})/(${denominator.content})`,
      output.slice(denominator.endIndex),
    ].join("");
  }
  return output;
}

function formatMathExpressionForDisplay(value: string) {
  return replaceLatexFractions(value)
    .replace(/\\left\s*/g, "")
    .replace(/\\right\s*/g, "")
    .replace(/\\begin\{cases\}/g, "{")
    .replace(/\\end\{cases\}/g, "")
    .replace(/\\\[\s*\d+(?:\.\d+)?(?:pt|em|ex|px)\s*\]/g, "")
    .replace(/\\\\/g, "")
    .replace(/\s*&\s*/g, "    ")
    .replace(/\\qquad/g, "    ")
    .replace(/\\quad/g, "  ")
    .replace(/\\lambda/g, "λ")
    .replace(/\\mu/g, "μ")
    .replace(/\\rho/g, "ρ")
    .replace(/\\sum/g, "∑")
    .replace(/\\leq?/g, "≤")
    .replace(/\\geq?/g, "≥")
    .replace(/\\neq/g, "≠")
    .replace(/\\infty/g, "∞")
    .replace(/\\cdot/g, "⋅")
    .replace(/\\times/g, "×")
    .replace(/,\s*/g, ", ")
    .replace(/\s{5,}/g, "    ")
    .trim();
}

function looksLikeLooseMathLine(line: string) {
  const trimmed = line.trim();
  if (!trimmed) return false;
  return (
    /\\(?:d?frac|sum|rho|lambda|mu|begin|end|leq?|geq?|left|right|qquad|quad)/.test(trimmed) ||
    /^[A-Za-z][A-Za-z0-9_{}^]*\s*=/.test(trimmed) ||
    /[_^].*=/.test(trimmed)
  );
}

function renderMathDisplay(lines: string[]) {
  const mathLines = lines.map((line) => formatMathExpressionForDisplay(line)).filter((line) => line.length > 0);
  if (mathLines.length === 0) return "";

  return [
    '<div class="math-display">',
    ...mathLines.map((line) => `<span class="math-line">${escapeHtml(line)}</span>`),
    "</div>",
  ].join("\n");
}

function isLooseMathBlockDelimiter(line: string, delimiter: "[" | "]") {
  const trimmed = line.trim();
  return trimmed === delimiter || trimmed === `\\${delimiter}`;
}

function normalizeLooseMathBlocks(lines: string[]) {
  const output: string[] = [];

  for (let index = 0; index < lines.length; index += 1) {
    if (!isLooseMathBlockDelimiter(lines[index], "[")) {
      output.push(lines[index]);
      continue;
    }

    let endIndex = index + 1;
    const mathLines: string[] = [];
    while (endIndex < lines.length && !isLooseMathBlockDelimiter(lines[endIndex], "]")) {
      mathLines.push(lines[endIndex]);
      endIndex += 1;
    }

    if (endIndex >= lines.length || !mathLines.some(looksLikeLooseMathLine)) {
      output.push(lines[index], ...mathLines);
      index = endIndex - 1;
      continue;
    }

    const rendered = renderMathDisplay(mathLines);
    if (rendered) {
      if (output.length > 0 && output[output.length - 1].trim() !== "") output.push("");
      output.push(rendered, "");
    }
    index = endIndex;
  }

  return output;
}

function normalizeLooseInlineMath(line: string) {
  return line.replace(/\(([A-Za-z][A-Za-z0-9_{}^=+\-*/\\]+)\)/g, (match, expression: string) => {
    if (!/[_^=\\]/.test(expression) || expression.length > 32) return match;
    return `<span class="math-inline">${escapeHtml(formatMathExpressionForDisplay(expression))}</span>`;
  });
}

type NormalizeMarkdownSegmentOptions = {
  preserveBlankLines?: boolean;
};

function normalizeMarkdownSegmentForDisplay(segment: string, options: NormalizeMarkdownSegmentOptions = {}) {
  const preserveBlankLines = options.preserveBlankLines === true;
  const normalizedSegment = segment
    .replace(/\u00a0/g, " ")
    .replace(/[\t ]+\n/g, "\n")
    .replace(/^[\t \u3000]+$/gm, "")
    .replace(/[\u200B-\u200D\u2060\uFEFF]/g, "")
    .replace(/\r\n?/g, "\n");
  const normalizedLines = (preserveBlankLines ? normalizedSegment : normalizedSegment.replace(/\n{3,}/g, "\n\n"))
    .split("\n")
    .map((line) => line.replace(/[ \t\u3000]+$/g, ""));

  const promotedLines = [...normalizedLines];

  for (let i = 0; i < promotedLines.length; i += 1) {
    const trimmed = promotedLines[i].trim();
    if (isStandaloneConclusionLine(trimmed)) {
      promotedLines[i] = `## ${trimmed}`;
      continue;
    }
    if (/^「[^」]{4,80}」$/.test(trimmed)) {
      promotedLines[i] = `### ${trimmed}`;
      continue;
    }
    if (isStandaloneTitleLine(promotedLines, i)) {
      promotedLines[i] = `## ${trimmed}`;
    }
  }

  const listifiedLines: string[] = [];
  for (let i = 0; i < promotedLines.length; ) {
    if (!isLikelyKeyValueLine(promotedLines[i])) {
      listifiedLines.push(promotedLines[i]);
      i += 1;
      continue;
    }

    let j = i;
    while (j < promotedLines.length && isLikelyKeyValueLine(promotedLines[j])) {
      j += 1;
    }

    if (j - i >= 2) {
      for (let k = i; k < j; k += 1) {
        listifiedLines.push(toKeyValueBullet(promotedLines[k]));
      }
    } else {
      listifiedLines.push(promotedLines[i]);
    }
    i = j;
  }

  const mathNormalizedLines = normalizeLooseMathBlocks(listifiedLines);
  const labeledLines = mathNormalizedLines.map((line) => {
    if (line.includes('class="math-display"') || line.includes('class="math-line"')) return line;
    const labeled = isStandaloneLabelLine(line) ? toStandaloneLabel(line) : line;
    return normalizeLooseInlineMath(labeled);
  });
  const compacted = preserveBlankLines ? labeledLines : collapseConsecutiveBlankLines(labeledLines, 1);
  const output = compacted.join("\n").replace(/^\n+/, "").trimEnd();
  return stripInvisibleCharacters(preserveBlankLines ? output : output.replace(/\n{3,}/g, "\n\n"));
}

function normalizeLLMTextForDisplay(rawText: string) {
  const normalized = rawText.replace(/\r\n?/g, "\n");
  const codeFencePattern = /(```[\s\S]*?```)/g;
  const parts = normalized.split(codeFencePattern);
  const formattedParts = parts
    .map((part, idx) => {
      if (!part) return "";
      // split() with capturing group: odd index is code fence
      if (idx % 2 === 1) return part.trim();
      return normalizeMarkdownSegmentForDisplay(part);
    })
    .filter((part) => part.length > 0);

  return formattedParts.join("\n\n").trim();
}

function normalizeMemoTextForDisplay(rawText: string) {
  const normalized = rawText.replace(/\r\n?/g, "\n");
  const codeFencePattern = /(```[\s\S]*?```)/g;
  const parts = normalized.split(codeFencePattern);
  const formattedParts = parts
    .map((part, idx) => {
      if (!part) return "";
      if (idx % 2 === 1) return part.trim();
      return preserveMemoPreviewBlankLines(normalizeMarkdownSegmentForDisplay(part, { preserveBlankLines: true }));
    })
    .filter((part) => part.length > 0);

  return formattedParts.join("\n\n").trim();
}

function preserveMemoPreviewBlankLines(markdown: string) {
  return markdown.replace(/\n{2,}/g, (newlines) => {
    const blankLineCount = Math.max(1, newlines.length - 1);
    const spacers = Array.from(
      { length: blankLineCount },
      () => '<div class="memo-preserved-blank-line"></div>'
    ).join("\n");
    return `\n\n${spacers}\n\n`;
  });
}

function normalizeUserTextForDisplay(rawText: string) {
  return stripInvisibleCharacters(
    rawText
      .replace(/\r\n?/g, "\n")
      .replace(/<br\s*\/?>/gi, "\n")
      .trimEnd()
  );
}

function formatMarkdownFallback(markdown: string) {
  const applyInlineMarkdownLite = (text: string) => {
    let html = escapeHtml(text);
    html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
    html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    return html;
  };

  const codeBlocks: string[] = [];
  let codeIndex = 0;
  const tokenized = markdown.replace(/```(?:[a-zA-Z0-9_-]+)?\n([\s\S]*?)```/g, (_, codeContent: string) => {
    const token = `@@CODE_BLOCK_${codeIndex}@@`;
    codeBlocks.push(`<pre><code>${escapeHtml((codeContent || "").trimEnd())}</code></pre>`);
    codeIndex += 1;
    return token;
  });

  const lines = tokenized.split("\n");
  const htmlParts: string[] = [];
  let listType: "ul" | "ol" | null = null;
  let paragraphOpen = false;

  const closeList = () => {
    if (!listType) return;
    htmlParts.push(`</${listType}>`);
    listType = null;
  };

  const closeParagraph = () => {
    if (!paragraphOpen) return;
    htmlParts.push("</p>");
    paragraphOpen = false;
  };

  lines.forEach((line) => {
    const trimmed = line.trim();

    if (!trimmed) {
      closeList();
      closeParagraph();
      return;
    }

    if (/^@@CODE_BLOCK_\d+@@$/.test(trimmed)) {
      closeList();
      closeParagraph();
      htmlParts.push(trimmed);
      return;
    }

    const h3 = trimmed.match(/^###\s+(.+)$/);
    if (h3) {
      closeList();
      closeParagraph();
      htmlParts.push(`<h3>${escapeHtml(h3[1])}</h3>`);
      return;
    }

    const h2 = trimmed.match(/^##\s+(.+)$/);
    if (h2) {
      closeList();
      closeParagraph();
      htmlParts.push(`<h2>${escapeHtml(h2[1])}</h2>`);
      return;
    }

    const h1 = trimmed.match(/^#\s+(.+)$/);
    if (h1) {
      closeList();
      closeParagraph();
      htmlParts.push(`<h1>${escapeHtml(h1[1])}</h1>`);
      return;
    }

    const unordered = trimmed.match(/^[-*]\s+(.+)$/);
    const ordered = trimmed.match(/^\d+\.\s+(.+)$/);
    if (unordered || ordered) {
      closeParagraph();
      const desiredType: "ul" | "ol" = unordered ? "ul" : "ol";
      if (listType !== desiredType) {
        closeList();
        htmlParts.push(`<${desiredType}>`);
        listType = desiredType;
      }
      htmlParts.push(`<li>${applyInlineMarkdownLite((unordered || ordered)?.[1] || "")}</li>`);
      return;
    }

    closeList();
    if (!paragraphOpen) {
      htmlParts.push("<p>");
      paragraphOpen = true;
    } else {
      htmlParts.push("<br>");
    }
    htmlParts.push(applyInlineMarkdownLite(trimmed));
  });

  closeList();
  closeParagraph();

  let html = htmlParts.join("");
  codeBlocks.forEach((block, idx) => {
    html = html.replace(`@@CODE_BLOCK_${idx}@@`, block);
  });
  return html;
}

function onCodeBlockCopyButtonClick(event: Event) {
  const target = event.target as Element | null;
  const button = target?.closest(CODE_COPY_BUTTON_SELECTOR) as HTMLButtonElement | null;
  if (!button) return;

  const codeElement = button.closest(".code-block-container")?.querySelector("code");
  const code = codeElement ? codeElement.textContent || "" : "";
  const icon = button.querySelector("i");
  const textSpan = button.querySelector("span");
  const defaultLabel = textSpan ? textSpan.dataset.defaultLabel || textSpan.textContent || "" : "";
  if (textSpan) textSpan.dataset.defaultLabel = defaultLabel;

  const copyPromise = copyTextToClipboard(code);

  copyPromise.then(() => {
    if (icon) {
      icon.classList.remove("bi-clipboard", "bi-x-lg");
      icon.classList.add("bi-check-lg");
      window.setTimeout(() => {
        icon.classList.remove("bi-check-lg", "bi-x-lg");
        icon.classList.add("bi-clipboard");
      }, 2000);
    }
    if (textSpan) {
      textSpan.textContent = "Copied!";
      window.setTimeout(() => {
        textSpan.textContent = defaultLabel;
      }, 2000);
    }
  }).catch((error) => {
    console.error("Failed to copy code block.", error);
    if (icon) {
      icon.classList.remove("bi-clipboard", "bi-check-lg");
      icon.classList.add("bi-x-lg");
      window.setTimeout(() => {
        icon.classList.remove("bi-check-lg", "bi-x-lg");
        icon.classList.add("bi-clipboard");
      }, 2000);
    }
    if (textSpan) {
      textSpan.textContent = "Failed";
      window.setTimeout(() => {
        textSpan.textContent = defaultLabel;
      }, 2000);
    }
  });
}

function ensureMarkedParser() {
  if (markedParser) return Promise.resolve();
  if (markdownEnhancementDisabled) return Promise.resolve();
  try {
    const renderer = {
      code(token: unknown) {
        const { text, lang } = readMarkedCodeToken(token);
        const language = lang.split(" ")[0] || "plaintext";

        let highlighted = text;
        try {
          if (hljs.getLanguage(language)) {
            highlighted = hljs.highlight(text, { language }).value;
          } else {
            highlighted = hljs.highlightAuto(text).value;
          }
        } catch (error) {
          console.error("Highlight error:", error);
          highlighted = escapeHtml(text);
        }

        return `
          <div class="code-block-container">
            <div class="code-block-header">
              <span class="code-block-lang">${language}</span>
              <button class="code-block-copy-btn" type="button">
                <i class="bi bi-clipboard"></i>
                <span>Copy code</span>
              </button>
            </div>
            <pre><code class="hljs language-${language}">${highlighted}</code></pre>
          </div>`;
      }
    };

    const marked = new Marked();
    marked.use({ renderer });
    markedParser = marked.parse.bind(marked);

    const memoRenderer = {
      code(token: unknown) {
        const { text, lang } = readMarkedCodeToken(token);
        const language = lang.split(" ")[0] || "plaintext";

        let highlighted = text;
        try {
          if (hljs.getLanguage(language)) {
            highlighted = hljs.highlight(text, { language }).value;
          } else {
            highlighted = hljs.highlightAuto(text).value;
          }
        } catch (error) {
          console.error("Highlight error:", error);
          highlighted = escapeHtml(text);
        }

        return `
          <div class="memo-code-block-container">
            <div class="memo-code-block-header">
              <span class="memo-code-block-lang">${language}</span>
            </div>
            <pre><code class="hljs language-${language}">${highlighted}</code></pre>
          </div>`;
      }
    };

    const memoMarked = new Marked();
    memoMarked.use({ renderer: memoRenderer });
    memoMarkedParser = memoMarked.parse.bind(memoMarked);
  } catch (error) {
    markdownEnhancementDisabled = true;
    console.warn("Failed to initialize markdown enhancement. Falling back to lightweight formatter.", error);
  }

  return Promise.resolve();
}

/* チャット画面を表示（セットアップ画面を隠す） */
function showChatInterface() {
  const { setupContainer, chatContainer } = getSharedDomRefs();
  if (!setupContainer || !chatContainer) return;

  setupContainer.setAttribute("data-visible", "false");
  chatContainer.setAttribute("data-visible", "true");
  refreshChatShareState();

  // Markdown パーサはチャット画面表示時に遅延読み込みする
  if (!markdownEnhancementDisabled) void ensureMarkedParser();
}

/* タイピングインジケータ */
function showTypingIndicator() {
  getSharedDomRefs().chatMessages?.setAttribute("aria-busy", "true");
}
function hideTypingIndicator() {
  getSharedDomRefs().chatMessages?.removeAttribute("aria-busy");
}

/* LLM 出力の Markdown を HTML に変換 */
function formatLLMOutput(text: string) {
  const normalized = normalizeLLMTextForDisplay(text);
  // ensureMarkedParser() は markedParser を同期的に設定するため、初回呼び出しでも
  // フォールバック（HTML をエスケープしてしまう）に落ちないよう初期化後に再判定する。
  if (!markedParser && !markdownEnhancementDisabled) {
    void ensureMarkedParser();
  }
  if (!markedParser) {
    return formatMarkdownFallback(normalized);
  }

  const cached = botMarkdownHtmlCache.get(normalized);
  if (cached !== undefined) return cached;

  const parsed = markedParser(normalized, {
    async: false,
    gfm: true,
    breaks: true
  });
  const html = typeof parsed === "string" ? parsed : normalized;
  rememberMarkdownHtml(botMarkdownHtmlCache, normalized, html);
  return html;
}

/* メモ用の LLM 出力 Markdown を HTML に変換 */
function formatMemoOutput(text: string) {
  const normalized = normalizeMemoTextForDisplay(text);
  if (!memoMarkedParser && !markdownEnhancementDisabled) {
    void ensureMarkedParser();
  }
  if (!memoMarkedParser) {
    return formatMarkdownFallback(normalized);
  }

  const cached = memoMarkdownHtmlCache.get(normalized);
  if (cached !== undefined) return cached;

  const parsed = memoMarkedParser(normalized, {
    async: false,
    gfm: true,
    breaks: true
  });
  const html = typeof parsed === "string" ? parsed : normalized;
  rememberMarkdownHtml(memoMarkdownHtmlCache, normalized, html);
  return html;
}

/* ユーザー入力の Markdown を HTML に変換 */
function formatUserInputForDisplay(text: string) {
  const normalized = normalizeUserTextForDisplay(text);
  if (!markedParser) {
    if (!markdownEnhancementDisabled) void ensureMarkedParser();
    return formatMarkdownFallback(normalized);
  }

  const cached = userMarkdownHtmlCache.get(normalized);
  if (cached !== undefined) return cached;

  const parsed = markedParser(normalized, {
    async: false,
    gfm: true,
    breaks: true
  });
  const html = sanitizeMessageHtml(
    typeof parsed === "string" ? parsed : formatMarkdownFallback(normalized)
  );
  rememberMarkdownHtml(userMarkdownHtmlCache, normalized, html);
  return html;
}

/*  サイドバートグル処理  */
function isOverlaySidebarViewport() {
  return window.matchMedia("(max-width: 960px)").matches;
}

function setSidebarOpen(isOpen: boolean) {
  const sb = document.querySelector(".sidebar");
  const toggleButton = document.getElementById("sidebar-toggle");
  if (!sb) return;

  const shouldOpen = isOverlaySidebarViewport() ? isOpen : false;
  sb.classList.toggle("open", shouldOpen);
  document.body.classList.toggle("sidebar-visible", shouldOpen);
  toggleButton?.setAttribute("aria-expanded", String(shouldOpen));
}

function toggleSidebar() {
  const sb = document.querySelector(".sidebar");
  if (!sb) return;
  setSidebarOpen(!sb.classList.contains("open"));
}

function closeSidebar() {
  setSidebarOpen(false);
}

let sidebarToggleInitialized = false;
let sidebarToggleAbortController: AbortController | null = null;

function onSidebarToggleButtonClick(e: Event) {
  e.stopPropagation();
  toggleSidebar();
}

function onSidebarOutsideClick(e: Event) {
  const target = e.target as Element | null;
  if (
    document.body.classList.contains("sidebar-visible") &&
    target &&
    !target.closest(".sidebar") &&
    !target.closest("#sidebar-toggle")
  ) {
    closeSidebar();
  }
}

const initSidebarToggle = () => {
  if (sidebarToggleInitialized) return;
  sidebarToggleInitialized = true;

  sidebarToggleAbortController?.abort();
  sidebarToggleAbortController = new AbortController();
  const { signal } = sidebarToggleAbortController;

  const sbBtn = document.getElementById("sidebar-toggle");
  sbBtn?.setAttribute("aria-expanded", "false");

  sbBtn?.addEventListener("click", onSidebarToggleButtonClick, { signal });

  // オーバーレイ／リンクタップで閉じる
  document.addEventListener("click", onSidebarOutsideClick, { signal });

  window.addEventListener("resize", closeSidebar, { signal });
};

function initCodeBlockCopyButtons() {
  document.addEventListener("click", onCodeBlockCopyButtonClick);
}

let chatUiInitialized = false;

function initChatUi() {
  if (chatUiInitialized) return;
  chatUiInitialized = true;
  initSidebarToggle();
  initCodeBlockCopyButtons();
}

export {
  initChatUi,
  showChatInterface,
  showTypingIndicator,
  hideTypingIndicator,
  formatLLMOutput,
  formatMemoOutput,
  formatUserInputForDisplay,
  closeSidebar
};
