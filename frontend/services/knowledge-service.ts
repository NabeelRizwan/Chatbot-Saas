import { api, request } from "@/services/api";
import { normalizeKnowledgeDocument, normalizeKnowledgeJob } from "@/lib/knowledge-contract";
import type { BackendKnowledgeJob, CrawlMode, KnowledgeAcceptedResponse, KnowledgeDocument, KnowledgeDocumentListResponse, KnowledgeJob, KnowledgeJobListResponse } from "@/types/knowledge";

export type AcceptedKnowledge = { document: KnowledgeDocument; jobId: string; message: string };
export async function getDocuments(botId: string): Promise<KnowledgeDocument[]> {
  const response = await request<KnowledgeDocumentListResponse>({ method: "GET", url: "/knowledge/documents", params: { bot_id: botId } });
  return response.documents.map(normalizeKnowledgeDocument);
}
export async function getJobs(botId: string): Promise<KnowledgeJob[]> {
  const response = await request<KnowledgeJobListResponse>({ method: "GET", url: "/knowledge/jobs", params: { bot_id: botId } });
  return response.jobs.map(normalizeKnowledgeJob);
}
export async function uploadFile(botId: string, file: File, onProgress?: (progress: number) => void): Promise<AcceptedKnowledge> {
  const formData = new FormData(); formData.append("file", file);
  const { data } = await api.post<KnowledgeAcceptedResponse>("/knowledge/upload", formData, {
    params: { bot_id: botId }, headers: { "Content-Type": "multipart/form-data" }, timeout: 120000,
    onUploadProgress: (event) => { if (event.total && onProgress) onProgress(Math.round((event.loaded / event.total) * 100)); },
  });
  return { document: normalizeKnowledgeDocument(data.document), jobId: data.job_id, message: data.message };
}
export async function crawlWebsite(botId: string, url: string, crawlMode: CrawlMode = "recursive"): Promise<AcceptedKnowledge> {
  const response = await request<KnowledgeAcceptedResponse>({ method: "POST", url: "/knowledge/crawl", data: { bot_id: Number(botId), url, crawl_mode: crawlMode } });
  return { document: normalizeKnowledgeDocument(response.document), jobId: response.job_id, message: response.message };
}
export async function deleteSource(documentId: string): Promise<void> { await request<void>({ method: "DELETE", url: `/knowledge/sources/${documentId}` }); }
export async function reindexDocument(documentId: string): Promise<AcceptedKnowledge> {
  const response = await request<KnowledgeAcceptedResponse>({ method: "POST", url: `/knowledge/documents/${documentId}/reindex` });
  return { document: normalizeKnowledgeDocument(response.document), jobId: response.job_id, message: response.message };
}
export async function cancelJob(botId: string, jobId: string): Promise<KnowledgeJob> {
  return normalizeKnowledgeJob(await request<BackendKnowledgeJob>({ method: "POST", url: `/knowledge/jobs/${jobId}/cancel`, params: { bot_id: botId } }));
}
export async function retryJob(botId: string, jobId: string): Promise<KnowledgeJob> {
  return normalizeKnowledgeJob(await request<BackendKnowledgeJob>({ method: "POST", url: `/knowledge/jobs/${jobId}/retry`, params: { bot_id: botId } }));
}
