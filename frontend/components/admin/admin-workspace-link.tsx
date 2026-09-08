"use client";

import Link from "next/link";
import { useAuthStore } from "@/store/auth-store";

/** Enter the existing workspace screens as the authenticated platform operator. */
export function AdminWorkspaceLink({ organizationId, href, children }: {
  organizationId: number; href: string; children: React.ReactNode;
}) {
  return <Link className="text-primary underline" href={href} onClick={() =>
    useAuthStore.getState().setSelectedOrganization(String(organizationId), "owner")
  }>{children}</Link>;
}
