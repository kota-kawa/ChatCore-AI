import type { NormalizedTask, UiChatMessage } from "./types";

export function buildTaskOrderForPersistence(tasks: NormalizedTask[]) {
  return tasks
    .filter((task) => !task.is_default)
    .map((task) => task.name.trim())
    .filter((name) => Boolean(name));
}

export function isLatestChatTurnAnswered(messages: Pick<UiChatMessage, "sender">[]) {
  let latestUserIndex = -1;
  let latestAssistantIndex = -1;

  messages.forEach((message, index) => {
    if (message.sender === "user") {
      latestUserIndex = index;
      return;
    }

    if (message.sender === "assistant") {
      latestAssistantIndex = index;
    }
  });

  if (latestUserIndex === -1) {
    return latestAssistantIndex >= 0;
  }

  return latestAssistantIndex > latestUserIndex;
}
