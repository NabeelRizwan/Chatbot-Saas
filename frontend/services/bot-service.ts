import { request } from "@/services/api";
import type { BackendBotResponse, Bot, BotCreateInput, BotUpdateInput } from "@/types/bot";
import { normalizeBot, toBackendBotCreate, toBackendBotUpdate } from "@/lib/bot-utils";

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
    data: toBackendBotCreate(input),
  });

  return normalizeBot(response);
}

export async function updateBot(id: string, input: BotUpdateInput): Promise<Bot> {
  const response = await request<BackendBotResponse>({
    method: "PUT",
    url: `/bot/${id}`,
    data: toBackendBotUpdate(input),
  });

  return normalizeBot(response);
}

export async function deleteBot(id: string): Promise<void> {
  await request<void>({
    method: "DELETE",
    url: `/bot/${id}`,
  });
}
