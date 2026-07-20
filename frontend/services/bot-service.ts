import { request } from "@/services/api";
import type { BackendBotResponse, Bot, BotCreateInput, BotUpdateInput } from "@/types/bot";
import { normalizeBot } from "@/lib/bot-utils";

export async function getBots(): Promise<Bot[]> {
  const response = await request<BackendBotResponse[] | { bots: BackendBotResponse[] }>({
    method: "GET",
    url: "/bots",
  });

  const bots = Array.isArray(response) ? response : response.bots;
  return bots.map(normalizeBot);
}

export async function getBot(id: string): Promise<Bot> {
  const response = await request<BackendBotResponse>({
    method: "GET",
    url: `/bot/${id}`,
  });

  return normalizeBot(response);
}

export async function createBot(input: BotCreateInput): Promise<Bot> {
  const response = await request<BackendBotResponse>({
    method: "POST",
    url: "/bot/create",
    data: {
      api_key: input.customerApiKey,
      organization_id: input.organizationId ? Number(input.organizationId) : undefined,
      name: input.name,
      provider: input.provider,
      model_name: input.model,
      provider_api_key: input.providerApiKey,
      system_prompt: input.systemPrompt,
      welcome_message: input.welcomeMessage,
    },
  });

  return normalizeBot({
    ...response,
    provider_api_key: input.providerApiKey,
    welcome_message: input.welcomeMessage,
    system_prompt: input.systemPrompt,
    status: "active",
  });
}

export async function updateBot(id: string, input: BotUpdateInput): Promise<Bot> {
  const response = await request<BackendBotResponse>({
    method: "PUT",
    url: `/bot/${id}`,
    data: {
      name: input.name,
      provider: input.provider,
      model_name: input.model,
      provider_api_key: input.providerApiKey || undefined,
      welcome_message: input.welcomeMessage,
      system_prompt: input.systemPrompt,
    },
  });

  return normalizeBot(response);
}

export async function deleteBot(id: string): Promise<void> {
  await request<void>({
    method: "DELETE",
    url: `/bot/${id}`,
  });
}
