export type TaskItem = {
  system_task_key?: string | null;
  name?: string;
  prompt_template?: string;
  response_rules?: string;
  output_skeleton?: string;
  input_examples?: string;
  output_examples?: string;
  is_default?: boolean;
};
