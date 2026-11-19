// 回答までのステップ（回答の実行記録）を、構造化データから描く。
// DOM は、旧形式の HTML を本文の描画（BotMessageHtml: サニタイズ込み）に通した結果と同じにしてある。
// web_search_sources.css のクラスと、開閉・favicon 失敗時の処理（web_search_sources_dom.ts）をそのまま使うため。
// 文言はサーバーが日本語固定で出していたものと同じで、今回は多言語化しない。
// Renders the steps to the answer (the answer's execution record) from structured data. The DOM is the
// same as what the legacy HTML produced once drawn through the prose renderer (BotMessageHtml, sanitizer
// included), so the classes of web_search_sources.css and the open/favicon-failure handling in
// web_search_sources_dom.ts work unchanged. The wording is what the server used to emit, fixed in Japanese;
// it is not localized in this change.
import { memo, useEffect, useLayoutEffect, useRef } from "react";

import { isAnswerTracePart } from "../../lib/chat_page/answer_trace";
import type {
  AnswerTraceSource,
  AnswerTraceStep,
  AnswerTraceStepKind,
  AnswerTraceV1,
  ChatMessagePart,
} from "../../lib/chat_page/types";
import {
  bindWebSearchSourcesInteractions,
  syncWebSearchSourcesState,
} from "../../lib/chat_page/web_search_sources_dom";
import { BotMessageHtml } from "./bot_message_html";

// SSR ではレイアウト効果が使えないため、BotMessageHtml と同じ切り替えをする。
// Layout effects are unavailable on SSR, so switch the same way BotMessageHtml does.
const useIsomorphicLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

const ROOT = "web-search-sources";
const STEP_ICONS: Record<AnswerTraceStepKind, string> = {
  decide: "bi-compass",
  search: "bi-search",
  reuse: "bi-arrow-repeat",
  read: "bi-file-earmark-text",
  follow: "bi-signpost-split",
  review: "bi-check2-circle",
  answer: "bi-stars",
  warning: "bi-exclamation-triangle",
  knowledge: "bi-journal-text",
  prompt: "bi-card-text",
  info: "bi-record-circle",
};

// 同じ URL が一覧に重なっても key が衝突しないよう、何回目の出現かを添える。
// Add the occurrence count so a URL repeated in a list never collides as a key.
function sourceKeys(sources: AnswerTraceSource[]): string[] {
  const seen = new Map<string, number>();
  return sources.map((source) => {
    const count = seen.get(source.url) ?? 0;
    seen.set(source.url, count + 1);
    return `${source.url}#${count}`;
  });
}

function SourceItem({ source }: { source: AnswerTraceSource }) {
  const followed = source.link_depth >= 1;
  return (
    <li className={`${ROOT}__item${followed ? ` ${ROOT}__item--followed` : ""}`}>
      <a className={`${ROOT}__link`} href={source.url} target="_blank" rel="noopener noreferrer">
        {/* favicon の読み込み失敗は web_search_sources_dom.ts がこの span にクラスを足して頭文字へ切り替える。className を変えない限り React はそのクラスを消さない */}
        {/* web_search_sources_dom.ts adds a class to this span on a favicon failure to show the initial; React keeps it as long as className is unchanged */}
        <span className="web-search-citation__icon">
          <span className="web-search-citation__fallback">{source.fallback_label}</span>
          {/* eslint-disable-next-line @next/next/no-img-element -- 外部サイトの小さな favicon で、旧 HTML と同じ素の img にする / a tiny external favicon drawn as the same plain img as the legacy HTML */}
          <img className="web-search-citation__favicon" src={source.favicon_url} alt="" referrerPolicy="no-referrer" />
        </span>
        <span className={`${ROOT}__content`}>
          <span className={`${ROOT}__title`}>{source.title}</span>
          {source.hostname ? <span className={`${ROOT}__hostname`}>{source.hostname}</span> : null}
          {followed ? (
            <span className={`${ROOT}__depth`}>
              {`${source.linked_from ? `${source.linked_from} から` : ""}${source.link_depth}階層先`}
            </span>
          ) : null}
        </span>
        <span className={`${ROOT}__external`}>↗</span>
      </a>
    </li>
  );
}

function StepMain({ step }: { step: AnswerTraceStep }) {
  return (
    <span className={`${ROOT}__step-main`}>
      <span className={`${ROOT}__step-head`}>
        <span className={`${ROOT}__step-title`}>{step.title}</span>
        {step.badge ? <span className={`${ROOT}__step-badge`}>{step.badge}</span> : null}
      </span>
      {step.query ? <span className={`${ROOT}__step-query`}>{step.query}</span> : null}
      {step.detail ? <span className={`${ROOT}__step-detail`}>{step.detail}</span> : null}
      {step.chips.length > 0 ? (
        <span className={`${ROOT}__step-chips`}>
          {step.chips.map((chip, index) => (
            <span key={`${index}:${chip}`} className={`${ROOT}__step-chip`}>
              {chip}
            </span>
          ))}
        </span>
      ) : null}
      {step.sources.length > 0 ? (
        <span className={`${ROOT}__step-toggle`}>
          <i className="bi bi-globe2"></i>
          <span className={`${ROOT}__step-toggle-label`}>参照したWebサイト</span>
          <span className={`${ROOT}__step-toggle-count`}>{`${step.sources.length}件`}</span>
          <span className={`${ROOT}__step-chevron`}>
            <i className="bi bi-chevron-down"></i>
          </span>
        </span>
      ) : null}
    </span>
  );
}

function Step({ step }: { step: AnswerTraceStep }) {
  const hasSources = step.sources.length > 0;
  // running は done と同じ DOM にクラスを 1 つ足すだけ。failed は kind（warning）が見た目を決める。
  // running only adds one class to the done DOM; for failed, the kind (warning) decides the look.
  const className = [
    `${ROOT}__step`,
    `${ROOT}__step--${step.kind}`,
    hasSources ? `${ROOT}__step--has-sources` : "",
    step.status === "running" ? `${ROOT}__step--running` : "",
  ]
    .filter(Boolean)
    .join(" ");
  const marker = (
    <span className={`${ROOT}__step-marker ${ROOT}__step-marker--${step.kind}`}>
      <i className={`bi ${STEP_ICONS[step.kind]}`}></i>
    </span>
  );
  if (!hasSources) {
    return (
      <li className={className}>
        {marker}
        <div className={`${ROOT}__step-card`}>
          <StepMain step={step} />
        </div>
      </li>
    );
  }
  const keys = sourceKeys(step.sources);
  return (
    <li className={className}>
      {marker}
      {/* open は付けない。利用者が開いた状態は DOM が持ち、更新で巻き戻さない */}
      {/* No open attribute: the open state the user set lives in the DOM and is never reset by an update */}
      <details className={`${ROOT}__step-details`}>
        <summary className={`${ROOT}__step-summary`}>
          <StepMain step={step} />
        </summary>
        <div className={`${ROOT}__step-body`}>
          <ul className={`${ROOT}__links`}>
            {step.sources.map((source, index) => (
              <SourceItem key={keys[index]} source={source} />
            ))}
          </ul>
        </div>
      </details>
    </li>
  );
}

type AnswerTraceProps = {
  trace: AnswerTraceV1;
};

// 回答までのステップ。更新（ステップの追加・状態の変化）では、ステップ ID を key にして既存の DOM を保つ。
// The steps to the answer. Updates keep the existing DOM by keying steps on their id.
function AnswerTraceComponent({ trace }: AnswerTraceProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  // 開閉と favicon 失敗のイベントはマウント時に一度だけ委譲する（BotMessageHtml と同じ。更新ごとの貼り替えは開閉アニメーションを打ち切る）。
  // Delegate the open and favicon-failure events once on mount, as BotMessageHtml does; re-attaching on each update would cut off the open animation.
  useIsomorphicLayoutEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    return bindWebSearchSourcesInteractions(container);
  }, []);

  // 更新で増えた favicon のうち、描画前に読み込みに失敗したものを頭文字へ切り替える。
  // Switch favicons that already failed to load before this render over to their initial.
  useIsomorphicLayoutEffect(() => {
    if (containerRef.current) syncWebSearchSourcesState(containerRef.current);
  }, [trace]);

  return (
    <div ref={containerRef}>
      <details className={`${ROOT} ${ROOT}--trace`}>
        <summary className={`${ROOT}__summary`}>
          <span className={`${ROOT}__summary-main`}>
            <span className={`${ROOT}__summary-icon`}>
              <i className="bi bi-list-check"></i>
            </span>
            <span className={`${ROOT}__summary-text`}>
              <span className={`${ROOT}__label`}>回答までのステップ</span>
              {trace.summary ? <span className={`${ROOT}__summary-detail`}>{trace.summary}</span> : null}
            </span>
          </span>
          <span className={`${ROOT}__count`}>{`${trace.steps.length}ステップ`}</span>
          <span className={`${ROOT}__chevron`}>
            <i className="bi bi-chevron-down"></i>
          </span>
        </summary>
        <div className={`${ROOT}__list`}>
          <ol className={`${ROOT}__steps`}>
            {trace.steps.map((step) => (
              <Step key={step.id} step={step} />
            ))}
          </ol>
        </div>
      </details>
    </div>
  );
}

export const AnswerTrace = memo(AnswerTraceComponent);
AnswerTrace.displayName = "AnswerTrace";

export type AnswerTraceMessagePart = Extract<ChatMessagePart, { type: "answer_trace" | "legacy_answer_trace" }>;

// 実行記録のパーツを描く。構造化前に保存された回答の記録は表示用の HTML なので、本文と同じ描画（サニタイズ込み）に通す。
// Renders an execution-record part. The record of an answer saved before structuring is display HTML,
// so it goes through the same renderer as prose, sanitizer included.
export function AnswerTracePart({ part }: { part: AnswerTraceMessagePart }) {
  return part.type === "answer_trace" ? <AnswerTrace trace={part.trace} /> : <BotMessageHtml text={part.html} />;
}

// 実行記録を、直後の本文と同じ枠の中に描くかを返す。
// 記録が本文の先頭に HTML で入っていた頃は、記録の下の余白と本文の上の余白が 1 つに相殺されていた。パーツごとの枠は
// flex の項目なので、記録を別の枠に入れると相殺されず、間隔が広がる。本文が続くときは本文の枠の中へ入れて同じ間隔を保つ。
// 本文がまだ届いていないときも同じ枠を使い、本文が届いても記録を作り直さない（開いた状態を保つ）。
// Whether the execution record is drawn inside the same wrapper as the prose that follows it.
// While the record lived at the head of the body as HTML, its bottom margin and the prose's top margin
// collapsed into one. Part wrappers are flex items, so a record in a wrapper of its own no longer collapses
// and the spacing grows; drawing it inside the prose wrapper keeps the spacing. The same wrapper is used
// while no prose has arrived yet, so the record is not remounted (and stays open) once it does.
export function answerTraceSharesTextPart(parts: ChatMessagePart[]): boolean {
  if (parts.length === 0 || !isAnswerTracePart(parts[0])) return false;
  return parts.length === 1 || parts[1].type === "text";
}
