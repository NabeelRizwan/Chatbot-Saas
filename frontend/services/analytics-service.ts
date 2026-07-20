import { request } from "@/services/api";
import type { AnalyticsSummary, BackendAnalyticsSummary } from "@/types/analytics";

export async function getBotAnalyticsSummary(botId: string): Promise<AnalyticsSummary> {
  const response = await request<BackendAnalyticsSummary>({
    method: "GET",
    url: `/analytics/bot/${botId}/summary`,
  });

  return {
    botId: String(response.bot_id),
    totalConversations: response.total_conversations,
    totalMessages: response.total_messages,
    averageResponseTimeMs: response.average_response_time_ms,
    recentConversations24h: response.recent_conversations_24h,
    recentMessages24h: response.recent_messages_24h,
    successfulMessages: response.successful_messages,
    erroredMessages: response.errored_messages,
    lastMessageAt: response.last_message_at,
  };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export async function getOrganizationAnalyticsDetails(orgId: number | string): Promise<any> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return request<any>({
    method: "GET",
    url: `/analytics/organization/${orgId}/details`,
  });
}

