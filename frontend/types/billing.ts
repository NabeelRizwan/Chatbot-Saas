export type Plan = {
  code: string;
  name: string;
  monthlyPriceCents: number;
  limits: Record<string, number>;
};

export type Subscription = {
  organizationId: string;
  status: string;
  plan: Plan;
};

export type UsageSummary = {
  organizationId: string;
  month: string;
  usage: Record<string, number>;
  limits: Record<string, number>;
  subscriptionStatus: string;
};

export type BackendPlan = {
  code: string;
  name: string;
  monthly_price_cents: number;
  limits: Record<string, number>;
};

export type BackendSubscription = {
  organization_id: number | string;
  status: string;
  plan: BackendPlan;
};

export type BackendUsageSummary = {
  organization_id: number | string;
  month: string;
  usage: Record<string, number>;
  limits: Record<string, number>;
  subscription_status: string;
};
