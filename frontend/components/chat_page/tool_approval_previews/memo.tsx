import { Fragment, memo } from "react";

import { useTranslation } from "../../../contexts/locale_context";
import type { ToolApprovalApi } from "../../../types/generated/api_schemas";
import { ExpandableText, FullTextDisclosure, PreviewField } from "./shared";

type AnyPreview = NonNullable<ToolApprovalApi["preview"]>;
type MemoPreview = Extract<AnyPreview, { kind: "memo_create" | "memo_append" | "memo_edit" }>;

// メモの作成・追記・書き換えの提案を、実行前に確かめられる形で見せる。部分置換は編集ごとに
// 変更前／変更後を並べ、複数あるときだけ番号を付ける（メモエージェントの実行確認と同じ規則）。
// Shows a memo create, append or edit proposal so it can be checked before it runs. Partial edits list
// each passage before and after, numbered only when there is more than one (the same rule as the memo
// agent's action review).
function MemoApprovalPreviewComponent({ preview }: { preview: MemoPreview }) {
  const { t } = useTranslation();
  const untitled = t("chat.toolApproval.preview.untitled");

  if (preview.kind === "memo_create") {
    return (
      <dl className="tool-approval-preview">
        <PreviewField label={t("chat.toolApproval.preview.title")}>{preview.title.trim() || untitled}</PreviewField>
        <PreviewField label={t("chat.toolApproval.preview.content")}>
          <ExpandableText text={preview.content} />
        </PreviewField>
      </dl>
    );
  }

  if (preview.kind === "memo_append") {
    return (
      <dl className="tool-approval-preview">
        <PreviewField label={t("chat.toolApproval.preview.targetMemo")}>{preview.memo_title.trim() || untitled}</PreviewField>
        <PreviewField label={t("chat.toolApproval.preview.appendText")}>
          <ExpandableText text={preview.text} />
        </PreviewField>
      </dl>
    );
  }

  const edits = preview.mode === "edits" ? (preview.edits ?? []) : [];
  const numbered = edits.length > 1;
  return (
    <dl className="tool-approval-preview">
      <PreviewField label={t("chat.toolApproval.preview.targetMemo")}>{preview.memo_title.trim() || untitled}</PreviewField>
      {preview.new_title !== null ? (
        <PreviewField label={t("chat.toolApproval.preview.newTitle")}>{preview.new_title.trim() || untitled}</PreviewField>
      ) : null}
      {edits.map((edit, index) => {
        const suffix = numbered ? ` ${index + 1}` : "";
        return (
          <Fragment key={index}>
            <PreviewField
              label={`${t("chat.toolApproval.preview.before")}${suffix}`}
              className="tool-approval-preview__field--before"
            >
              <ExpandableText text={edit.before} />
            </PreviewField>
            <PreviewField label={`${t("chat.toolApproval.preview.after")}${suffix}`}>
              <ExpandableText text={edit.after || t("chat.toolApproval.preview.removed")} />
            </PreviewField>
          </Fragment>
        );
      })}
      {preview.mode === "content" && preview.content !== null ? (
        <PreviewField label={t("chat.toolApproval.preview.editedContent")}>
          <FullTextDisclosure text={preview.content} />
        </PreviewField>
      ) : null}
    </dl>
  );
}

// 不要な再レンダリングを防ぐためにメモ化する
// Memoized to prevent unnecessary re-renders
export const MemoApprovalPreview = memo(MemoApprovalPreviewComponent);
MemoApprovalPreview.displayName = "MemoApprovalPreview";
