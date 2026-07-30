import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PromptCard, type PromptRecord } from "../components/prompt_share/prompt_card";
import { PromptShareAuthorProfileModal } from "../components/prompt_share/prompt_share_author_profile_modal";

const noop = () => {};

const basePrompt: PromptRecord = {
  id: 12,
  clientId: "prompt-12",
  title: "会議メモを要点・決定事項・次のアクションに要約する",
  content: "会議の議事録を受け取り、次の3セクションに分けて日本語で要約してください。",
  category: "business",
  author: "Kota",
  author_user_id: 42,
  author_avatar_url: "/static/uploads/avatar-42.png",
  content_format: "prompt",
  media_type: "text",
  prompt_type: "text",
  liked: false,
  used_in_chat: false,
  comment_count: 3,
  created_at: "2026-06-01T00:00:00Z"
};

function renderPromptCard(overrides: Partial<PromptRecord> = {}, onOpenAuthorProfile = vi.fn(), onOpenDetail = vi.fn()) {
  render(
    <PromptCard
      prompt={{ ...basePrompt, ...overrides }}
      isDropdownOpen={false}
      isLikePending={false}
      isLikeEffectActive={false}
      isAddAsTaskPending={false}
      isUseInChatEffectActive={false}
      onOpenDetail={onOpenDetail}
      onOpenComments={noop}
      onOpenShare={noop}
      onToggleDropdown={noop}
      onCloseDropdown={noop}
      onAddAsTask={noop}
      onToggleLike={noop}
      onOpenAuthorProfile={onOpenAuthorProfile}
    />
  );
  return { onOpenAuthorProfile, onOpenDetail };
}

// SNSのようにアバター+投稿者名からプロフィールを開ける導線を検証する
// Verifies the SNS-style avatar/name affordance that opens the author profile
describe("prompt_share author avatar", () => {
  it("投稿者IDがある場合、アバターをクリックするとプロフィールが開き、詳細モーダルは開かない", () => {
    const { onOpenAuthorProfile, onOpenDetail } = renderPromptCard();

    fireEvent.click(screen.getByRole("button", { name: /Kota/ }));

    expect(onOpenAuthorProfile).toHaveBeenCalledWith(42, "Kota");
    expect(onOpenDetail).not.toHaveBeenCalled();
  });

  it("投稿者IDが無い場合はクリックできない静的な署名として表示する", () => {
    const { onOpenAuthorProfile } = renderPromptCard({ author_user_id: null });

    expect(screen.queryByRole("button", { name: /Kota/ })).not.toBeInTheDocument();
    expect(screen.getByText("Kota")).toBeInTheDocument();
    expect(onOpenAuthorProfile).not.toHaveBeenCalled();
  });

  it("PromptShareAuthorProfileModalは自己紹介・投稿数・投稿一覧を表示し、行クリックとさらに読み込むを呼び出す", () => {
    const onOpenPrompt = vi.fn();
    const onLoadMore = vi.fn();
    const onClose = vi.fn();

    render(
      <PromptShareAuthorProfileModal
        isOpen
        authorProfileModalRef={{ current: null }}
        profile={{
          id: 42,
          username: "Kota",
          avatar_url: "/static/uploads/avatar-42.png",
          bio: "プロンプトを書くのが好きです。",
          prompt_count: 2
        }}
        fallbackName="Kota"
        prompts={[basePrompt]}
        isLoading={false}
        isLoadingMore={false}
        error={null}
        hasMore
        onLoadMore={onLoadMore}
        onOpenPrompt={onOpenPrompt}
        onClose={onClose}
      />
    );

    expect(screen.getByText("プロンプトを書くのが好きです。")).toBeInTheDocument();
    expect(screen.getByText("2件の投稿")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /会議メモを要点・決定事項・次のアクションに要約する/ }));
    expect(onOpenPrompt).toHaveBeenCalledWith(basePrompt);

    fireEvent.click(screen.getByRole("button", { name: "さらに読み込む" }));
    expect(onLoadMore).toHaveBeenCalledOnce();
  });

  it("自己紹介が未入力・投稿0件のプロフィールは空状態のメッセージを表示する", () => {
    render(
      <PromptShareAuthorProfileModal
        isOpen
        authorProfileModalRef={{ current: null }}
        profile={{
          id: 99,
          username: "新人ユーザー",
          avatar_url: "",
          bio: "",
          prompt_count: 0
        }}
        fallbackName="新人ユーザー"
        prompts={[]}
        isLoading={false}
        isLoadingMore={false}
        error={null}
        hasMore={false}
        onLoadMore={noop}
        onOpenPrompt={noop}
        onClose={noop}
      />
    );

    expect(screen.getByText("自己紹介はまだ入力されていません。")).toBeInTheDocument();
    expect(screen.getByText("公開しているプロンプトはまだありません。")).toBeInTheDocument();
  });
});
