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
  headers: {
    "Content-Type": "application/json",
  },
});

api.interceptors.request.use((config) => {
  const { accessToken, selectedOrganizationId } = useAuthStore.getState();
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`;
  }
  if (selectedOrganizationId) {
    config.headers["X-Organization-Id"] = selectedOrganizationId;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<ApiErrorPayload>) => {
    const originalRequest = error.config as (AxiosRequestConfig & { _retry?: boolean }) | undefined;
    const authState = useAuthStore.getState();

    if (error.response?.status === 401 && originalRequest && !originalRequest._retry && authState.refreshToken) {
      originalRequest._retry = true;
      try {
        const refreshResponse = await axios.post<{
          access_token: string;
          refresh_token: string;
          user: { id: number | string; name: string; email: string };
        }>(`${API_BASE_URL}/auth/refresh`, { refresh_token: authState.refreshToken });
        useAuthStore.getState().setSession(
          {
            accessToken: refreshResponse.data.access_token,
            refreshToken: refreshResponse.data.refresh_token,
          },
          {
            id: String(refreshResponse.data.user.id),
            name: refreshResponse.data.user.name,
            email: refreshResponse.data.user.email,
            role: authState.user?.role ?? "owner",
          },
        );
        originalRequest.headers = {
          ...originalRequest.headers,
          Authorization: `Bearer ${refreshResponse.data.access_token}`,
        };
        return api.request(originalRequest);
      } catch {
        useAuthStore.getState().clearSession();
      }
    }

    const message =
      error.response?.data?.detail ??
      error.response?.data?.message ??
      error.message ??
      "Request failed";

    return Promise.reject(new ApiServiceError(message, error.response?.status));
  },
);

export async function request<T>(config: AxiosRequestConfig): Promise<T> {
  const response = await api.request<T>(config);
  return response.data;
}
