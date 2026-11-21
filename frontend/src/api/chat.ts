import { api } from "@/api/client";
import type { ChatStatus, ChatTurn } from "@/types";

export function fetchChatStatus() {
  return api.get<ChatStatus>("/chat/status");
}

export function sendChatMessage(threadId: string, text: string) {
  return api.post<ChatTurn>("/chat/messages", { thread_id: threadId, text });
}

export function confirmChatCalls(threadId: string, decisions: boolean[]) {
  return api.post<ChatTurn>("/chat/confirm", { thread_id: threadId, decisions });
}

export function resetChatThread(threadId: string | null) {
  // thread_id null means "no old thread to forget" (first visit); the
  // backend accepts exactly one shape for both cases.
  return api.post<{ thread_id: string }>("/chat/reset", { thread_id: threadId });
}
