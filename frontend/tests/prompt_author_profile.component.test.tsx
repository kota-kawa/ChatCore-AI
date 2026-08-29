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
  const view = render(
    <PromptCard
      prompt={{ ...basePrompt, ...overrides }}
      isDropdownOpen={false}
      isLikePending={false}
      isLikeEffectActive={false}
      isAddAsTaskPending={false}
      isMemoSavePending={false}
      isUseInChatEffectActive={false}
      onOpenDetail={onOpenDetail}
      onOpenComments={noop}
      onOpenShare={noop}
      onToggleDropdown={noop}
      onCloseDropdown={noop}
      onAddAsTask={noop}
      onSaveAsMemo={noop}
      onToggleLike={noop}
      onOpenAuthorProfile={onOpenAuthorProfile}
    />
  );
  return { onOpenAuthorProfile, onOpenDetail, container: view.container };
}

// SNSのようにアバター+投稿者名からプロフィールを開ける導線を検証する
// Verifies the SNS-style avatar/name affordance that opens the author profile
describe("prompt_share author avatar", () => {
  it("投稿者IDがある場合、アバターをクリックするとプロフィールが開き、詳細モーダルは開かない", () => {
    const { onOpenAuthorProfile, onOpenDetail } = renderPromptCard();

    const authorButton = screen.getByRole("button", { name: /Kota/ });
    const cardHeader = authorButton.closest(".prompt-card__header");

    expect(cardHeader).toContainElement(screen.getByText("2026/06/01"));
    fireEvent.click(authorButton);

    expect(onOpenAuthorProfile).toHaveBeenCalledWith(42, "Kota");
    expect(onOpenDetail).not.toHaveBeenCalled();
  });

  it("投稿者IDが無い場合はクリックできない静的な署名として表示する", () => {
    const { onOpenAuthorProfile } = renderPromptCard({ author_user_id: null });

    expect(screen.queryByRole("button", { name: /Kota/ })).not.toBeInTheDocument();
    expect(screen.getByText("Kota")).toBeInTheDocument();
    expect(onOpenAuthorProfile).not.toHaveBeenCalled();
  });

  it("カードの本文プレビューをMarkdownとして整形する", () => {
    const { container } = renderPromptCard({
      content: "# 会議メモ\n\n- 決定事項をまとめる\n- 次の対応を明記する"
    });

    expect(container.querySelector(".prompt-card__content h1")).toHaveTextContent("会議メモ");
    expect(container.querySelector(".prompt-card__content li")).toHaveTextContent("決定事項をまとめる");
  });

  it("PromptShareAuthorProfileModalは自己紹介・投稿数・投稿一覧を表示し、行クリックとさらに読み込むを呼び出す", () => {
    const onOpenPrompt = vi.fn();
    const onLoadMore = vi.fn();
    const onClose = vi.fn();
    const profilePrompt = {
      ...basePrompt,
      description: "会議の決定事項を短く整理するための説明",
      attachments: [{
        role: "reference",
        url: "/prompt_share/api/media/profile-example.webp",
        thumbnail_url: "/prompt_share/api/media/profile-example-card.webp"
      }]
    };

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
        prompts={[profilePrompt]}
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
    expect(screen.getByText("会議の決定事項を短く整理するための説明")).toBeInTheDocument();
    expect(screen.getByAltText("会議メモを要点・決定事項・次のアクションに要約する の作例画像")).toHaveAttribute(
      "src",
      "/prompt_share/api/media/profile-example-card.webp"
    );

    fireEvent.click(screen.getByRole("button", { name: /会議メモを要点・決定事項・次のアクションに要約する/ }));
    expect(onOpenPrompt).toHaveBeenCalledWith(profilePrompt);

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
