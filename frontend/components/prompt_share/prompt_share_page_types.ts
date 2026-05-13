import type { PromptType } from "../../scripts/prompt_share/types";

export type PromptCategory = {
  value: string;
  iconClass: string;
  label: string;
};

export type PromptTypeFilter = "all" | PromptType;

export type PromptTypeFilterOption = {
  value: PromptTypeFilter;
  iconClass: string;
  label: string;
};

export type ModalKey = "post" | "detail" | "share" | null;

export type PromptFeedback = {
  message: string;
  variant: "empty" | "error";
};

export type PromptPostStatusVariant = "info" | "success" | "error";

export type PromptPostStatus = {
  message: string;
  variant: PromptPostStatusVariant;
};
