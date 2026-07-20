export type ApiErrorPayload = {
  detail?: string;
  message?: string;
};

export type ApiResult<T> = {
  data: T;
};

export type DashboardMetric = {
  label: string;
  value: string;
  change: string;
  tone: "blue" | "green" | "amber" | "neutral";
};
