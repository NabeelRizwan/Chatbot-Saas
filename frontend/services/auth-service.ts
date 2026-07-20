import { request } from "@/services/api";
import type { AuthUser } from "@/store/auth-store";

type BackendAuthResponse = {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  user: {
    id: number | string;
    name: string;
    email: string;
  };
};

function normalizeAuth(response: BackendAuthResponse) {
  return {
    accessToken: response.access_token,
    refreshToken: response.refresh_token,
    expiresIn: response.expires_in,
    user: {
      id: String(response.user.id),
      name: response.user.name,
      email: response.user.email,
      role: "owner" as const,
    } satisfies AuthUser,
  };
}

export async function register(input: { name: string; email: string; password: string; organizationName?: string }) {
  const response = await request<BackendAuthResponse>({
    method: "POST",
    url: "/auth/register",
    data: {
      name: input.name,
      email: input.email,
      password: input.password,
      organization_name: input.organizationName,
    },
  });
  return normalizeAuth(response);
}

export async function login(input: { email: string; password: string }) {
  const response = await request<BackendAuthResponse>({
    method: "POST",
    url: "/auth/login",
    data: input,
  });
  return normalizeAuth(response);
}

export async function refresh(refreshToken: string) {
  const response = await request<BackendAuthResponse>({
    method: "POST",
    url: "/auth/refresh",
    data: { refresh_token: refreshToken },
  });
  return normalizeAuth(response);
}

export async function logout(refreshToken?: string | null) {
  await request<{ success: boolean }>({
    method: "POST",
    url: "/auth/logout",
    data: { refresh_token: refreshToken },
  });
}

export async function updateProfile(input: {
  name?: string;
  bio?: string;
  avatar_url?: string;
  preferences?: Record<string, unknown>;
}) {
  const response = await request<{
    id: number | string;
    name: string;
    email: string;
    bio?: string;
    avatar_url?: string;
    preferences?: Record<string, unknown>;
  }>({
    method: "PATCH",
    url: "/auth/profile",
    data: input,
  });
  return {
    id: String(response.id),
    name: response.name,
    email: response.email,
    bio: response.bio,
    avatar_url: response.avatar_url,
    preferences: response.preferences,
    role: "owner" as const,
  } satisfies AuthUser;
}
