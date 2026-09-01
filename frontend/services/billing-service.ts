import { request } from "@/services/api";
import type { BackendPlan, BackendSubscription, BackendUsageSummary, Plan, Subscription, UsageSummary } from "@/types/billing";

function normalizePlan(plan: BackendPlan): Plan {
  return {
    code: plan.code,
    name: plan.name,
    monthlyPriceCents: plan.monthly_price_cents,
    limits: plan.limits,
  };
}

export async function getPlans() {
  return (await request<BackendPlan[]>({ method: "GET", url: "/billing/plans" })).map(normalizePlan);
}

export async function getSubscription(organizationId: string): Promise<Subscription> {
  const response = await request<BackendSubscription>({
    method: "GET",
    url: `/billing/organizations/${organizationId}/subscription`,
  });
  return {
    organizationId: String(response.organization_id),
    status: response.status,
    plan: normalizePlan(response.plan),
  };
}

export async function getUsage(organizationId: string): Promise<UsageSummary> {
  const response = await request<BackendUsageSummary>({
    method: "GET",
    url: `/billing/organizations/${organizationId}/usage`,
  });
  return {
    organizationId: String(response.organization_id),
    month: response.month,
    currentPlan: response.current_plan,
    currentPeriod: response.current_period,
    usage: response.usage,
    limits: response.limits,
    metering: response.metering,
    subscriptionStatus: response.subscription_status,
  };
}
