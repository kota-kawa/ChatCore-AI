export type PromptCategory = {
  value: string;
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
