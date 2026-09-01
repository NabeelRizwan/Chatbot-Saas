import axios, { AxiosError, type AxiosInstance, type AxiosRequestConfig } from "axios";

import { useAuthStore } from "@/store/auth-store";
import type { ApiErrorPayload } from "@/types/api";

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export class ApiServiceError extends Error {
  status?: number;
  constructor(message: string, status?: number) {
    super(message);
    this.name = "ApiServiceError";
    this.status = status;
  }
}

export const api: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  withCredentials: true,
  headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
});

function formatErrorDetail(detail: ApiErrorPayload["detail"]): string | undefined {
  if (typeof detail === "string") return detail;
  if (!Array.isArray(detail)) return undefined;
  return detail
    .map((issue) => {
      const field = issue.loc?.filter((part) => part !== "body").join(".");
      return [field, issue.msg].filter(Boolean).join(": ");
    })
    .filter(Boolean)
    .join("; ");
}

api.interceptors.request.use((config) => {
  const { accessToken, selectedOrganizationId } = useAuthStore.getState();
  if (accessToken) config.headers.Authorization = `Bearer ${accessToken}`;
  if (selectedOrganizationId) config.headers["X-Organization-Id"] = selectedOrganizationId;
  return config;
});

type RetriableRequest = AxiosRequestConfig & { _retry?: boolean };
type RefreshCoordinator = typeof globalThis & {
  __chatbotSaasRefreshPromise?: Promise<string>;
};
const refreshCoordinator = globalThis as RefreshCoordinator;

function isAuthLifecycleRequest(url?: string) {
  return Boolean(url && ["/auth/login", "/auth/register", "/auth/refresh", "/auth/logout"].some((path) => url.endsWith(path)));
}

export async function refreshAccessToken(): Promise<string> {
  if (!refreshCoordinator.__chatbotSaasRefreshPromise) {
    const legacyRefreshToken = useAuthStore.getState().consumeLegacyRefreshToken();
    const pending = axios
      .post<{
        access_token: string;
        user: { id: number | string; name: string; email: string; is_admin?: boolean };
      }>(
        `${API_BASE_URL}/auth/refresh`,
        legacyRefreshToken ? { refresh_token: legacyRefreshToken } : {},
        { withCredentials: true, headers: { "X-Requested-With": "XMLHttpRequest" } },
      )
      .then(({ data }) => {
        useAuthStore.getState().setSession(data.access_token, {
          id: String(data.user.id), name: data.user.name, email: data.user.email, is_admin: data.user.is_admin,
        });
        return data.access_token;
      })
      .finally(() => {
        if (refreshCoordinator.__chatbotSaasRefreshPromise === pending) {
          delete refreshCoordinator.__chatbotSaasRefreshPromise;
        }
      });
    refreshCoordinator.__chatbotSaasRefreshPromise = pending;
  }
  return refreshCoordinator.__chatbotSaasRefreshPromise;
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<ApiErrorPayload>) => {
    const originalRequest = error.config as RetriableRequest | undefined;
    const authState = useAuthStore.getState();
    if (
      error.response?.status === 401 && originalRequest && !originalRequest._retry &&
      !isAuthLifecycleRequest(originalRequest.url) && authState.user
    ) {
      originalRequest._retry = true;
      try {
        const accessToken = await refreshAccessToken();
        originalRequest.headers = { ...originalRequest.headers, Authorization: `Bearer ${accessToken}` };
        return api.request(originalRequest);
      } catch {
        // A route/HMR bundle that began before the global coordinator existed
        // may lose a refresh-cookie rotation race. If another request already
        // recovered the session, retry with that newer access token instead of
        // clearing a valid session.
        const recoveredToken = useAuthStore.getState().accessToken;
        if (recoveredToken && recoveredToken !== authState.accessToken) {
          originalRequest.headers = {
            ...originalRequest.headers,
            Authorization: `Bearer ${recoveredToken}`,
          };
          return api.request(originalRequest);
        }
        useAuthStore.getState().clearSession();
      }
    }

    const message = formatErrorDetail(error.response?.data?.detail) ?? error.response?.data?.message ?? error.message ?? "Request failed";
    return Promise.reject(new ApiServiceError(message, error.response?.status));
  },
);

export async function request<T>(config: AxiosRequestConfig): Promise<T> {
  const response = await api.request<T>(config);
  return response.data;
}
