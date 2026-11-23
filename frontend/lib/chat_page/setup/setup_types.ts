// タスク選択画面で共有する状態とデータの型を定義する。
// Defines shared state and data types for task selection.

export type TaskItem = {
  task_id?: number | null;
  system_task_key?: string | null;
  name?: string;
  prompt_template?: string;
  response_rules?: string;
  output_skeleton?: string;
  input_examples?: string;
  output_examples?: string;
  is_default?: boolean;
};
