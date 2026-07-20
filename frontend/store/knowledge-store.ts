import { create } from "zustand";

import * as knowledgeService from "@/services/knowledge-service";
import type { KnowledgeDocument } from "@/types/knowledge";

type UploadItem = {
  id: string;
  filename: string;
  progress: number;
  status: "uploading" | "accepted" | "failed";
  error?: string;
};

type KnowledgeState = {
  documentsByBot: Record<string, KnowledgeDocument[]>;
  loading: boolean;
  mutating: boolean;
  pollingBotIds: string[];
  uploads: UploadItem[];
  error: string | null;
  fetchDocuments: (botId: string) => Promise<void>;
  uploadFile: (botId: string, file: File) => Promise<void>;
  crawlWebsite: (botId: string, url: string) => Promise<void>;
  deleteDocument: (botId: string, documentId: string) => Promise<void>;
  reindexDocument: (botId: string, documentId: string) => Promise<void>;
  pollProcessing: (botId: string) => void;
  stopPolling: (botId: string) => void;
  clearError: () => void;
};

const pollingTimers = new Map<string, ReturnType<typeof setInterval>>();

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong";
}

function upsertDocument(documents: KnowledgeDocument[], document: KnowledgeDocument) {
  const exists = documents.some((item) => item.id === document.id);
  if (exists) {
    return documents.map((item) => (item.id === document.id ? document : item));
  }
  return [document, ...documents];
}

function hasProcessingDocuments(documents: KnowledgeDocument[]) {
  return documents.some((document) => ["pending", "processing"].includes(document.processingStatus));
}

export const useKnowledgeStore = create<KnowledgeState>()((set, get) => ({
  documentsByBot: {},
  loading: false,
  mutating: false,
  pollingBotIds: [],
  uploads: [],
  error: null,
  fetchDocuments: async (botId) => {
    set({ loading: true, error: null });
    try {
      const documents = await knowledgeService.getDocuments(botId);
      set((state) => ({
        documentsByBot: { ...state.documentsByBot, [botId]: documents },
        loading: false,
      }));
      if (hasProcessingDocuments(documents)) {
        get().pollProcessing(botId);
      } else {
        get().stopPolling(botId);
      }
    } catch (error) {
      set({ error: getErrorMessage(error), loading: false });
      get().stopPolling(botId);
    }
  },
  uploadFile: async (botId, file) => {
    const uploadId = `${file.name}-${Date.now()}`;
    set((state) => ({
      uploads: [{ id: uploadId, filename: file.name, progress: 0, status: "uploading" }, ...state.uploads],
      error: null,
    }));

    try {
      const document = await knowledgeService.uploadFile(botId, file, (progress) => {
        set((state) => ({
          uploads: state.uploads.map((item) => (item.id === uploadId ? { ...item, progress } : item)),
        }));
      });
      set((state) => ({
        documentsByBot: {
          ...state.documentsByBot,
          [botId]: upsertDocument(state.documentsByBot[botId] ?? [], document),
        },
        uploads: state.uploads.map((item) =>
          item.id === uploadId ? { ...item, progress: 100, status: "accepted" } : item,
        ),
      }));
      get().pollProcessing(botId);
    } catch (error) {
      set((state) => ({
        error: getErrorMessage(error),
        uploads: state.uploads.map((item) =>
          item.id === uploadId ? { ...item, status: "failed", error: getErrorMessage(error) } : item,
        ),
      }));
      throw error;
    }
  },
  crawlWebsite: async (botId, url) => {
    set({ mutating: true, error: null });
    try {
      const document = await knowledgeService.crawlWebsite(botId, url);
      set((state) => ({
        documentsByBot: {
          ...state.documentsByBot,
          [botId]: upsertDocument(state.documentsByBot[botId] ?? [], document),
        },
        mutating: false,
      }));
      get().pollProcessing(botId);
    } catch (error) {
      set({ error: getErrorMessage(error), mutating: false });
      throw error;
    }
  },
  deleteDocument: async (botId, documentId) => {
    const previous = get().documentsByBot[botId] ?? [];
    set((state) => ({
      documentsByBot: {
        ...state.documentsByBot,
        [botId]: previous.filter((document) => document.id !== documentId),
      },
      mutating: true,
      error: null,
    }));
    try {
      await knowledgeService.deleteDocument(documentId);
      set({ mutating: false });
    } catch (error) {
      set((state) => ({
        documentsByBot: { ...state.documentsByBot, [botId]: previous },
        error: getErrorMessage(error),
        mutating: false,
      }));
      throw error;
    }
  },
  reindexDocument: async (botId, documentId) => {
    set({ mutating: true, error: null });
    try {
      const document = await knowledgeService.reindexDocument(documentId);
      set((state) => ({
        documentsByBot: {
          ...state.documentsByBot,
          [botId]: upsertDocument(state.documentsByBot[botId] ?? [], document),
        },
        mutating: false,
      }));
      get().pollProcessing(botId);
    } catch (error) {
      set({ error: getErrorMessage(error), mutating: false });
      throw error;
    }
  },
  pollProcessing: (botId) => {
    if (pollingTimers.has(botId)) {
      return;
    }
    const timer = setInterval(() => {
      void get().fetchDocuments(botId);
    }, 5000);
    pollingTimers.set(botId, timer);
    set((state) => ({ pollingBotIds: Array.from(new Set([...state.pollingBotIds, botId])) }));
  },
  stopPolling: (botId) => {
    const timer = pollingTimers.get(botId);
    if (timer) {
      clearInterval(timer);
      pollingTimers.delete(botId);
    }
    set((state) => ({ pollingBotIds: state.pollingBotIds.filter((id) => id !== botId) }));
  },
  clearError: () => set({ error: null }),
}));
