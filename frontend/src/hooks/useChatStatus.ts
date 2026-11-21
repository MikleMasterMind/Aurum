import { useQuery } from "@tanstack/react-query";
import { fetchChatStatus } from "@/api/chat";

export function useChatStatus() {
  return useQuery({ queryKey: ["chat-status"], queryFn: fetchChatStatus });
}
