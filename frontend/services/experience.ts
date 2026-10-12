import { request } from "@/services/api";
import type {
  ApprovedFaq, ApprovedFaqInput, ExperienceLead, ExperienceProduct, ExperienceProductInput,
  ExperienceSettings, ExperienceIntegrations, LeadStatus, LeadDetail, SavedQuestion, SavedQuestionInput, SavedQuestionRun,
} from "@/types/experience";

const base = (botId: string) => `/bot/${encodeURIComponent(botId)}/experience`;

export const experienceService = {
  settings: (botId: string) => request<ExperienceSettings>({ url: `${base(botId)}/` }),
  saveSettings: (botId: string, data: ExperienceSettings) => request<ExperienceSettings>({ method: "PUT", url: `${base(botId)}/settings`, data }),
  faqs: (botId: string) => request<{ items: ApprovedFaq[] }>({ url: `${base(botId)}/faqs` }),
  saveFaq: (botId: string, data: ApprovedFaqInput, id?: number) => request<ApprovedFaq>({ method: id ? "PUT" : "POST", url: `${base(botId)}/faqs${id ? `/${id}` : ""}`, data }),
  deleteFaq: (botId: string, id: number) => request<void>({ method: "DELETE", url: `${base(botId)}/faqs/${id}` }),
  products: (botId: string) => request<{ items: ExperienceProduct[] }>({ url: `${base(botId)}/products` }),
  saveProduct: (botId: string, data: ExperienceProductInput, id?: number) => request<ExperienceProduct>({ method: id ? "PUT" : "POST", url: `${base(botId)}/products${id ? `/${id}` : ""}`, data }),
  deleteProduct: (botId: string, id: number) => request<void>({ method: "DELETE", url: `${base(botId)}/products/${id}` }),
  leads: (botId: string, offset = 0) => request<{ items: ExperienceLead[]; total: number }>({ url: `${base(botId)}/leads`, params: { limit: 25, offset } }),
  lead: (botId: string, id: number) => request<LeadDetail>({ url: `${base(botId)}/leads/${id}` }),
  updateLead: (botId: string, id: number, status: LeadStatus) => request<ExperienceLead>({ method: "PATCH", url: `${base(botId)}/leads/${id}`, data: { status } }),
  deleteLead: (botId: string, id: number) => request<void>({ method: "DELETE", url: `${base(botId)}/leads/${id}` }),
  questions: (botId: string) => request<{ items: SavedQuestion[] }>({ url: `${base(botId)}/test-cases` }),
  saveQuestion: (botId: string, data: SavedQuestionInput, id?: number) => request<SavedQuestion>({ method: id ? "PUT" : "POST", url: `${base(botId)}/test-cases${id ? `/${id}` : ""}`, data }),
  deleteQuestion: (botId: string, id: number) => request<void>({ method: "DELETE", url: `${base(botId)}/test-cases/${id}` }),
  runs: (botId: string) => request<{ items: SavedQuestionRun[] }>({ url: `${base(botId)}/test-runs` }),
  createRun: (botId: string, caseIds: number[]) => request<SavedQuestionRun>({ method: "POST", url: `${base(botId)}/test-runs`, data: { case_ids: caseIds } }),
  run: (botId: string, id: number) => request<SavedQuestionRun>({ url: `${base(botId)}/test-runs/${id}` }),
  executeNext: (botId: string, id: number) => request<SavedQuestionRun>({ method: "POST", url: `${base(botId)}/test-runs/${id}/execute-next`, timeout: 240000 }),
  cancelRun: (botId: string, id: number) => request<SavedQuestionRun>({ method: "POST", url: `${base(botId)}/test-runs/${id}/cancel` }),
  integrations: (botId: string) => request<ExperienceIntegrations>({ url: `${base(botId)}/integrations` }),
  saveIntegrations: (botId: string, data: ExperienceIntegrations) => request<ExperienceIntegrations>({ method: "PUT", url: `${base(botId)}/integrations`, data }),
};
