export type AnalyticsSummary = {
  botId: string;
  totalConversations: number;
  totalMessages: number;
  averageResponseTimeMs?: number | null;
  recentConversations24h: number;
  recentMessages24h: number;
  successfulMessages: number;
  erroredMessages: number;
  lastMessageAt?: string | null;
};

export type BackendAnalyticsSummary = {
  bot_id: number | string;
  total_conversations: number;
  total_messages: number;
  average_response_time_ms?: number | null;
  recent_conversations_24h: number;
  recent_messages_24h: number;
  successful_messages: number;
  errored_messages: number;
  last_message_at?: string | null;
};
