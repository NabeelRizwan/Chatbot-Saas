export type OrganizationRole = "owner" | "admin" | "member";

export type Organization = {
  id: string;
  name: string;
  slug: string;
  role: OrganizationRole;
  createdAt: string;
};

export type OrganizationMember = {
  id: string;
  userId: string;
  name: string;
  email: string;
  role: OrganizationRole;
  createdAt: string;
};

export type OrganizationInvitation = {
  id: string;
  organizationId: string;
  email: string;
  role: "admin" | "member";
  status: string;
  expiresAt: string;
  inviteToken?: string | null;
};

export type BackendOrganization = {
  id: number | string;
  name: string;
  slug: string;
  role: OrganizationRole;
  created_at: string;
};

export type BackendOrganizationMember = {
  id: number | string;
  user_id: number | string;
  name: string;
  email: string;
  role: OrganizationRole;
  created_at: string;
};

export type BackendOrganizationInvitation = {
  id: number | string;
  organization_id: number | string;
  email: string;
  role: "admin" | "member";
  status: string;
  expires_at: string;
  invite_token?: string | null;
};
