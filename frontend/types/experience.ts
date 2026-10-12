export type ExperienceSettings = {
  enabled: boolean;
  suggested_questions: string[];
  hosted_chat_enabled: boolean;
  lead_form_enabled: boolean;
  approved_faq_enabled: boolean;
  product_cards_enabled: boolean;
  font_family: "system" | "inter" | "serif";
  density: "comfortable" | "compact";
  theme: "light" | "dark" | "auto";
  corner_style: "rounded" | "soft" | "square";
  lead_consent_text: string;
};

export type ApprovedFaqInput = {
  question: string;
  answer: string;
  aliases: string[];
  source_document_id: number | null;
  source_url: string | null;
  approved: boolean;
  enabled: boolean;
};
export type ApprovedFaq = ApprovedFaqInput & {
  id: number;
  source_status: "current" | "changed" | "missing" | "unbound";
  created_at: string;
  updated_at: string;
};

export type ExperienceProductInput = {
  title: string;
  description: string;
  url: string;
  image_url: string | null;
  price_amount: string | null;
  currency: string;
  source_document_id: number | null;
  enabled: boolean;
};
export type ExperienceProduct = ExperienceProductInput & { id: number; source_status: "current" | "changed" | "missing" | "unbound"; created_at: string; updated_at: string };

export type LeadStatus = "new" | "contacted" | "closed";
export type ExperienceLead = {
  id: number;
  name: string;
  email: string;
  phone: string | null;
  message: string | null;
  status: LeadStatus;
  consent_at: string;
  created_at: string;
};
export type LeadDetail = ExperienceLead & { submissions: Array<{ id: number; name: string; phone: string | null; message: string; consent_text: string; consent_at: string }> };

export type SavedQuestionInput = {
  question: string;
  expected_answer: string;
  required_phrases: string[];
  forbidden_phrases: string[];
  enabled: boolean;
};
export type SavedQuestion = SavedQuestionInput & { id: number; created_at: string; updated_at: string };
export type SavedQuestionResult = {
  id: number;
  case_id: number;
  question: string;
  expected_answer: string;
  answer: string | null;
  latency_ms: number | null;
  status: "pending" | "running" | "passed_checks" | "needs_review" | "manual_review" | "error";
  missing_phrases: string[];
  forbidden_matches: string[];
  error: string | null;
  sources: Array<{ title?: string; source_url?: string; document_id?: number | null }>;
};
export type SavedQuestionRun = {
  id: number;
  status: "pending" | "running" | "completed";
  results: SavedQuestionResult[];
  created_at: string;
  completed_at: string | null;
  provider: string;
  model: string;
};

export type ExperienceIntegrations = {
  booking: { provider: "none" | "calcom" | "calendly" | "custom"; enabled: boolean; url: string; label: string };
  orders: { provider: "none" | "shopify" | "custom"; enabled: boolean; url: string; label: string };
};
