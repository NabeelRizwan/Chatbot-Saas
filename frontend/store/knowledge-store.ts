import { create } from "zustand";
import { isKnowledgeJobActive } from "@/lib/knowledge-contract";
import * as knowledgeService from "@/services/knowledge-service";
import type { CrawlMode, KnowledgeDocument, KnowledgeJob } from "@/types/knowledge";

type UploadItem = { id: string; filename: string; progress: number; status: "uploading" | "accepted" | "failed"; error?: string };
type KnowledgeState = {
  documentsByBot: Record<string, KnowledgeDocument[]>; jobsByBot: Record<string, KnowledgeJob[]>;
  loading: boolean; mutating: boolean; pollingBotIds: string[]; uploads: UploadItem[]; error: string | null;
  fetchDocuments: (botId: string) => Promise<void>; fetchJobs: (botId: string) => Promise<void>; refresh: (botId: string) => Promise<void>;
  uploadFile: (botId: string, file: File) => Promise<void>; crawlWebsite: (botId: string, url: string, crawlMode?: CrawlMode) => Promise<void>;
  deleteDocument: (botId: string, documentId: string) => Promise<void>; reindexDocument: (botId: string, documentId: string) => Promise<void>;
  cancelJob: (botId: string, jobId: string) => Promise<void>; retryJob: (botId: string, jobId: string) => Promise<void>;
  pollProcessing: (botId: string) => void; stopPolling: (botId: string) => void; clearError: () => void;
};

const pollingTimers = new Map<string, ReturnType<typeof setTimeout>>();
function getErrorMessage(error: unknown): string {
  const message = error instanceof Error ? error.message : "Knowledge operation failed.";
  if (/PLAN_QUOTA_EXCEEDED|current plan|plan limit|exceed your plan/i.test(message)) {
    return "Crawl was not activated because it would exceed your plan. Your existing knowledge remains active.";
  }
  return message;
}
function upsert<T extends { id?: string; jobId?: string }>(items: T[], item: T): T[] {
  const key = item.id ?? item.jobId;
  return items.some((current) => (current.id ?? current.jobId) === key)
    ? items.map((current) => ((current.id ?? current.jobId) === key ? item : current)) : [item, ...items];
}

export const useKnowledgeStore = create<KnowledgeState>()((set, get) => ({
  documentsByBot: {}, jobsByBot: {}, loading: false, mutating: false, pollingBotIds: [], uploads: [], error: null,
  fetchDocuments: async (botId) => {
    try {
      const documents = await knowledgeService.getDocuments(botId);
      set((state) => ({ documentsByBot: { ...state.documentsByBot, [botId]: documents } }));
    } catch (error) { set({ error: getErrorMessage(error) }); }
  },
  fetchJobs: async (botId) => {
    try {
      const jobs = await knowledgeService.getJobs(botId);
      set((state) => ({ jobsByBot: { ...state.jobsByBot, [botId]: jobs } }));
    } catch (error) { set({ error: getErrorMessage(error) }); }
  },
  refresh: async (botId) => {
    set({ loading: true, error: null });
    await get().fetchDocuments(botId);
    await get().fetchJobs(botId);
    if ((get().jobsByBot[botId] ?? []).some((job) => isKnowledgeJobActive(job.status))) get().pollProcessing(botId);
    else get().stopPolling(botId);
    set({ loading: false });
  },
  uploadFile: async (botId, file) => {
    const uploadId = `${file.name}-${Date.now()}`;
    set((state) => ({ uploads: [{ id: uploadId, filename: file.name, progress: 0, status: "uploading" }, ...state.uploads], error: null }));
    try {
      const accepted = await knowledgeService.uploadFile(botId, file, (progress) => set((state) => ({ uploads: state.uploads.map((item) => item.id === uploadId ? { ...item, progress } : item) })));
      set((state) => ({ documentsByBot: { ...state.documentsByBot, [botId]: upsert(state.documentsByBot[botId] ?? [], accepted.document) },
        uploads: state.uploads.map((item) => item.id === uploadId ? { ...item, progress: 100, status: "accepted" } : item) }));
      await get().fetchJobs(botId); get().pollProcessing(botId);
    } catch (error) {
      set((state) => ({ error: getErrorMessage(error), uploads: state.uploads.map((item) => item.id === uploadId ? { ...item, status: "failed", error: getErrorMessage(error) } : item) })); throw error;
    }
  },
  crawlWebsite: async (botId, url, crawlMode = "recursive") => {
    set({ mutating: true, error: null });
    try {
      const accepted = await knowledgeService.crawlWebsite(botId, url, crawlMode);
      set((state) => ({ documentsByBot: { ...state.documentsByBot, [botId]: upsert(state.documentsByBot[botId] ?? [], accepted.document) } }));
      await get().fetchJobs(botId); get().pollProcessing(botId);
    } catch (error) { set({ error: getErrorMessage(error) }); throw error; } finally { set({ mutating: false }); }
  },
  deleteDocument: async (botId, documentId) => {
    set({ mutating: true, error: null });
    try { await knowledgeService.deleteSource(documentId); await get().refresh(botId); }
    catch (error) { set({ error: getErrorMessage(error) }); throw error; } finally { set({ mutating: false }); }
  },
  reindexDocument: async (botId, documentId) => {
    set({ mutating: true, error: null });
    try {
      const accepted = await knowledgeService.reindexDocument(documentId);
      set((state) => ({ documentsByBot: { ...state.documentsByBot, [botId]: upsert(state.documentsByBot[botId] ?? [], accepted.document) } }));
      await get().fetchJobs(botId); get().pollProcessing(botId);
    } catch (error) { set({ error: getErrorMessage(error) }); throw error; } finally { set({ mutating: false }); }
  },
  cancelJob: async (botId, jobId) => {
    set({ mutating: true, error: null });
    try { const job = await knowledgeService.cancelJob(botId, jobId); set((state) => ({ jobsByBot: { ...state.jobsByBot, [botId]: upsert(state.jobsByBot[botId] ?? [], job) } })); get().pollProcessing(botId); }
    catch (error) { set({ error: getErrorMessage(error) }); throw error; } finally { set({ mutating: false }); }
  },
  retryJob: async (botId, jobId) => {
    set({ mutating: true, error: null });
    try { const job = await knowledgeService.retryJob(botId, jobId); set((state) => ({ jobsByBot: { ...state.jobsByBot, [botId]: upsert(state.jobsByBot[botId] ?? [], job) } })); get().pollProcessing(botId); }
    catch (error) { set({ error: getErrorMessage(error) }); throw error; } finally { set({ mutating: false }); }
  },
  pollProcessing: (botId) => {
    if (pollingTimers.has(botId)) return;
    const poll = async () => {
      pollingTimers.delete(botId);
      if (typeof document !== "undefined" && document.visibilityState === "visible") {
        await get().fetchJobs(botId);
        // Fetch after every observed job state, including the first terminal
        // state. Promotion and final chunk counts become visible in that same
        // commit, and skipping this fetch leaves a ready job beside a stale
        // "processing / 0 chunks" source card.
        await get().fetchDocuments(botId);
      }
      if ((get().jobsByBot[botId] ?? []).some((job) => isKnowledgeJobActive(job.status))) {
        pollingTimers.set(botId, setTimeout(() => void poll(), 5000));
      } else get().stopPolling(botId);
    };
    pollingTimers.set(botId, setTimeout(() => void poll(), 5000));
    set((state) => ({ pollingBotIds: Array.from(new Set([...state.pollingBotIds, botId])) }));
  },
  stopPolling: (botId) => {
    const timer = pollingTimers.get(botId); if (timer) clearTimeout(timer); pollingTimers.delete(botId);
    set((state) => ({ pollingBotIds: state.pollingBotIds.filter((id) => id !== botId) }));
  },
  clearError: () => set({ error: null }),
}));
