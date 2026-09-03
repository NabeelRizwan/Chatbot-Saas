export const providers = ["gemini", "openai", "claude", "grok"] as const;

export type BotProvider = (typeof providers)[number];

export const providerLabels: Record<BotProvider, string> = {
  gemini: "Gemini",
  openai: "OpenAI",
  claude: "Claude",
  grok: "Grok",
};

export const providerModels: Record<BotProvider, readonly string[]> = {
  gemini: ["gemini-2.5-flash", "gemini-1.5-pro"],
  openai: ["gpt-4.1-mini", "gpt-4.1"],
  claude: ["claude-3-5-sonnet", "claude-3-opus"],
  grok: ["grok-2", "grok-beta"],
};

export const providerDefaultModels: Record<BotProvider, string> = {
  gemini: providerModels.gemini[0],
  openai: providerModels.openai[0],
  claude: providerModels.claude[0],
  grok: providerModels.grok[0],
};

export type BotStatus = "active" | "draft" | "disabled";
export type BotTone = "professional" | "friendly" | "empathetic" | "humorous" | "neutral";
export type BotCategory = "general" | "sales" | "marketing" | "hr";
export type AiUsageMode = "platform" | "byo";

export type BotCapabilities = {
  web_search: boolean;
  file_analysis: boolean;
  temperature: number;
};

export type WidgetConfig = {
  welcome_message: string;
  primary_color: string;
  accent_color: string;
  launcher_text: string;
  launcher_icon: "message" | "bot" | "support";
  position: "bottom-right" | "bottom-left";
  placeholder_text: string;
};

export type Bot = {
  id: string;
  organizationId: string | null;
  name: string;
  description: string | null;
  category: BotCategory;
  avatarUrl: string | null;
  status: BotStatus;
  provider: BotProvider;
  model: string;
  aiUsageMode: AiUsageMode;
  providerApiKeyMasked: string | null;
  customerApiKeyMasked: string | null;
  systemPrompt: string | null;
  tone: BotTone;
  capabilities: BotCapabilities;
  welcomeMessage: string | null;
  widgetConfig: WidgetConfig;
  allowedOrigins: string[];
  createdAt: string | null;
};

export type BotEditableFields = {
  name: string;
  description: string | null;
  category: BotCategory;
  avatarUrl: string | null;
  status: BotStatus;
  provider: BotProvider;
  model: string;
  aiUsageMode: AiUsageMode;
  providerApiKey?: string | null;
  systemPrompt: string | null;
  tone: BotTone;
  capabilities: BotCapabilities;
  welcomeMessage: string | null;
  widgetConfig: WidgetConfig;
  allowedOrigins?: string[];
};

export type BotBuilderInput = Omit<BotEditableFields, "widgetConfig">;
export type BotCreateInput = BotEditableFields & { organizationId: string };
export type BotUpdateInput = Partial<BotEditableFields>;

export type BackendBotResponse = {
  bot_id?: number | string;
  id?: number | string;
  organization_id?: number | string | null;
  name: string;
  description?: string | null;
  category?: string | null;
  avatar_url?: string | null;
  status?: string | null;
  provider: string;
  model_name?: string;
  model?: string;
  provider_api_key_masked?: string | null;
  api_key?: string | null;
  ai_usage_mode?: string | null;
  system_prompt?: string | null;
  tone?: string | null;
  capabilities?: Partial<BotCapabilities> | null;
  welcome_message?: string | null;
  widget_config?: Partial<WidgetConfig> | null;
  allowed_origins?: string[] | null;
  created_at?: string | null;
};

export type BackendBotCreateRequest = {
  organization_id: number;
  name: string;
  description: string | null;
  category: BotCategory;
  avatar_url: string | null;
  status: BotStatus;
  provider: BotProvider;
  model_name: string;
  provider_api_key?: string | null;
  system_prompt: string | null;
  tone: BotTone;
  capabilities: BotCapabilities;
  welcome_message: string | null;
  widget_config: WidgetConfig;
  allowed_origins: string[];
};

export type BackendBotUpdateRequest = Partial<Omit<BackendBotCreateRequest, "organization_id">>;
