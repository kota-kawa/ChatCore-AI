export type TaskItem = {
  name?: string;
  prompt_template?: string;
  response_rules?: string;
  output_skeleton?: string;
  input_examples?: string;
  output_examples?: string;
  is_default?: boolean;
};

export type LoadTaskCardsOptions = {
  forceRefresh?: boolean;
};
