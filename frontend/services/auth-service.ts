import { request } from "@/services/api";
import type { AuthUser } from "@/store/auth-store";

type BackendAuthResponse = {
  access_token: string;
  refresh_token?: string | null;
  expires_in: number;
  user: { id: number | string; name: string; email: string; is_admin?: boolean };
};

function normalizeAuth(response: BackendAuthResponse) {
  return {
    accessToken: response.access_token,
    expiresIn: response.expires_in,
    user: {
      id: String(response.user.id),
      name: response.user.name,
      email: response.user.email,
      is_admin: response.user.is_admin,
    } satisfies AuthUser,
  };
}

export async function register(input: { name: string; email: string; password: string; organizationName?: string }) {
  const response = await request<BackendAuthResponse>({
    method: "POST",
    url: "/auth/register",
    data: { name: input.name, email: input.email, password: input.password, organization_name: input.organizationName },
  });
  return normalizeAuth(response);
}

export async function login(input: { email: string; password: string }) {
  return normalizeAuth(await request<BackendAuthResponse>({ method: "POST", url: "/auth/login", data: input }));
}

export async function refresh(legacyRefreshToken?: string | null) {
  const response = await request<BackendAuthResponse>({
    method: "POST",
    url: "/auth/refresh",
    data: legacyRefreshToken ? { refresh_token: legacyRefreshToken } : {},
  });
  return normalizeAuth(response);
}

export async function logout(legacyRefreshToken?: string | null) {
  await request<{ success: boolean }>({
    method: "POST",
    url: "/auth/logout",
    data: legacyRefreshToken ? { refresh_token: legacyRefreshToken } : {},
  });
}

export async function logoutAll() {
  return request<{ success: boolean; revoked_sessions: number }>({ method: "POST", url: "/auth/logout-all" });
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
    is_admin?: boolean;
    bio?: string;
    avatar_url?: string;
    preferences?: Record<string, unknown>;
  }>({ method: "PATCH", url: "/auth/profile", data: input });
  return {
    id: String(response.id), name: response.name, email: response.email, is_admin: response.is_admin,
    bio: response.bio, avatar_url: response.avatar_url, preferences: response.preferences,
  } satisfies AuthUser;
}
