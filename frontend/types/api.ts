export type ApiErrorPayload = {
  detail?: string | Array<{ loc?: Array<string | number>; msg?: string }>;
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
