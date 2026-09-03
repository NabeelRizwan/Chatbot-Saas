import type { ConfigSnapshot, PlatformKey } from "@/services/admin-service";

export function compatibleCredentials(keys: PlatformKey[], provider: string, currentProfileId: number | null) {
  return keys.filter((key) => key.provider === provider && key.status !== "disabled" &&
    (key.remaining_capacity > 0 || key.id === currentProfileId));
}

export function configSnapshot(bot: ConfigSnapshot): ConfigSnapshot {
  return { provider: bot.provider, model_name: bot.model_name, credential_profile_id: bot.credential_profile_id };
}
