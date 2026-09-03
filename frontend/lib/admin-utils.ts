import type { ConfigSnapshot, PlatformKey } from "@/services/admin-service";

export function compatibleCredentials(keys: PlatformKey[], provider: string, botId: number) {
  return keys.filter((key) => key.provider === provider && key.status !== "disabled" &&
    (key.allocated_to_bot_id === null || key.allocated_to_bot_id === botId));
}

export function configSnapshot(bot: ConfigSnapshot): ConfigSnapshot {
  return { provider: bot.provider, model_name: bot.model_name, credential_profile_id: bot.credential_profile_id };
}
