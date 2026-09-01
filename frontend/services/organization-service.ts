import { request } from "@/services/api";
import type {
  BackendOrganization,
  BackendOrganizationInvitation,
  BackendOrganizationMember,
  Organization,
  OrganizationInvitation,
  OrganizationMember,
} from "@/types/organization";

function normalizeOrg(org: BackendOrganization): Organization {
  return {
    id: String(org.id),
    name: org.name,
    slug: org.slug,
    role: org.role,
    createdAt: org.created_at,
  };
}

function normalizeMember(member: BackendOrganizationMember): OrganizationMember {
  return {
    id: String(member.id),
    userId: String(member.user_id),
    name: member.name,
    email: member.email,
    role: member.role,
    createdAt: member.created_at,
  };
}

function normalizeInvite(invite: BackendOrganizationInvitation): OrganizationInvitation {
  return {
    id: String(invite.id),
    organizationId: String(invite.organization_id),
    email: invite.email,
    role: invite.role,
    status: invite.status,
    expiresAt: invite.expires_at,
    inviteToken: invite.invite_token,
  };
}

export async function getOrganizations() {
  return (await request<BackendOrganization[]>({ method: "GET", url: "/organizations/" })).map(normalizeOrg);
}

export async function createOrganization(name: string) {
  return normalizeOrg(await request<BackendOrganization>({ method: "POST", url: "/organizations/", data: { name } }));
}

export async function updateOrganization(organizationId: string, name: string) {
  return normalizeOrg(
    await request<BackendOrganization>({
      method: "PATCH",
      url: `/organizations/${organizationId}`,
      data: { name },
    }),
  );
}

export async function getMembers(organizationId: string) {
  return (
    await request<BackendOrganizationMember[]>({ method: "GET", url: `/organizations/${organizationId}/members` })
  ).map(normalizeMember);
}

export async function getInvitations(organizationId: string) {
  return (
    await request<BackendOrganizationInvitation[]>({ method: "GET", url: `/organizations/${organizationId}/invitations` })
  ).map(normalizeInvite);
}

export async function inviteMember(
  organizationId: string,
  email: string,
  role: "viewer" | "member" | "editor" | "admin",
) {
  return normalizeInvite(
    await request<BackendOrganizationInvitation>({
      method: "POST",
      url: `/organizations/${organizationId}/invitations`,
      data: { email, role },
    }),
  );
}

export async function updateMemberRole(
  organizationId: string,
  membershipId: string,
  role: "viewer" | "member" | "editor" | "admin",
) {
  return normalizeMember(
    await request<BackendOrganizationMember>({
      method: "PATCH",
      url: `/organizations/${organizationId}/members/${membershipId}`,
      data: { role },
    }),
  );
}

export async function acceptInvitation(token: string) {
  return normalizeInvite(
    await request<BackendOrganizationInvitation>({
      method: "POST",
      url: "/organizations/invitations/accept",
      data: { token },
    }),
  );
}
