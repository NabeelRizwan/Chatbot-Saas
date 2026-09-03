import type {
  AiUsageMode,
  BackendBotCreateRequest,
  BackendBotResponse,
  BackendBotUpdateRequest,
  Bot,
  BotCategory,
  BotCreateInput,
  BotProvider,
  BotStatus,
  BotTone,
  BotUpdateInput,
  WidgetConfig,
} from "../types/bot";
import { providerDefaultModels, providers } from "../types/bot";

export const defaultWidgetConfig: WidgetConfig = {
  welcome_message: "Hi, how can I help you today?",
  primary_color: "#2563eb",
  accent_color: "#0f172a",
  launcher_text: "Chat",
  launcher_icon: "message",
  position: "bottom-right",
  placeholder_text: "Type your message...",
};

export function isBotProvider(value: string): value is BotProvider {
  return providers.includes(value as BotProvider);
}

function normalizeStatus(value?: string | null): BotStatus {
  return value === "draft" || value === "disabled" ? value : "active";
}

function normalizeTone(value?: string | null): BotTone {
  return value === "professional" || value === "friendly" || value === "empathetic" || value === "humorous"
    ? value
    : "neutral";
}

function normalizeCategory(value?: string | null): BotCategory {
  return value === "sales" || value === "marketing" || value === "hr" ? value : "general";
}

function normalizeAiUsageMode(value?: string | null): AiUsageMode {
  return value === "byo" ? "byo" : "platform";
}

export function normalizeBot(payload: BackendBotResponse): Bot {
  const provider = isBotProvider(payload.provider) ? payload.provider : "gemini";

  return {
    id: String(payload.bot_id ?? payload.id ?? ""),
    organizationId: payload.organization_id == null ? null : String(payload.organization_id),
    name: payload.name,
    description: payload.description ?? null,
    category: normalizeCategory(payload.category),
    avatarUrl: payload.avatar_url ?? null,
    status: normalizeStatus(payload.status),
    provider,
    model: payload.model_name ?? payload.model ?? providerDefaultModels[provider],
    aiUsageMode: normalizeAiUsageMode(payload.ai_usage_mode),
    providerApiKeyMasked: payload.provider_api_key_masked ?? null,
    customerApiKeyMasked: payload.api_key ?? null,
    systemPrompt: payload.system_prompt ?? null,
    tone: normalizeTone(payload.tone),
    capabilities: {
      web_search: payload.capabilities?.web_search ?? false,
      file_analysis: payload.capabilities?.file_analysis ?? true,
      temperature: payload.capabilities?.temperature ?? 0.7,
    },
    welcomeMessage: payload.welcome_message ?? null,
    widgetConfig: { ...defaultWidgetConfig, ...payload.widget_config },
    allowedOrigins: payload.allowed_origins ?? [],
    createdAt: payload.created_at ?? null,
  };
}

function normalizedOrganizationId(value: string): number {
  const organizationId = Number(value);
  if (!Number.isInteger(organizationId) || organizationId <= 0) {
    throw new Error("Select a valid organization before creating a bot.");
  }
  return organizationId;
}

function keyForMode(mode: AiUsageMode, key: string | null | undefined): string | null | undefined {
  if (mode === "platform") return null;
  if (key === undefined) return undefined;
  const trimmed = key?.trim();
  if (!trimmed) throw new Error("Enter a provider API key when using your own key.");
  return trimmed;
}

export function toBackendBotCreate(input: BotCreateInput): BackendBotCreateRequest {
  const providerApiKey = keyForMode(input.aiUsageMode, input.providerApiKey);
  if (input.aiUsageMode === "byo" && providerApiKey === undefined) {
    throw new Error("Enter a provider API key when using your own key.");
  }

  return {
    organization_id: normalizedOrganizationId(input.organizationId),
    name: input.name,
    description: input.description,
    category: input.category,
    avatar_url: input.avatarUrl,
    status: input.status,
    provider: input.provider,
    model_name: input.model,
    provider_api_key: providerApiKey,
    system_prompt: input.systemPrompt,
    tone: input.tone,
    capabilities: input.capabilities,
    welcome_message: input.welcomeMessage,
    widget_config: input.widgetConfig,
    allowed_origins: input.allowedOrigins ?? [],
  };
}

export function toBackendBotUpdate(input: BotUpdateInput): BackendBotUpdateRequest {
  const output: BackendBotUpdateRequest = {};
  if (input.name !== undefined) output.name = input.name;
  if (input.description !== undefined) output.description = input.description;
  if (input.category !== undefined) output.category = input.category;
  if (input.avatarUrl !== undefined) output.avatar_url = input.avatarUrl;
  if (input.status !== undefined) output.status = input.status;
  if (input.provider !== undefined) output.provider = input.provider;
  if (input.model !== undefined) output.model_name = input.model;
  if (input.systemPrompt !== undefined) output.system_prompt = input.systemPrompt;
  if (input.tone !== undefined) output.tone = input.tone;
  if (input.capabilities !== undefined) output.capabilities = input.capabilities;
  if (input.welcomeMessage !== undefined) output.welcome_message = input.welcomeMessage;
  if (input.widgetConfig !== undefined) output.widget_config = input.widgetConfig;
  if (input.allowedOrigins !== undefined) output.allowed_origins = input.allowedOrigins;
  if (input.aiUsageMode !== undefined) {
    const providerApiKey = keyForMode(input.aiUsageMode, input.providerApiKey);
    if (providerApiKey !== undefined) output.provider_api_key = providerApiKey;
  } else if (input.providerApiKey !== undefined) {
    const trimmed = input.providerApiKey?.trim();
    output.provider_api_key = trimmed || null;
  }
  return output;
}
