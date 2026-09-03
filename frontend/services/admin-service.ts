import { api } from "./api";

export interface Page<T> { items: T[]; total: number; offset: number; limit: number }
export interface ProviderOption { id: string; models: string[] }
export interface PlatformKey {
  id: number;
  credential_profile_id: number;
  provider: string;
  label: string | null;
  status: "available" | "assigned" | "disabled";
  max_bot_assignments: number;
  remaining_capacity: number;
  assigned_bots: { id: number; name: string; provider: string; model_name: string; organization_id: number | null; organization_name: string | null; customer_name: string | null }[];
  assigned_bots_limit: number;
  assigned_bot_count: number;
  created_at: string;
  updated_at: string;
}
export interface AdminOrganization { id: number; name: string; bot_count: number; created_at: string }
export interface ConfigSnapshot { provider: string; model_name: string; credential_profile_id: number | null }
export interface AdminBot extends ConfigSnapshot {
  id: number;
  name: string;
  organization_id: number;
  organization_name: string;
  customer_name: string | null;
  status: string;
  usage_mode: "byo" | "platform";
  credential_label: string | null;
  credential_status: string | null;
  credential_assigned_bot_count: number | null;
  credential_max_bot_assignments: number | null;
  credential_remaining_capacity: number | null;
}
export type ListParams = { offset?: number; limit?: number; search?: string; provider?: string; organization_id?: number; assignable_to_bot_id?: number; credential_profile_id?: number; unassigned?: boolean };

export const adminService = {
  session: async () => (await api.get<{ user_id: number; is_admin: true }>("/admin/session")).data,
  overview: async () => (await api.get<{ organizations: number; bots: number; enabled_credentials: number }>("/admin/overview")).data,
  providerOptions: async () => (await api.get<{ providers: ProviderOption[]; allocation_mode: string }>("/admin/provider-options")).data,
  organizations: async (params: ListParams) => (await api.get<Page<AdminOrganization>>("/admin/organizations", { params })).data,
  bots: async (params: ListParams) => (await api.get<Page<AdminBot>>("/admin/bots", { params })).data,
  listPlatformKeys: async (params: ListParams = {}) => (await api.get<Page<PlatformKey>>("/admin/platform-keys", { params })).data,
  addPlatformKey: async (payload: { provider: string; api_key: string; label: string; max_bot_assignments: number }) =>
    (await api.post<PlatformKey>("/admin/platform-keys", payload)).data,
  updateKeyLabel: async (id: number, label: string) => (await api.put<PlatformKey>(`/admin/platform-keys/${id}`, { label })).data,
  updateKeyCapacity: async (id: number, max_bot_assignments: number, expected_max_bot_assignments: number) =>
    (await api.put<PlatformKey>(`/admin/platform-keys/${id}`, { max_bot_assignments, expected_max_bot_assignments })).data,
  enableKey: async (id: number) => (await api.post<PlatformKey>(`/admin/platform-keys/${id}/enable`)).data,
  disableKey: async (id: number) => (await api.post<PlatformKey>(`/admin/platform-keys/${id}/disable`)).data,
  deleteKey: async (id: number) => { await api.delete(`/admin/platform-keys/${id}`); },
  updateBotConfig: async (id: number, config: ConfigSnapshot, expected: ConfigSnapshot) =>
    (await api.patch<AdminBot>(`/admin/bots/${id}/provider-config`, { ...config, expected })).data,
};
