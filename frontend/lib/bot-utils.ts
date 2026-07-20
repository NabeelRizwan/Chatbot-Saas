import type { BackendBotResponse, Bot, BotProvider, BotStatus } from "@/types/bot";
import { providers } from "@/types/bot";

export function isBotProvider(value: string): value is BotProvider {
  return providers.includes(value as BotProvider);
}

export function maskApiKey(value?: string | null): string {
  if (!value) {
    return "Not available";
  }

  if (value.includes("****")) {
    return value;
  }

  const prefix = value.startsWith("sk-") ? "sk-" : value.slice(0, 3);
  const suffix = value.slice(-4);
  return `${prefix}****${suffix}`;
}

export function normalizeBotStatus(value?: string): BotStatus {
  if (value === "draft" || value === "disabled") {
    return value;
  }

  return "active";
}

export function normalizeBot(payload: BackendBotResponse): Bot {
  const provider = isBotProvider(payload.provider) ? payload.provider : "gemini";

  return {
    id: String(payload.bot_id ?? payload.id ?? ""),
    name: payload.name,
    provider,
    model: payload.model_name ?? payload.model ?? "",
    createdAt: payload.created_at,
    apiKeyMasked: payload.api_key_masked ?? maskApiKey(payload.provider_api_key),
    organizationId: payload.organization_id ? String(payload.organization_id) : null,
    status: normalizeBotStatus(payload.status),
    welcomeMessage: payload.welcome_message,
    systemPrompt: payload.system_prompt ?? undefined,
  };
}
