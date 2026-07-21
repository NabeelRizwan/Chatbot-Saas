"use client";

import { BarChart3, Bot, Building2, CreditCard, Database, Loader2, Save, Send, UserRound, Users, Zap, Clock, HelpCircle, Sparkles, CheckCircle, ShieldCheck, ShieldOff, Trash2, Key, Activity, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getBotAnalyticsSummary, getOrganizationAnalyticsDetails } from "@/services/analytics-service";
import { updateProfile } from "@/services/auth-service";
import { getPlans, getSubscription, getUsage } from "@/services/billing-service";
import { getBots } from "@/services/bot-service";
import { createOrganization, getInvitations, getMembers, getOrganizations, inviteMember, updateMemberRole, updateOrganization } from "@/services/organization-service";
import { adminService, type PlatformKey } from "@/services/admin-service";
import { useAuthStore } from "@/store/auth-store";
import { useToastStore } from "@/store/toast-store";
import { API_BASE_URL } from "@/services/api";
import type { AnalyticsSummary } from "@/types/analytics";
import type { Plan, Subscription, UsageSummary } from "@/types/billing";
import type { Bot as BotType } from "@/types/bot";
import type { Organization, OrganizationInvitation, OrganizationMember } from "@/types/organization";

type PlatformView = "settings" | "organization" | "team" | "billing" | "analytics" | "profile" | "admin-keys";

function formatLimit(value?: number) {
  if (!value) return "Unlimited";
  if (value > 1024 * 1024) return `${Math.round(value / 1024 / 1024)} MB`;
  return value.toLocaleString();
}

function UsageRow({ label, used, limit }: { label: string; used: number; limit?: number }) {
  const percentage = limit ? Math.min(100, Math.round((used / limit) * 100)) : 0;
  return (
    <div>
      <div className="flex items-center justify-between gap-3 text-sm">
        <span className="font-medium">{label}</span>
        <span className="text-muted-foreground">{used.toLocaleString()} / {formatLimit(limit)}</span>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${percentage}%` }} />
      </div>
    </div>
  );
}

function Metric({ label, value, icon: Icon }: { label: string; value: string | number; icon: LucideIcon }) {
  return (
    <Card>
      <CardContent className="flex items-center justify-between p-5">
        <div>
          <p className="text-sm text-muted-foreground">{label}</p>
          <p className="mt-2 text-2xl font-semibold tracking-normal">{value}</p>
        </div>
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Icon className="h-5 w-5" />
        </div>
      </CardContent>
    </Card>
  );
}

const drawSVGLineChart = (data: { date: string; conversations: number; messages: number }[]) => {
  if (!data || data.length === 0) return null;
  const width = 500;
  const height = 200;
  const paddingX = 40;
  const paddingY = 25;
  const chartWidth = width - paddingX * 2;
  const chartHeight = height - paddingY * 2;

  const maxVal = Math.max(...data.map(d => Math.max(d.conversations, d.messages)), 5);
  
  const getPoints = (key: "conversations" | "messages") => {
    return data.map((d, index) => {
      const x = paddingX + (index / (data.length - 1)) * chartWidth;
      const y = height - paddingY - (d[key] / maxVal) * chartHeight;
      return { x, y };
    });
  };

  const convPoints = getPoints("conversations");
  const msgPoints = getPoints("messages");

  const makePath = (points: { x: number; y: number }[]) => {
    return points.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");
  };

  const makeAreaPath = (points: { x: number; y: number }[]) => {
    if (points.length === 0) return "";
    const linePath = makePath(points);
    return `${linePath} L ${points[points.length - 1].x.toFixed(1)} ${(height - paddingY).toFixed(1)} L ${points[0].x.toFixed(1)} ${(height - paddingY).toFixed(1)} Z`;
  };

  const convPath = makePath(convPoints);
  const convArea = makeAreaPath(convPoints);
  const msgPath = makePath(msgPoints);
  const msgArea = makeAreaPath(msgPoints);

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-auto overflow-visible">
      <defs>
        <linearGradient id="convGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#3b82f6" stopOpacity="0.2" />
          <stop offset="100%" stopColor="#3b82f6" stopOpacity="0.0" />
        </linearGradient>
        <linearGradient id="msgGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.2" />
          <stop offset="100%" stopColor="#38bdf8" stopOpacity="0.0" />
        </linearGradient>
      </defs>
      
      {/* Grid Lines */}
      {[0, 0.25, 0.5, 0.75, 1].map((r, i) => {
        const y = paddingY + r * chartHeight;
        const value = Math.round(maxVal * (1 - r));
        return (
          <g key={i} className="opacity-30">
            <line x1={paddingX} y1={y} x2={width - paddingX} y2={y} stroke="currentColor" strokeWidth="0.5" strokeDasharray="3 3" />
            <text x={paddingX - 8} y={y + 3} textAnchor="end" className="fill-muted-foreground text-[8px] font-bold">{value}</text>
          </g>
        );
      })}

      {/* Area Fills */}
      <path d={convArea} fill="url(#convGrad)" />
      <path d={msgArea} fill="url(#msgGrad)" />

      {/* Paths */}
      <path d={convPath} fill="none" stroke="#3b82f6" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <path d={msgPath} fill="none" stroke="#38bdf8" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />

      {/* Data Circles */}
      {convPoints.map((p, i) => (
        <circle key={i} cx={p.x} cy={p.y} r="3" fill="#3b82f6" stroke="white" strokeWidth="1" />
      ))}
      {msgPoints.map((p, i) => (
        <circle key={i} cx={p.x} cy={p.y} r="2.5" fill="#38bdf8" stroke="white" strokeWidth="1" />
      ))}

      {/* X Axis Labels */}
      {data.map((d, index) => {
        const x = paddingX + (index / (data.length - 1)) * chartWidth;
        const parts = d.date.split("-");
        const formattedDate = parts.length === 3 ? `${parts[1]}/${parts[2]}` : d.date;
        return (
          <text key={index} x={x} y={height - paddingY + 14} textAnchor="middle" className="fill-muted-foreground text-[8px] font-bold">
            {formattedDate}
          </text>
        );
      })}
    </svg>
  );
};

const drawSVGDonutChart = (bots: { name: string; conversations: number }[]) => {
  if (!bots || bots.length === 0) {
    return <div className="text-xs text-muted-foreground p-8 text-center font-medium">No bot metrics available.</div>;
  }
  const total = bots.reduce((sum, b) => sum + b.conversations, 0);
  if (total === 0) {
    return <div className="text-xs text-muted-foreground p-8 text-center font-medium">No active chats recorded.</div>;
  }

  const radius = 50;
  const strokeWidth = 10;
  const circum = 2 * Math.PI * radius;
  const center = 75;

  let currentOffset = 0;
  const colors = ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6"];

  return (
    <div className="flex flex-col sm:flex-row items-center gap-6 justify-center">
      <div className="relative w-32 h-32">
        <svg viewBox="0 0 150 150" className="w-full h-full transform -rotate-90">
          <circle cx={center} cy={center} r={radius} fill="transparent" stroke="var(--muted)" strokeWidth={strokeWidth} className="opacity-20" />
          {bots.map((b, i) => {
            const percentage = b.conversations / total;
            const strokeDash = circum * percentage;
            const strokeOffset = circum - currentOffset;
            currentOffset += strokeDash;
            return (
              <circle
                key={i}
                cx={center}
                cy={center}
                r={radius}
                fill="transparent"
                stroke={colors[i % colors.length]}
                strokeWidth={strokeWidth}
                strokeDasharray={`${strokeDash} ${circum}`}
                strokeDashoffset={strokeOffset}
                strokeLinecap="round"
                className="transition-all duration-500"
              />
            );
          })}
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-lg font-bold text-foreground leading-none">{total}</span>
          <span className="text-[8px] text-muted-foreground uppercase font-bold tracking-wider mt-1">Total Chats</span>
        </div>
      </div>

      <div className="flex-1 space-y-2 min-w-[150px]">
        {bots.map((b, i) => (
          <div key={i} className="flex items-center justify-between text-xs font-semibold">
            <div className="flex items-center gap-2 truncate max-w-[150px]">
              <span className="h-2 w-2 rounded-full shrink-0" style={{ backgroundColor: colors[i % colors.length] }} />
              <span className="truncate text-foreground">{b.name}</span>
            </div>
            <span className="text-muted-foreground font-medium">{b.conversations} ({Math.round((b.conversations / total) * 100)}%)</span>
          </div>
        ))}
      </div>
    </div>
  );
};

export function PlatformClient({ view }: { view: PlatformView }) {
  const user = useAuthStore((state) => state.user);
  const setUser = useAuthStore((state) => state.setUser);
  const selectedOrganizationId = useAuthStore((state) => state.selectedOrganizationId);
  const setSelectedOrganizationId = useAuthStore((state) => state.setSelectedOrganizationId);
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [members, setMembers] = useState<OrganizationMember[]>([]);
  const [invitations, setInvitations] = useState<OrganizationInvitation[]>([]);
  const [subscription, setSubscription] = useState<Subscription | null>(null);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [bots, setBots] = useState<BotType[]>([]);
  const [analytics, setAnalytics] = useState<AnalyticsSummary[]>([]);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [orgAnalytics, setOrgAnalytics] = useState<any>(null);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<"admin" | "member">("member");
  const [profileName, setProfileName] = useState("");
  const [newOrgName, setNewOrgName] = useState("");
  const [renameValue, setRenameValue] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // V3 unified account states
  const accessToken = useAuthStore((state) => state.accessToken);
  const showToast = useToastStore((state) => state.showToast);
  const [activeAccountTab, setActiveAccountTab] = useState<"profile" | "security" | "preferences" | "usage">("profile");
  const [bio, setBio] = useState("");
  const [avatarUrl, setAvatarUrl] = useState("");
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [sessionsList, setSessionsList] = useState<{ id: number; created_at: string; expires_at: string }[]>([]);
  const [theme, setTheme] = useState("system");
  const [language, setLanguage] = useState("en");
  const [emailNotifications, setEmailNotifications] = useState(true);
  const [inAppNotifications, setInAppNotifications] = useState(true);

  // Admin keys state
  const [platformKeys, setPlatformKeys] = useState<PlatformKey[]>([]);
  const [poolStatus, setPoolStatus] = useState<Record<string, { available: number; assigned: number; disabled: number; total: number }>>({});
  const [newKeyProvider, setNewKeyProvider] = useState("gemini");
  const [newKeyValue, setNewKeyValue] = useState("");
  const [newKeyLabel, setNewKeyLabel] = useState("");
  const [keysLoading, setKeysLoading] = useState(false);

  const selectedOrg = useMemo(
    () => organizations.find((org) => org.id === selectedOrganizationId) ?? organizations[0],
    [organizations, selectedOrganizationId],
  );
  const totals = useMemo(
    () => ({
      conversations: analytics.reduce((sum, item) => sum + item.totalConversations, 0),
      messages: analytics.reduce((sum, item) => sum + item.totalMessages, 0),
      recentMessages: analytics.reduce((sum, item) => sum + item.recentMessages24h, 0),
      errors: analytics.reduce((sum, item) => sum + item.erroredMessages, 0),
    }),
    [analytics],
  );

  const fetchPlatformKeys = async () => {
    setKeysLoading(true);
    try {
      const [keys, status] = await Promise.all([
        adminService.listPlatformKeys(),
        adminService.getPoolStatus(),
      ]);
      setPlatformKeys(keys);
      setPoolStatus(status.providers);
    } catch (err) {
      console.error("Error fetching platform keys:", err);
    } finally {
      setKeysLoading(false);
    }
  };

  const handleAddPlatformKey = async () => {
    if (!newKeyValue.trim()) return;
    setSaving(true);
    try {
      await adminService.addPlatformKey({
        provider: newKeyProvider,
        api_key: newKeyValue.trim(),
        label: newKeyLabel.trim() || undefined,
      });
      setNewKeyValue("");
      setNewKeyLabel("");
      showToast({ title: "Platform key added", description: "Key encrypted and added to pool.", variant: "success" });
      await fetchPlatformKeys();
    } catch (err) {
      showToast({
        title: "Error adding key",
        description: err instanceof Error ? err.message : "Unable to add key.",
        variant: "error",
      });
    } finally {
      setSaving(false);
    }
  };

  const handleEnableKey = async (keyId: number) => {
    try {
      await adminService.enableKey(keyId);
      showToast({ title: "Key enabled", description: "Key is now available for allocation.", variant: "success" });
      await fetchPlatformKeys();
    } catch (err) {
      showToast({ title: "Error", description: err instanceof Error ? err.message : "Could not enable key.", variant: "error" });
    }
  };

  const handleDisableKey = async (keyId: number) => {
    if (!confirm("Disable this key? If assigned to a bot, the bot will lose its platform key.")) return;
    try {
      await adminService.disableKey(keyId);
      showToast({ title: "Key disabled", description: "Key is now disabled.", variant: "success" });
      await fetchPlatformKeys();
    } catch (err) {
      showToast({ title: "Error", description: err instanceof Error ? err.message : "Could not disable key.", variant: "error" });
    }
  };

  const handleDeletePlatformKey = async (keyId: number) => {
    if (!confirm("Permanently delete this platform key? This cannot be undone.")) return;
    try {
      await adminService.deleteKey(keyId);
      showToast({ title: "Platform key deleted", description: "Key permanently removed.", variant: "success" });
      await fetchPlatformKeys();
    } catch (err) {
      showToast({ title: "Cannot delete key", description: err instanceof Error ? err.message : "Unable to delete key.", variant: "error" });
    }
  };

  const fetchSessions = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/auth/sessions`, {
        headers: { Authorization: `Bearer ${accessToken}` }
      });
      if (res.ok) {
        const data = await res.json();
        setSessionsList(data);
      }
    } catch (err) {
      console.error("Error loading sessions:", err);
    }
  };

  async function load() {
    if (!user) return;
    setLoading(true);
    setError(null);
    try {
      setProfileName(user.name);
      setBio(user.bio || "");
      setAvatarUrl(user.avatar_url || "");
      setTheme(user.preferences?.theme || "system");
      setLanguage(user.preferences?.language || "en");
      setEmailNotifications(user.preferences?.notifications?.email ?? true);
      setInAppNotifications(user.preferences?.notifications?.in_app ?? true);

      const [orgs, nextPlans, nextBots] = await Promise.all([getOrganizations(), getPlans(), getBots()]);
      setOrganizations(orgs);
      setPlans(nextPlans);
      setBots(nextBots);
      const org = orgs.find((item) => item.id === selectedOrganizationId) ?? orgs[0];
      if (org) {
        setSelectedOrganizationId(org.id);
        setRenameValue(org.name);
        const [nextMembers, nextInvites, nextSubscription, nextUsage, nextAnalytics, orgDetails] = await Promise.all([
          getMembers(org.id),
          org.role === "member" ? Promise.resolve([]) : getInvitations(org.id),
          getSubscription(org.id),
          getUsage(org.id),
          Promise.all(nextBots.map((bot) => getBotAnalyticsSummary(bot.id).catch(() => null))),
          getOrganizationAnalyticsDetails(org.id).catch(() => null),
        ]);
        setMembers(nextMembers);
        setInvitations(nextInvites);
        setSubscription(nextSubscription);
        setUsage(nextUsage);
        setAnalytics(nextAnalytics.filter((item): item is AnalyticsSummary => Boolean(item)));
        setOrgAnalytics(orgDetails);
      }
      await fetchSessions();
      if (user?.is_admin) {
        await fetchPlatformKeys();
      }
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load platform data.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, [user, selectedOrganizationId]);

  async function submitOrg() {
    if (!newOrgName.trim()) return;
    setSaving(true);
    try {
      const org = await createOrganization(newOrgName.trim());
      setOrganizations((current) => [...current, org]);
      setSelectedOrganizationId(org.id);
      setNewOrgName("");
    } finally {
      setSaving(false);
    }
  }

  async function submitRename() {
    if (!selectedOrg || !renameValue.trim()) return;
    setSaving(true);
    try {
      const org = await updateOrganization(selectedOrg.id, renameValue.trim());
      setOrganizations((current) => current.map((item) => (item.id === org.id ? org : item)));
    } finally {
      setSaving(false);
    }
  }

  async function submitInvite() {
    if (!selectedOrg || !inviteEmail.trim()) return;
    setSaving(true);
    try {
      const invite = await inviteMember(selectedOrg.id, inviteEmail.trim(), inviteRole);
      setInvitations((current) => [invite, ...current]);
      setInviteEmail("");
    } finally {
      setSaving(false);
    }
  }

  async function changeRole(member: OrganizationMember, role: "admin" | "member") {
    if (!selectedOrg || member.role === "owner") return;
    const updated = await updateMemberRole(selectedOrg.id, member.id, role);
    setMembers((current) => current.map((item) => (item.id === updated.id ? updated : item)));
  }

  async function submitProfile() {
    if (!profileName.trim()) return;
    setSaving(true);
    try {
      const updated = await updateProfile({
        name: profileName.trim(),
        bio: bio.trim(),
        avatar_url: avatarUrl.trim(),
        preferences: {
          theme,
          language,
          notifications: {
            email: emailNotifications,
            in_app: inAppNotifications
          }
        }
      });
      setUser({
        ...user!,
        name: updated.name,
        bio: updated.bio,
        avatar_url: updated.avatar_url,
        preferences: updated.preferences,
        role: user?.role ?? updated.role
      });
      showToast({
        title: "Profile saved",
        description: "Your changes have been saved successfully.",
        variant: "success"
      });
    } catch (err) {
      showToast({
        title: "Save failed",
        description: err instanceof Error ? err.message : "Unable to save profile.",
        variant: "error"
      });
    } finally {
      setSaving(false);
    }
  }

  async function handleSavePassword() {
    if (!oldPassword || !newPassword) return;
    if (newPassword.length < 8) {
      showToast({
        title: "Validation error",
        description: "New password must be at least 8 characters.",
        variant: "error"
      });
      return;
    }
    setSaving(true);
    try {
      const res = await fetch(`${API_BASE_URL}/auth/change-password`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${accessToken}`
        },
        body: JSON.stringify({ old_password: oldPassword, new_password: newPassword })
      });
      if (res.ok) {
        setOldPassword("");
        setNewPassword("");
        showToast({
          title: "Password updated",
          description: "Your security password has been changed successfully.",
          variant: "success"
        });
      } else {
        const errJson = await res.json();
        throw new Error(errJson.detail || "Incorrect old password.");
      }
    } catch (err) {
      showToast({
        title: "Change failed",
        description: err instanceof Error ? err.message : "Password could not be changed.",
        variant: "error"
      });
    } finally {
      setSaving(false);
    }
  }

  async function handleRevokeSession(sessionId: number) {
    try {
      const res = await fetch(`${API_BASE_URL}/auth/sessions/${sessionId}`, {
        method: "DELETE",
        headers: {
          Authorization: `Bearer ${accessToken}`
        }
      });
      if (res.ok) {
        showToast({
          title: "Session revoked",
          description: "The login session was terminated.",
          variant: "success"
        });
        await fetchSessions();
      } else {
        throw new Error("Failed to revoke session.");
      }
    } catch (err) {
      showToast({
        title: "Revoke failed",
        description: err instanceof Error ? err.message : "Unable to revoke session.",
        variant: "error"
      });
    }
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
        <p className="text-sm font-medium text-primary">SaaS platform</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-normal sm:text-4xl">
          {view === "analytics" ? "Analytics" : view === "billing" ? "Billing and usage" : view === "team" ? "Team" : view === "profile" ? "Profile" : view === "organization" ? "Organization" : "Settings"}
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-muted-foreground">Workspace: {selectedOrg?.name ?? "No organization selected"}</p>
      </div>

      {error && <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">{error}</div>}

      {view === "settings" && (
        <section className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Metric label="Total conversations" value={totals.conversations} icon={BarChart3} />
            <Metric label="Total messages" value={totals.messages} icon={Zap} />
            <Metric label="Uploaded documents" value={usage?.usage.document_uploads ?? 0} icon={Database} />
            <Metric label="Active bots" value={usage?.usage.active_bots ?? bots.length} icon={Bot} />
          </div>
          <Card>
            <CardHeader>
              <CardTitle>Usage trends</CardTitle>
              <CardDescription>Bot activity and usage for the current billing month.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-4 md:grid-cols-3">
                <Metric label="Messages last 24h" value={totals.recentMessages} icon={BarChart3} />
                <Metric label="Errored messages" value={totals.errors} icon={Zap} />
                <Metric label="Tokens used" value={usage?.usage.tokens_used ?? 0} icon={CreditCard} />
              </div>
              <div className="divide-y divide-border rounded-lg border border-border">
                {bots.map((bot) => {
                  const summary = analytics.find((item) => item.botId === bot.id);
                  return (
                    <div key={bot.id} className="flex flex-col gap-2 p-3 text-sm sm:flex-row sm:items-center sm:justify-between">
                      <div>
                        <p className="font-medium">{bot.name}</p>
                        <p className="text-muted-foreground">{summary?.totalConversations ?? 0} conversations - {summary?.totalMessages ?? 0} messages</p>
                      </div>
                      <Button asChild size="sm" variant="outline">
                        <Link href={`/bots/${bot.id}`}>Bot settings</Link>
                      </Button>
                    </div>
                  );
                })}
              </div>
            </CardContent>
          </Card>
        </section>
      )}

      {view === "analytics" && (
        <section className="space-y-6">
          {orgAnalytics ? (
            <>
              {/* Analytics V2 Stats Grid */}
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <Metric label="Total Conversations" value={orgAnalytics.summary.total_conversations} icon={BarChart3} />
                <Metric label="Total Messages" value={orgAnalytics.summary.total_messages} icon={Zap} />
                <Metric label="Active Bots" value={orgAnalytics.summary.active_bots ?? 0} icon={Bot} />
                <Metric label="Total Members" value={orgAnalytics.summary.total_users ?? 0} icon={Users} />
              </div>

              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <Metric label="Conversations Today" value={orgAnalytics.summary.conversations_today ?? 0} icon={BarChart3} />
                <Metric label="Messages Today" value={orgAnalytics.summary.messages_today ?? 0} icon={Zap} />
                <Metric label="Avg Latency" value={orgAnalytics.summary.avg_response_time_ms ? `${(orgAnalytics.summary.avg_response_time_ms / 1000).toFixed(2)}s` : "N/A"} icon={Clock} />
                <Metric label="User Activity Score" value={`${orgAnalytics.summary.user_activity_score ?? 0}/100`} icon={Sparkles} />
              </div>

              <div className="grid gap-4 sm:grid-cols-3">
                <Metric label="Resolution Rate" value={`${orgAnalytics.summary.resolution_rate.toFixed(1)}%`} icon={CheckCircle} />
                <Metric label="Fallback Rate" value={`${orgAnalytics.summary.fallback_rate.toFixed(1)}%`} icon={HelpCircle} />
                <Metric label="Knowledge Hit Rate" value={`${orgAnalytics.summary.hit_rate.toFixed(1)}%`} icon={Database} />
              </div>

              {/* Trends and Insights Grid */}
              <div className="grid gap-6 lg:grid-cols-2">
                
                {/* Daily Trends (Visual SVG Line Chart) */}
                <Card>
                  <CardHeader>
                    <CardTitle>Daily Trends (Past 7 Days)</CardTitle>
                    <CardDescription>
                      <span className="inline-flex items-center gap-1.5 mr-3">
                        <span className="h-2 w-2 rounded-full bg-blue-500" /> Chats
                      </span>
                      <span className="inline-flex items-center gap-1.5">
                        <span className="h-2 w-2 rounded-full bg-sky-400" /> Messages
                      </span>
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="pt-2">
                    {drawSVGLineChart(orgAnalytics.trends)}
                  </CardContent>
                </Card>

                {/* AI Insights Card */}
                <Card className="border border-primary/20 bg-primary/5">
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2"><Sparkles className="h-5 w-5 text-primary" />AI Insights & Gaps</CardTitle>
                    <CardDescription>Automatically analyzed knowledge base weaknesses and user intents.</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4 text-sm">
                    <div>
                      <h4 className="font-semibold text-xs text-muted-foreground uppercase tracking-wider mb-2">Knowledge Gaps</h4>
                      <ul className="list-disc pl-4 space-y-1 text-xs text-foreground font-medium">
                        {orgAnalytics.insights.knowledge_gaps.map((gap: string, idx: number) => (
                          <li key={idx}>{gap}</li>
                        ))}
                      </ul>
                    </div>

                    <div>
                      <h4 className="font-semibold text-xs text-muted-foreground uppercase tracking-wider mb-2">Actionable Suggestions</h4>
                      <ul className="list-disc pl-4 space-y-1 text-xs text-foreground font-medium">
                        {orgAnalytics.insights.suggested_improvements.map((imp: string, idx: number) => (
                          <li key={idx}>{imp}</li>
                        ))}
                      </ul>
                    </div>

                    <div>
                      <h4 className="font-semibold text-xs text-muted-foreground uppercase tracking-wider mb-2">Unanswered / Fallbacks</h4>
                      <div className="flex flex-wrap gap-1 mt-1">
                        {orgAnalytics.insights.unanswered_questions.length === 0 ? (
                          <span className="text-[10px] text-muted-foreground italic">None detected.</span>
                        ) : (
                          orgAnalytics.insights.unanswered_questions.map((q: string, idx: number) => (
                            <span key={idx} className="bg-destructive/10 text-destructive text-[10px] px-2 py-0.5 rounded-full font-bold">
                              "{q}"
                            </span>
                          ))
                        )}
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </div>

              {/* Bot Usage Trends (Donut Chart) and Top Documents Grid */}
              <div className="grid gap-6 lg:grid-cols-2">
                {/* Bot Usage Trends (Donut Chart) */}
                <Card>
                  <CardHeader>
                    <CardTitle>Bot Activity Distribution</CardTitle>
                    <CardDescription>Engagement metrics showing proportion of conversations per chatbot.</CardDescription>
                  </CardHeader>
                  <CardContent className="pt-2">
                    {drawSVGDonutChart(orgAnalytics.top_bots)}
                  </CardContent>
                </Card>

                {/* Top Documents */}
                <Card>
                  <CardHeader>
                    <CardTitle>Top Knowledge Sources</CardTitle>
                    <CardDescription>Largest documents indexed by bot chunk count.</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="divide-y divide-border rounded-lg border border-border overflow-hidden">
                      {orgAnalytics.top_documents.length === 0 ? (
                        <div className="p-4 text-center text-xs text-muted-foreground">No documents indexed yet.</div>
                      ) : (
                        orgAnalytics.top_documents.map((doc: { id: number | string; filename: string; source_type: string; chunk_count: number; token_count: number }) => (
                          <div key={doc.id} className="flex items-center justify-between p-3 text-xs">
                            <div className="truncate max-w-[200px]">
                              <p className="font-semibold text-foreground truncate">{doc.filename}</p>
                              <p className="text-muted-foreground uppercase text-[10px] font-bold">{doc.source_type}</p>
                            </div>
                            <div className="text-right text-muted-foreground">
                              <p className="font-bold text-foreground">{doc.chunk_count} chunks</p>
                              <p className="text-[10px] font-medium">{doc.token_count.toLocaleString()} tokens</p>
                            </div>
                          </div>
                        ))
                      )}
                    </div>
                  </CardContent>
                </Card>
              </div>
            </>
          ) : (
            <div className="p-8 text-center text-muted-foreground font-medium">
              No organization metrics available. Start chatting with your widget to populate data!
            </div>
          )}
        </section>
      )}

      {(view === "organization" || view === "settings") && (
        <section className="grid gap-6 lg:grid-cols-[360px_1fr]">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2"><Building2 className="h-5 w-5 text-primary" />Organizations</CardTitle>
              <CardDescription>Switch workspaces and create new organizations.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {organizations.map((org) => (
                <button key={org.id} type="button" onClick={() => setSelectedOrganizationId(org.id)} className={`w-full rounded-lg border p-3 text-left text-sm transition-colors ${selectedOrg?.id === org.id ? "border-primary bg-primary/5" : "border-border hover:bg-muted"}`}>
                  <span className="font-medium">{org.name}</span>
                  <span className="mt-1 block text-xs text-muted-foreground">{org.role}</span>
                </button>
              ))}
              <div className="flex gap-2 pt-2">
                <input value={newOrgName} onChange={(event) => setNewOrgName(event.target.value)} className="h-10 min-w-0 flex-1 rounded-lg border border-input bg-background px-3 text-sm outline-none" placeholder="New organization" />
                <Button disabled={saving} onClick={() => void submitOrg()}>Create</Button>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Organization settings</CardTitle>
              <CardDescription>Rename the selected workspace.</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3 sm:flex-row">
              <input value={renameValue} onChange={(event) => setRenameValue(event.target.value)} className="h-10 min-w-0 flex-1 rounded-lg border border-input bg-background px-3 text-sm outline-none" placeholder="Organization name" />
              <Button disabled={saving || !selectedOrg} onClick={() => void submitRename()}><Save className="h-4 w-4" />Save</Button>
            </CardContent>
          </Card>
        </section>
      )}

      {(view === "team" || view === "settings") && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Users className="h-5 w-5 text-primary" />Team management</CardTitle>
            <CardDescription>Invite members and manage admin/member roles.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-2 sm:grid-cols-[1fr_140px_auto]">
              <input value={inviteEmail} onChange={(event) => setInviteEmail(event.target.value)} className="h-10 rounded-lg border border-input bg-background px-3 text-sm outline-none" placeholder="teammate@example.com" />
              <select value={inviteRole} onChange={(event) => setInviteRole(event.target.value as "admin" | "member")} className="h-10 rounded-lg border border-input bg-background px-3 text-sm outline-none">
                <option value="member">Member</option>
                <option value="admin">Admin</option>
              </select>
              <Button disabled={saving} onClick={() => void submitInvite()}><Send className="h-4 w-4" />Invite</Button>
            </div>
            <div className="divide-y divide-border rounded-lg border border-border">
              {members.map((member) => (
                <div key={member.id} className="flex flex-col gap-3 p-3 text-sm sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <p className="font-medium">{member.name}</p>
                    <p className="text-muted-foreground">{member.email}</p>
                  </div>
                  {member.role === "owner" ? (
                    <span className="rounded-full bg-muted px-2 py-1 text-xs capitalize text-muted-foreground">owner</span>
                  ) : (
                    <select value={member.role} onChange={(event) => void changeRole(member, event.target.value as "admin" | "member")} className="h-9 rounded-lg border border-input bg-background px-3 text-sm outline-none">
                      <option value="member">Member</option>
                      <option value="admin">Admin</option>
                    </select>
                  )}
                </div>
              ))}
            </div>
            {invitations.length > 0 && (
              <div className="grid gap-2">
                {invitations.map((invite) => (
                  <div key={invite.id} className="rounded-lg border border-border p-3 text-sm">
                    <p className="font-medium">{invite.email}</p>
                    <p className="text-muted-foreground">{invite.role} - {invite.status}{invite.inviteToken ? ` - ${invite.inviteToken}` : ""}</p>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {(view === "billing" || view === "settings") && (
        <section className="grid gap-6 lg:grid-cols-[360px_1fr]">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2"><CreditCard className="h-5 w-5 text-primary" />Subscription</CardTitle>
              <CardDescription>Billing foundation prepared for Stripe checkout.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-2xl font-semibold">{subscription?.plan.name ?? "Free"}</p>
              <p className="text-sm text-muted-foreground">{subscription?.status ?? "active"}</p>
              {plans.map((plan) => (
                <div key={plan.code} className="rounded-lg border border-border p-3 text-sm">
                  <p className="font-medium">{plan.name}</p>
                  <p className="text-muted-foreground">${(plan.monthlyPriceCents / 100).toFixed(0)} / month</p>
                </div>
              ))}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Usage and quotas</CardTitle>
              <CardDescription>Current month: {usage?.month ?? "not available"}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              <UsageRow label="Messages" used={usage?.usage.messages_sent ?? 0} limit={usage?.limits.monthly_messages} />
              <UsageRow label="Active bots" used={usage?.usage.active_bots ?? 0} limit={usage?.limits.max_bots} />
              <UsageRow label="Documents" used={usage?.usage.document_uploads ?? 0} limit={usage?.limits.max_documents} />
              <UsageRow label="Storage" used={usage?.usage.storage_bytes ?? 0} limit={usage?.limits.storage_bytes} />
              <UsageRow label="Tokens" used={usage?.usage.tokens_used ?? 0} />
            </CardContent>
          </Card>
        </section>
      )}

      {(view === "profile" || view === "settings") && (
        <section className="grid gap-6 md:grid-cols-[220px_1fr]">
          <div className="flex flex-col gap-1 text-sm font-semibold text-muted-foreground">
            <button
              onClick={() => setActiveAccountTab("profile")}
              className={`flex items-center gap-2 px-3 py-2 rounded-lg text-left transition-colors ${
                activeAccountTab === "profile" ? "bg-primary/5 text-primary" : "hover:bg-muted hover:text-foreground"
              }`}
            >
              <UserRound className="h-4 w-4" />
              Profile Details
            </button>
            <button
              onClick={() => setActiveAccountTab("security")}
              className={`flex items-center gap-2 px-3 py-2 rounded-lg text-left transition-colors ${
                activeAccountTab === "security" ? "bg-primary/5 text-primary" : "hover:bg-muted hover:text-foreground"
              }`}
            >
              <Clock className="h-4 w-4" />
              Security & Sessions
            </button>
            <button
              onClick={() => setActiveAccountTab("preferences")}
              className={`flex items-center gap-2 px-3 py-2 rounded-lg text-left transition-colors ${
                activeAccountTab === "preferences" ? "bg-primary/5 text-primary" : "hover:bg-muted hover:text-foreground"
              }`}
            >
              <Sparkles className="h-4 w-4" />
              Preferences
            </button>
            <button
              onClick={() => setActiveAccountTab("usage")}
              className={`flex items-center gap-2 px-3 py-2 rounded-lg text-left transition-colors ${
                activeAccountTab === "usage" ? "bg-primary/5 text-primary" : "hover:bg-muted hover:text-foreground"
              }`}
            >
              <BarChart3 className="h-4 w-4" />
              Usage & Limits
            </button>
          </div>

          <div className="space-y-6">
            {activeAccountTab === "profile" && (
              <Card>
                <CardHeader>
                  <CardTitle>Profile Details</CardTitle>
                  <CardDescription>Manage your public profile information, email, and bio.</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="flex items-center gap-4">
                    <div className="h-16 w-16 rounded-full bg-primary/10 text-primary flex items-center justify-center font-bold text-lg border border-primary/20 overflow-hidden shrink-0">
                      {avatarUrl ? <img src={avatarUrl} alt="Avatar" className="h-full w-full object-cover" /> : profileName.substring(0,2).toUpperCase()}
                    </div>
                    <div className="space-y-1.5 flex-1">
                      <label className="text-xs font-semibold text-muted-foreground">Avatar URL</label>
                      <input
                        value={avatarUrl}
                        onChange={(e) => setAvatarUrl(e.target.value)}
                        placeholder="https://example.com/avatar.jpg"
                        className="h-9 w-full rounded-lg border border-input bg-background px-3 text-xs outline-none focus:ring-1 focus:ring-primary/20"
                      />
                    </div>
                  </div>
                  <div className="grid gap-4 sm:grid-cols-2">
                    <label className="space-y-1.5 text-xs font-semibold text-muted-foreground block">
                      <span>Full Name</span>
                      <input
                        value={profileName}
                        onChange={(e) => setProfileName(e.target.value)}
                        className="h-10 w-full rounded-lg border border-input bg-background px-3 text-xs outline-none"
                      />
                    </label>
                    <label className="space-y-1.5 text-xs font-semibold text-muted-foreground block">
                      <span>Email Address</span>
                      <input
                        readOnly
                        value={user?.email ?? ""}
                        className="h-10 w-full rounded-lg border border-input bg-muted px-3 text-xs outline-none cursor-not-allowed"
                      />
                    </label>
                  </div>
                  <label className="space-y-1.5 text-xs font-semibold text-muted-foreground block">
                    <span>Bio / Tagline</span>
                    <textarea
                      value={bio}
                      onChange={(e) => setBio(e.target.value)}
                      placeholder="Write a brief tagline about yourself..."
                      className="min-h-24 w-full rounded-lg border border-input bg-background px-3 py-2 text-xs outline-none resize-y"
                    />
                  </label>
                  <Button disabled={saving || !profileName.trim()} onClick={submitProfile} className="gap-1.5 h-9">
                    <Save className="h-4 w-4" /> Save Profile
                  </Button>
                </CardContent>
              </Card>
            )}

            {activeAccountTab === "security" && (
              <div className="space-y-6">
                <Card>
                  <CardHeader>
                    <CardTitle>Change Password</CardTitle>
                    <CardDescription>Update your password to keep your account secure.</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="grid gap-4 sm:grid-cols-2">
                      <label className="space-y-1.5 text-xs font-semibold text-muted-foreground block">
                        <span>Current Password</span>
                        <input
                          type="password"
                          value={oldPassword}
                          onChange={(e) => setOldPassword(e.target.value)}
                          className="h-10 w-full rounded-lg border border-input bg-background px-3 text-xs outline-none"
                        />
                      </label>
                      <label className="space-y-1.5 text-xs font-semibold text-muted-foreground block">
                        <span>New Password</span>
                        <input
                          type="password"
                          value={newPassword}
                          onChange={(e) => setNewPassword(e.target.value)}
                          className="h-10 w-full rounded-lg border border-input bg-background px-3 text-xs outline-none"
                        />
                      </label>
                    </div>
                    <Button disabled={saving || !oldPassword || !newPassword} onClick={handleSavePassword} className="h-9">
                      Update Password
                    </Button>
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle>Active Login Sessions</CardTitle>
                    <CardDescription>Terminated refresh tokens will log out corresponding devices.</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="divide-y divide-border rounded-lg border border-border overflow-hidden">
                      {sessionsList.length === 0 ? (
                        <div className="p-4 text-center text-xs text-muted-foreground font-medium">No active sessions loaded.</div>
                      ) : (
                        sessionsList.map((s) => (
                          <div key={s.id} className="flex items-center justify-between p-3 text-xs">
                            <div>
                              <p className="font-bold text-foreground">Device Session (ID: {s.id})</p>
                              <p className="text-muted-foreground font-medium">Expires: {new Date(s.expires_at).toLocaleString()}</p>
                            </div>
                            <Button size="sm" variant="outline" className="text-destructive border-destructive/20 hover:bg-destructive/5 h-8 text-[11px]" onClick={() => handleRevokeSession(s.id)}>
                              Revoke
                            </Button>
                          </div>
                        ))
                      )}
                    </div>
                  </CardContent>
                </Card>
              </div>
            )}

            {activeAccountTab === "preferences" && (
              <Card>
                <CardHeader>
                  <CardTitle>System Preferences</CardTitle>
                  <CardDescription>Customize colors, localization language, and system alerts.</CardDescription>
                </CardHeader>
                <CardContent className="space-y-5">
                  <div className="grid gap-4 sm:grid-cols-2">
                    <label className="space-y-1.5 text-xs font-semibold text-muted-foreground block">
                      <span>Visual Theme</span>
                      <select
                        value={theme}
                        onChange={(e) => setTheme(e.target.value)}
                        className="h-10 w-full rounded-lg border border-input bg-background px-3 text-xs outline-none cursor-pointer"
                      >
                        <option value="light">Light Theme</option>
                        <option value="dark">Dark Theme</option>
                        <option value="system">Follow System Settings</option>
                      </select>
                    </label>
                    <label className="space-y-1.5 text-xs font-semibold text-muted-foreground block">
                      <span>Language</span>
                      <select
                        value={language}
                        onChange={(e) => setLanguage(e.target.value)}
                        className="h-10 w-full rounded-lg border border-input bg-background px-3 text-xs outline-none cursor-pointer"
                      >
                        <option value="en">English (US)</option>
                        <option value="es">Español</option>
                        <option value="fr">Français</option>
                        <option value="de">Deutsch</option>
                      </select>
                    </label>
                  </div>

                  <div className="space-y-3 pt-2">
                    <h4 className="text-xs font-bold text-foreground uppercase tracking-wide">Notification Preferences</h4>
                    <label className="flex items-center gap-2.5 text-xs font-semibold text-muted-foreground select-none cursor-pointer">
                      <input
                        type="checkbox"
                        checked={emailNotifications}
                        onChange={(e) => setEmailNotifications(e.target.checked)}
                        className="rounded border-input text-primary focus:ring-primary h-4 w-4"
                      />
                      <span>Receive monthly usage digests and alerts via email</span>
                    </label>
                    <label className="flex items-center gap-2.5 text-xs font-semibold text-muted-foreground select-none cursor-pointer">
                      <input
                        type="checkbox"
                        checked={inAppNotifications}
                        onChange={(e) => setInAppNotifications(e.target.checked)}
                        className="rounded border-input text-primary focus:ring-primary h-4 w-4"
                      />
                      <span>Receive real-time fallback alerts in-app</span>
                    </label>
                  </div>

                  <Button disabled={saving} onClick={submitProfile} className="gap-1.5 h-9">
                    <Save className="h-4 w-4" /> Save Preferences
                  </Button>
                </CardContent>
              </Card>
            )}

            {activeAccountTab === "usage" && (
              <Card>
                <CardHeader>
                  <CardTitle>Usage and Quotas</CardTitle>
                  <CardDescription>Track monthly quotas and resource usage details.</CardDescription>
                </CardHeader>
                <CardContent className="space-y-5">
                  <UsageRow label="Messages" used={usage?.usage.messages_sent ?? 0} limit={usage?.limits.monthly_messages} />
                  <UsageRow label="Active bots" used={usage?.usage.active_bots ?? 0} limit={usage?.limits.max_bots} />
                  <UsageRow label="Documents" used={usage?.usage.document_uploads ?? 0} limit={usage?.limits.max_documents} />
                  <UsageRow label="Storage" used={usage?.usage.storage_bytes ?? 0} limit={usage?.limits.storage_bytes} />
                  <UsageRow label="Tokens" used={usage?.usage.tokens_used ?? 0} />
                </CardContent>
              </Card>
            )}
          </div>
        </section>
      )}

      {user?.is_admin && (view === "admin-keys" || view === "settings") && (
        <div className="space-y-6">
          {/* Pool Availability Summary */}
          {Object.keys(poolStatus).length > 0 && (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {Object.entries(poolStatus).map(([provider, counts]) => (
                <Card key={provider} className="border border-border">
                  <CardContent className="p-4">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-bold capitalize text-foreground">{provider}</span>
                      <span className="text-[10px] bg-primary/10 text-primary px-2 py-0.5 rounded font-bold">
                        {counts.total} total
                      </span>
                    </div>
                    <div className="flex gap-2 flex-wrap">
                      <span className="text-[10px] bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-400 px-2 py-0.5 rounded font-bold">
                        {counts.available} available
                      </span>
                      <span className="text-[10px] bg-indigo-50 text-indigo-700 dark:bg-indigo-950/30 dark:text-indigo-400 px-2 py-0.5 rounded font-bold">
                        {counts.assigned} assigned
                      </span>
                      {counts.disabled > 0 && (
                        <span className="text-[10px] bg-amber-50 text-amber-700 dark:bg-amber-950/30 dark:text-amber-400 px-2 py-0.5 rounded font-bold">
                          {counts.disabled} disabled
                        </span>
                      )}
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}

          <Card className="border border-border">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Key className="h-5 w-5 text-primary" />
                Platform API Key Pool
              </CardTitle>
              <CardDescription>
                Admin-managed provider keys allocated 1:1 to bots. Keys are encrypted at rest — never stored in plaintext.
                Each bot using "Platform Managed" gets its own dedicated key.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              {/* Add Key Form */}
              <div className="rounded-xl border border-dashed border-border p-5 bg-muted/20 space-y-4">
                <div className="flex items-center gap-2 mb-1">
                  <ShieldCheck className="h-4 w-4 text-primary" />
                  <h4 className="text-xs font-bold text-foreground uppercase tracking-wide">Add New Provider Key</h4>
                </div>
                <p className="text-[11px] text-muted-foreground">
                  The key will be encrypted with AES-256 (Fernet) before storage. The plaintext is never persisted.
                </p>
                <div className="grid gap-3 sm:grid-cols-[160px_1fr_1fr_auto] items-end">
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold text-muted-foreground uppercase">AI Provider</label>
                    <select
                      value={newKeyProvider}
                      onChange={(e) => setNewKeyProvider(e.target.value)}
                      className="h-9 w-full rounded-md border border-input bg-background px-3 text-xs outline-none focus:ring-2 focus:ring-primary/20"
                    >
                      <option value="gemini">Gemini</option>
                      <option value="openai">OpenAI</option>
                      <option value="claude">Claude</option>
                      <option value="grok">Grok</option>
                    </select>
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold text-muted-foreground uppercase">API Key (plaintext)</label>
                    <input
                      type="password"
                      placeholder="AIza... or sk-..."
                      value={newKeyValue}
                      onChange={(e) => setNewKeyValue(e.target.value)}
                      className="h-9 w-full rounded-md border border-input bg-background px-3 text-xs outline-none font-mono focus:ring-2 focus:ring-primary/20"
                      autoComplete="new-password"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-[10px] font-bold text-muted-foreground uppercase">Label (optional)</label>
                    <input
                      type="text"
                      placeholder="e.g. Production Gemini Key 1"
                      value={newKeyLabel}
                      onChange={(e) => setNewKeyLabel(e.target.value)}
                      className="h-9 w-full rounded-md border border-input bg-background px-3 text-xs outline-none focus:ring-2 focus:ring-primary/20"
                    />
                  </div>
                  <Button
                    disabled={saving || !newKeyValue.trim()}
                    onClick={handleAddPlatformKey}
                    size="sm"
                    className="h-9 gap-1.5"
                  >
                    <ShieldCheck className="h-3.5 w-3.5" />
                    {saving ? "Adding..." : "Add & Encrypt"}
                  </Button>
                </div>
              </div>

              {/* Keys Table */}
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <h4 className="text-xs font-bold text-foreground uppercase tracking-wide">Key Pool</h4>
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 text-[11px] gap-1"
                    onClick={fetchPlatformKeys}
                    disabled={keysLoading}
                  >
                    {keysLoading ? <Loader2 className="h-3 w-3 animate-spin" /> : <Activity className="h-3 w-3" />}
                    Refresh
                  </Button>
                </div>

                {keysLoading ? (
                  <div className="flex items-center justify-center py-8">
                    <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                  </div>
                ) : platformKeys.length === 0 ? (
                  <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border bg-muted/10 py-12">
                    <Key className="h-8 w-8 text-muted-foreground/40" />
                    <p className="text-sm text-muted-foreground font-medium">No platform API keys in pool</p>
                    <p className="text-xs text-muted-foreground">Add your first provider key above to get started.</p>
                  </div>
                ) : (
                  <div className="overflow-hidden rounded-xl border border-border">
                    {/* Table Header */}
                    <div className="hidden sm:grid sm:grid-cols-[1.5fr_1.2fr_1fr_1fr_1fr_1.2fr_auto] gap-3 px-4 py-2.5 bg-muted/40 text-[10px] font-bold text-muted-foreground uppercase tracking-wide">
                      <span>Provider / Key</span>
                      <span>Status</span>
                      <span>Assigned Bot</span>
                      <span>Requests</span>
                      <span>Tokens Used</span>
                      <span>Last Used</span>
                      <span>Actions</span>
                    </div>

                    <div className="divide-y divide-border">
                      {platformKeys.map((k) => (
                        <div
                          key={k.id}
                          className="grid grid-cols-1 sm:grid-cols-[1.5fr_1.2fr_1fr_1fr_1fr_1.2fr_auto] gap-3 px-4 py-3.5 text-xs hover:bg-muted/5 transition-colors items-center"
                        >
                          {/* Provider + masked key */}
                          <div className="flex flex-col gap-0.5">
                            <div className="flex items-center gap-1.5">
                              <span className="capitalize font-bold bg-primary/10 text-primary px-1.5 py-0.5 rounded text-[10px]">
                                {k.provider}
                              </span>
                              {k.label && (
                                <span className="text-muted-foreground text-[10px] truncate max-w-[120px]">{k.label}</span>
                              )}
                            </div>
                            <span className="font-mono text-[10px] text-muted-foreground">{k.masked_key ?? "**** encrypted ****"}</span>
                          </div>

                          {/* Status badge */}
                          <div>
                            {k.status === "available" && (
                              <span className="inline-flex items-center gap-1 text-[10px] bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-400 px-2 py-0.5 rounded-full font-bold">
                                <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full" />
                                Available
                              </span>
                            )}
                            {k.status === "assigned" && (
                              <span className="inline-flex items-center gap-1 text-[10px] bg-indigo-50 text-indigo-700 dark:bg-indigo-950/30 dark:text-indigo-400 px-2 py-0.5 rounded-full font-bold">
                                <span className="w-1.5 h-1.5 bg-indigo-500 rounded-full" />
                                Assigned
                              </span>
                            )}
                            {k.status === "disabled" && (
                              <span className="inline-flex items-center gap-1 text-[10px] bg-amber-50 text-amber-700 dark:bg-amber-950/30 dark:text-amber-400 px-2 py-0.5 rounded-full font-bold">
                                <span className="w-1.5 h-1.5 bg-amber-500 rounded-full" />
                                Disabled
                              </span>
                            )}
                          </div>

                          {/* Assigned bot */}
                          <div>
                            {k.bot ? (
                              <span className="text-[11px] font-semibold text-foreground">{k.bot.name}</span>
                            ) : (
                              <span className="text-[11px] text-muted-foreground">—</span>
                            )}
                          </div>

                          {/* Requests */}
                          <div className="font-mono text-[11px] text-foreground">
                            {(k.requests_count ?? 0).toLocaleString()}
                          </div>

                          {/* Tokens used */}
                          <div className="font-mono text-[11px] text-foreground">
                            {(k.tokens_used ?? 0).toLocaleString()}
                          </div>

                          {/* Last used */}
                          <div className="text-[11px] text-muted-foreground">
                            {k.last_used_at
                              ? new Date(k.last_used_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
                              : "Never"}
                          </div>

                          {/* Actions */}
                          <div className="flex items-center gap-1.5">
                            {k.status === "disabled" ? (
                              <button
                                onClick={() => handleEnableKey(k.id)}
                                title="Enable key"
                                className="h-7 w-7 rounded flex items-center justify-center bg-emerald-50 text-emerald-600 hover:bg-emerald-100 border border-emerald-200 transition-colors"
                              >
                                <ShieldCheck className="h-3.5 w-3.5" />
                              </button>
                            ) : (
                              <button
                                onClick={() => handleDisableKey(k.id)}
                                title="Disable key"
                                className="h-7 w-7 rounded flex items-center justify-center bg-amber-50 text-amber-600 hover:bg-amber-100 border border-amber-200 transition-colors"
                              >
                                <ShieldOff className="h-3.5 w-3.5" />
                              </button>
                            )}
                            <button
                              onClick={() => handleDeletePlatformKey(k.id)}
                              title="Delete key"
                              className="h-7 w-7 rounded flex items-center justify-center bg-red-50 text-red-600 hover:bg-red-100 border border-red-200 transition-colors"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
