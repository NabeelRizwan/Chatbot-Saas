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

export type OrganizationAnalytics = {
  window: { label: string; start: string; end: string; timezone: string };
  summary: {
    chat_sessions: number;
    total_messages: number;
    successful_messages: number;
    avg_response_time_ms: number | null;
    fallback_rate: number;
    retrieval_attempt_rate: number;
    evidence_found_rate: number;
    active_bots: number;
    team_members: number;
    chat_sessions_today: number;
    messages_today: number;
  };
  trends: {
    window: string;
    series: { date: string; chat_sessions: number; messages: number }[];
  };
  top_bots: { id: number; name: string; chat_sessions: number }[];
  largest_knowledge_sources: {
    id: number;
    filename: string;
    chunk_count: number;
    token_count: number;
    logical_size_bytes: number;
    source_type: string;
  }[];
  insights: {
    top_questions: { question: string; count: number }[];
    frequent_unanswered_questions: { question: string; count: number }[];
  };
  metric_notes: Record<string, string>;
};
