export const providers = ["gemini", "openai"] as const;

export type BotProvider = (typeof providers)[number];

export const providerLabels: Record<BotProvider, string> = {
  gemini: "Gemini",
  openai: "OpenAI",
};

export const providerModels: Record<BotProvider, readonly string[]> = {
  gemini: ["gemini-2.5-flash", "gemini-1.5-pro"],
  openai: ["gpt-4.1-mini", "gpt-4.1"],
};

export type BotStatus = "active" | "draft" | "disabled";

export type Bot = {
  id: string;
  name: string;
  provider: BotProvider;
  model: string;
  createdAt?: string;
  apiKeyMasked?: string;
  organizationId?: string | null;
  status: BotStatus;
  welcomeMessage?: string;
  welcome_message?: string;
  widget_config?: Record<string, unknown>;
  systemPrompt?: string;
};

export type BotCreateInput = {
  name: string;
  provider: BotProvider;
  model: string;
  ai_usage_mode?: "platform" | "byo";
  providerApiKey?: string;
  organizationId?: string | null;
  welcomeMessage?: string;
  systemPrompt?: string;
  customerApiKey?: string;
};

export type BotUpdateInput = {
  name?: string;
  provider?: BotProvider;
  model?: string;
  ai_usage_mode?: "platform" | "byo";
  providerApiKey?: string;
  welcomeMessage?: string;
  welcome_message?: string;
  widget_config?: Record<string, unknown>;
  systemPrompt?: string;
  description?: string;
  category?: string;
  avatar_url?: string;
  status?: string;
  tone?: string;
  capabilities?: Record<string, boolean>;
};

export type BackendBotResponse = {
  bot_id?: number | string;
  id?: number | string;
  name: string;
  provider: string;
  model_name?: string;
  model?: string;
  created_at?: string;
  provider_api_key?: string;
  api_key_masked?: string;
  status?: string;
  welcome_message?: string;
  system_prompt?: string | null;
  organization_id?: number | string | null;
};
