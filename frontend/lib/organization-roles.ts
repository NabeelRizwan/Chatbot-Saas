import type { OrganizationRole } from "@/types/organization";

export const ORGANIZATION_ROLE_ORDER: Record<OrganizationRole, number> = {
  viewer: 1,
  member: 2,
  editor: 3,
  admin: 4,
  owner: 5,
};

export function hasOrganizationRole(role: OrganizationRole | null | undefined, minimum: OrganizationRole) {
  return Boolean(role && ORGANIZATION_ROLE_ORDER[role] >= ORGANIZATION_ROLE_ORDER[minimum]);
}
