import { api } from "./api";

export interface PlatformKey {
  id: number;
  provider: string;
  masked_key: string | null;
  label: string | null;
  status: "available" | "assigned" | "disabled";
  allocated_to_bot_id: number | null;
  bot: { id: number; name: string; provider: string } | null;
  requests_count: number;
  tokens_used: number;
  last_used_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface PoolStatus {
  providers: Record<
    string,
    { available: number; assigned: number; disabled: number; total: number }
  >;
}

const BASE = "/admin";

export const adminService = {
  listPlatformKeys: async (): Promise<PlatformKey[]> => {
    const res = await api.get(`${BASE}/platform-keys`);
    return res.data;
  },

  getPoolStatus: async (): Promise<PoolStatus> => {
    const res = await api.get(`${BASE}/platform-keys/pool-status`);
    return res.data;
  },

  addPlatformKey: async (payload: {
    provider: string;
    api_key: string;
    label?: string;
  }): Promise<PlatformKey> => {
    const res = await api.post(`${BASE}/platform-keys`, payload);
    return res.data;
  },

  updateKeyLabel: async (
    keyId: number,
    label: string | null
  ): Promise<PlatformKey> => {
    const res = await api.put(`${BASE}/platform-keys/${keyId}`, { label });
    return res.data;
  },

  enableKey: async (keyId: number): Promise<PlatformKey> => {
    const res = await api.post(`${BASE}/platform-keys/${keyId}/enable`);
    return res.data;
  },

  disableKey: async (keyId: number): Promise<PlatformKey> => {
    const res = await api.post(`${BASE}/platform-keys/${keyId}/disable`);
    return res.data;
  },

  deleteKey: async (keyId: number): Promise<void> => {
    await api.delete(`${BASE}/platform-keys/${keyId}`);
  },
};
