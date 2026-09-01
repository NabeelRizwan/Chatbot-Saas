"use client";

import { Building2, Copy, CreditCard, Loader2, Send, Users } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { hasOrganizationRole } from "@/lib/organization-roles";
import { getSubscription, getUsage } from "@/services/billing-service";
import { createOrganization, getInvitations, getMembers, getOrganizations, inviteMember } from "@/services/organization-service";
import { useAuthStore } from "@/store/auth-store";
import type { Subscription, UsageSummary } from "@/types/billing";
import type { Organization, OrganizationInvitation, OrganizationMember, OrganizationRole } from "@/types/organization";

function formatLimit(value?: number) {
  if (!value) {
    return "Unlimited";
  }
  if (value > 1024 * 1024) {
    return `${Math.round(value / 1024 / 1024)} MB`;
  }
  return value.toLocaleString();
}

function UsageRow({ label, used, limit, bytes = false }: { label: string; used: number; limit?: number; bytes?: boolean }) {
  const percentage = limit ? Math.min(100, Math.round((used / limit) * 100)) : 0;
  return (
    <div>
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium">{label}</span>
        <span className="text-muted-foreground">
          {bytes ? `${(used / 1024 / 1024).toFixed(2)} MB` : used.toLocaleString()} / {formatLimit(limit)}
        </span>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${percentage}%` }} />
      </div>
    </div>
  );
}

export function SettingsClient() {
  const user = useAuthStore((state) => state.user);
  const selectedOrganizationId = useAuthStore((state) => state.selectedOrganizationId);
  const setSelectedOrganization = useAuthStore((state) => state.setSelectedOrganization);
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [members, setMembers] = useState<OrganizationMember[]>([]);
  const [invitations, setInvitations] = useState<OrganizationInvitation[]>([]);
  const [subscription, setSubscription] = useState<Subscription | null>(null);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<Exclude<OrganizationRole, "owner">>("member");
  const [newOrgName, setNewOrgName] = useState("");
  const [loading, setLoading] = useState(true);
  const selectedOrg = useMemo(
    () => organizations.find((org) => org.id === selectedOrganizationId) ?? organizations[0],
    [organizations, selectedOrganizationId],
  );

  async function load() {
    if (!user) {
      setLoading(false);
      return;
    }
    setLoading(true);
    const orgs = await getOrganizations();
    setOrganizations(orgs);
    const org = orgs.find((item) => item.id === selectedOrganizationId) ?? orgs[0];
    if (org) {
      setSelectedOrganization(org.id, org.role);
      const [nextMembers, nextInvites, nextSubscription, nextUsage] = await Promise.all([
        hasOrganizationRole(org.role, "member") ? getMembers(org.id) : Promise.resolve([]),
        hasOrganizationRole(org.role, "admin") ? getInvitations(org.id) : Promise.resolve([]),
        hasOrganizationRole(org.role, "member") ? getSubscription(org.id) : Promise.resolve(null),
        hasOrganizationRole(org.role, "member") ? getUsage(org.id) : Promise.resolve(null),
      ]);
      setMembers(nextMembers);
      setInvitations(nextInvites);
      setSubscription(nextSubscription);
      setUsage(nextUsage);
    }
    setLoading(false);
  }

  useEffect(() => {
    void load();
  }, [user, selectedOrganizationId]);

  async function submitInvite() {
    if (!selectedOrg || !inviteEmail.trim()) {
      return;
    }
    const invite = await inviteMember(selectedOrg.id, inviteEmail.trim(), inviteRole);
    setInvitations((current) => [invite, ...current]);
    setInviteEmail("");
  }

  async function submitOrg() {
    if (!newOrgName.trim()) {
      return;
    }
    const org = await createOrganization(newOrgName.trim());
    setOrganizations((current) => [...current, org]);
    setSelectedOrganization(org.id, org.role);
    setNewOrgName("");
  }

  if (!user) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Sign in required</CardTitle>
          <CardDescription>Create an account or sign in to manage organizations, usage, and billing.</CardDescription>
        </CardHeader>
      </Card>
    );
  }

  if (loading) {
    return (
      <div className="flex min-h-80 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm font-medium text-primary">Workspace settings</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-normal">Organizations and billing</h1>
      </div>

      <div className="grid gap-6 xl:grid-cols-[360px_1fr]">
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Building2 className="h-5 w-5 text-primary" />
                Organizations
              </CardTitle>
              <CardDescription>Switch workspaces and create a new one.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {organizations.map((org) => (
                <button
                  key={org.id}
                  type="button"
                  onClick={() => setSelectedOrganization(org.id, org.role)}
                  className={`w-full rounded-lg border p-3 text-left text-sm transition-colors ${
                    selectedOrg?.id === org.id ? "border-primary bg-primary/5" : "border-border hover:bg-muted"
                  }`}
                >
                  <span className="font-medium">{org.name}</span>
                  <span className="mt-1 block text-xs text-muted-foreground">{org.role}</span>
                </button>
              ))}
              <div className="flex gap-2 pt-2">
                <input
                  value={newOrgName}
                  onChange={(event) => setNewOrgName(event.target.value)}
                  className="h-10 min-w-0 flex-1 rounded-lg border border-input bg-background px-3 text-sm outline-none"
                  placeholder="New organization"
                />
                <Button onClick={() => void submitOrg()}>Create</Button>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <CreditCard className="h-5 w-5 text-primary" />
                Plan
              </CardTitle>
              <CardDescription>Billing foundation prepared for checkout.</CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-semibold">{subscription?.plan.name ?? "Free"}</p>
              <p className="mt-1 text-sm text-muted-foreground">{subscription?.status ?? "active"}</p>
              <Button className="mt-4 w-full" variant="outline">
                Upgrade hooks ready
              </Button>
            </CardContent>
          </Card>
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Users className="h-5 w-5 text-primary" />
                Team members
              </CardTitle>
              <CardDescription>Owners and admins can invite teammates.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {hasOrganizationRole(selectedOrg?.role, "admin") && <div className="grid gap-2 sm:grid-cols-[1fr_140px_auto]">
                <input
                  value={inviteEmail}
                  onChange={(event) => setInviteEmail(event.target.value)}
                  className="h-10 rounded-lg border border-input bg-background px-3 text-sm outline-none"
                  placeholder="teammate@example.com"
                />
                <select
                  value={inviteRole}
                  onChange={(event) => setInviteRole(event.target.value as Exclude<OrganizationRole, "owner">)}
                  className="h-10 rounded-lg border border-input bg-background px-3 text-sm outline-none"
                >
                  <option value="viewer">Viewer</option>
                  <option value="member">Member</option>
                  <option value="editor">Editor</option>
                  {selectedOrg?.role === "owner" && <option value="admin">Admin</option>}
                </select>
                <Button onClick={() => void submitInvite()}>
                  <Send className="h-4 w-4" />
                  Invite
                </Button>
              </div>}

              <div className="divide-y divide-border rounded-lg border border-border">
                {members.map((member) => (
                  <div key={member.id} className="flex items-center justify-between gap-3 p-3 text-sm">
                    <div>
                      <p className="font-medium">{member.name}</p>
                      <p className="text-muted-foreground">{member.email}</p>
                    </div>
                    <span className="rounded-full bg-muted px-2 py-1 text-xs capitalize text-muted-foreground">{member.role}</span>
                  </div>
                ))}
              </div>

              {invitations.length > 0 && (
                <div className="space-y-2">
                  <p className="text-sm font-medium">Pending invitations</p>
                  {invitations.map((invite) => (
                    <div key={invite.id} className="flex items-center justify-between gap-3 rounded-lg border border-border p-3 text-sm">
                      <div>
                        <p className="font-medium">{invite.email}</p>
                        <p className="text-xs text-muted-foreground">{invite.role} · {invite.status}</p>
                      </div>
                      {invite.inviteToken && (
                        <Button size="sm" variant="outline" onClick={() => navigator.clipboard.writeText(invite.inviteToken ?? "")}>
                          <Copy className="h-4 w-4" />
                          Token
                        </Button>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Usage</CardTitle>
              <CardDescription>Monthly usage for the selected organization.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              <UsageRow label="Successful generated messages" used={usage?.usage.messages_used ?? 0} limit={usage?.limits.monthly_messages} />
              <UsageRow label="Bots" used={usage?.usage.bots_used ?? 0} limit={usage?.limits.max_bots} />
              <UsageRow label="Active knowledge resources" used={usage?.usage.documents_used ?? 0} limit={usage?.limits.max_documents} />
              <UsageRow label="Logical knowledge storage" used={usage?.usage.logical_storage_bytes ?? 0} limit={usage?.limits.storage_bytes} bytes />
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
