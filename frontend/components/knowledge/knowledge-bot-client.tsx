"use client";

import { AnimatePresence, motion } from "framer-motion";
import {
  AlertCircle,
  CheckCircle2,
  Clock,
  ExternalLink,
  FileText,
  Globe,
  Loader2,
  MessageSquare,
  RefreshCw,
  Send,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { sendChatMessage, streamChatMessage } from "@/services/chat-service";
import { useAuthStore } from "@/store/auth-store";
import { useBotStore } from "@/store/bot-store";
import { useKnowledgeStore } from "@/store/knowledge-store";
import { useToastStore } from "@/store/toast-store";
import type { ChatSource, RetrievedChunk } from "@/types/chat";
import type { KnowledgeDocument, ProcessingStatus } from "@/types/knowledge";

const acceptedExtensions = [".pdf", ".txt", ".docx", ".csv", ".xlsx", ".md"];
const maxUploadBytes = 20 * 1024 * 1024;
const emptyDocuments: KnowledgeDocument[] = [];

const statusStyles: Record<ProcessingStatus, string> = {
  pending: "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  processing: "border-blue-500/30 bg-blue-500/10 text-blue-700 dark:text-blue-300",
  completed: "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  failed: "border-destructive/30 bg-destructive/10 text-destructive",
};

function formatBytes(size?: number | null) {
  if (!size) {
    return "Remote source";
  }
  if (size < 1024 * 1024) {
    return `${Math.max(1, Math.round(size / 1024))} KB`;
  }
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function formatDate(value?: string) {
  if (!value) {
    return "Date unavailable";
  }
  return new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function getFriendlyError(error: unknown) {
  const message = error instanceof Error ? error.message : "Something went wrong";
  if (/rate|429/i.test(message)) {
    return "The provider is rate limiting requests. Wait a moment and try again.";
  }
  if (/api key|provider key|credential|unauthorized|forbidden|401|403/i.test(message)) {
    return "Check the customer key and the bot provider key, then try again.";
  }
  return message;
}

function validateFile(file: File) {
  const extension = `.${file.name.split(".").pop()?.toLowerCase() ?? ""}`;
  if (!acceptedExtensions.includes(extension)) {
    return "Supported files are PDF, TXT, DOCX, CSV, XLSX, and MD.";
  }
  if (file.size > maxUploadBytes) {
    return "File must be 20 MB or smaller.";
  }
  return null;
}

function StatusBadge({ status }: { status: ProcessingStatus }) {
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-medium", statusStyles[status])}>
      {status === "completed" && <CheckCircle2 className="h-3.5 w-3.5" />}
      {status === "failed" && <AlertCircle className="h-3.5 w-3.5" />}
      {["pending", "processing"].includes(status) && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
      {status}
    </span>
  );
}

function UploadModal({ botId, onClose }: { botId: string; onClose: () => void }) {
  const uploadFile = useKnowledgeStore((state) => state.uploadFile);
  const fetchDocuments = useKnowledgeStore((state) => state.fetchDocuments);
  const uploads = useKnowledgeStore((state) => state.uploads);
  const showToast = useToastStore((state) => state.showToast);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleFiles(files: FileList | File[]) {
    const file = files[0];
    if (!file) {
      return;
    }
    const validationError = validateFile(file);
    if (validationError) {
      setError(validationError);
      return;
    }
    setError(null);
    try {
      await uploadFile(botId, file);
      await fetchDocuments(botId);
      showToast({ title: "Upload accepted", description: `${file.name} is processing.`, variant: "success" });
      onClose();
    } catch (uploadError) {
      setError(getFriendlyError(uploadError));
    }
  }

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-background/70 p-4 backdrop-blur-sm">
      <motion.div
        initial={{ opacity: 0, y: 16, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 16, scale: 0.98 }}
        className="w-full max-w-lg rounded-lg border border-border bg-card shadow-soft"
      >
        <div className="flex items-center justify-between border-b border-border p-5">
          <div>
            <h2 className="text-lg font-semibold">Upload source</h2>
            <p className="mt-1 text-sm text-muted-foreground">PDF, TXT, DOCX, CSV, XLSX, or MD up to 20 MB.</p>
          </div>
          <Button size="icon" variant="ghost" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>
        <div className="space-y-4 p-5">
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragging(false);
              void handleFiles(event.dataTransfer.files);
            }}
            className={cn(
              "flex min-h-52 w-full flex-col items-center justify-center rounded-lg border border-dashed border-border bg-background p-6 text-center transition-colors",
              dragging && "border-primary bg-primary/5",
            )}
          >
            <Upload className="h-9 w-9 text-primary" />
            <span className="mt-4 text-sm font-medium">Drop a file or click to browse</span>
            <span className="mt-1 text-xs text-muted-foreground">Files are saved first, then processed in the background.</span>
          </button>
          <input
            ref={inputRef}
            type="file"
            className="hidden"
            accept=".pdf,.txt,.docx,.csv,.xlsx,.md,application/pdf,text/plain,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/markdown"
            onChange={(event) => {
              if (event.target.files) {
                void handleFiles(event.target.files);
              }
            }}
          />
          {error && <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</div>}
          {uploads.slice(0, 3).map((upload) => (
            <div key={upload.id} className="rounded-lg border border-border p-3">
              <div className="flex items-center justify-between text-sm">
                <span className="truncate font-medium">{upload.filename}</span>
                <span className="text-muted-foreground">{upload.progress}%</span>
              </div>
              <div className="mt-2 h-2 overflow-hidden rounded-full bg-muted">
                <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${upload.progress}%` }} />
              </div>
            </div>
          ))}
        </div>
      </motion.div>
    </div>
  );
}

function CrawlModal({ botId, onClose }: { botId: string; onClose: () => void }) {
  const crawlWebsite = useKnowledgeStore((state) => state.crawlWebsite);
  const fetchDocuments = useKnowledgeStore((state) => state.fetchDocuments);
  const mutating = useKnowledgeStore((state) => state.mutating);
  const showToast = useToastStore((state) => state.showToast);
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    try {
      new URL(url);
    } catch {
      setError("Enter a valid http or https URL.");
      return;
    }
    try {
      setError(null);
      await crawlWebsite(botId, url);
      await fetchDocuments(botId);
      showToast({ title: "Crawl accepted", description: "The page is processing.", variant: "success" });
      onClose();
    } catch (crawlError) {
      setError(getFriendlyError(crawlError));
    }
  }

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-background/70 p-4 backdrop-blur-sm">
      <motion.div
        initial={{ opacity: 0, y: 16, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 16, scale: 0.98 }}
        className="w-full max-w-lg rounded-lg border border-border bg-card shadow-soft"
      >
        <div className="flex items-center justify-between border-b border-border p-5">
          <div>
            <h2 className="text-lg font-semibold">Crawl page</h2>
            <p className="mt-1 text-sm text-muted-foreground">Single-page website ingestion.</p>
          </div>
          <Button size="icon" variant="ghost" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>
        <div className="space-y-4 p-5">
          <div className="flex h-11 items-center gap-2 rounded-lg border border-input bg-background px-3">
            <Globe className="h-4 w-4 text-muted-foreground" />
            <input
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              className="h-full w-full bg-transparent text-sm outline-none"
              placeholder="https://example.com/docs"
            />
          </div>
          {error && <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</div>}
          <Button className="w-full" disabled={mutating || !url.trim()} onClick={submit}>
            {mutating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Globe className="h-4 w-4" />}
            Start crawl
          </Button>
        </div>
      </motion.div>
    </div>
  );
}

function DocumentRow({ botId, document }: { botId: string; document: KnowledgeDocument }) {
  const deleteDocument = useKnowledgeStore((state) => state.deleteDocument);
  const reindexDocument = useKnowledgeStore((state) => state.reindexDocument);
  const showToast = useToastStore((state) => state.showToast);

  async function onDelete() {
    try {
      await deleteDocument(botId, document.id);
      showToast({ title: "Source deleted", description: document.filename, variant: "success" });
    } catch (error) {
      showToast({ title: "Delete failed", description: error instanceof Error ? error.message : "Try again.", variant: "error" });
    }
  }

  async function onReindex() {
    try {
      await reindexDocument(botId, document.id);
      showToast({ title: "Reindex queued", description: document.filename, variant: "success" });
    } catch (error) {
      showToast({ title: "Reindex failed", description: error instanceof Error ? error.message : "Try again.", variant: "error" });
    }
  }

  return (
    <motion.div layout className="space-y-3 rounded-lg border border-border bg-card p-4">
      <div className="flex min-w-0 items-start gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
          {document.sourceType === "website" ? <Globe className="h-5 w-5" /> : <FileText className="h-5 w-5" />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <h3 className="truncate text-sm font-semibold">{document.filename}</h3>
            <StatusBadge status={document.processingStatus} />
          </div>
          <p className="mt-1 truncate text-xs text-muted-foreground">
            {document.sourceUrl ?? `${document.sourceType.toUpperCase()} · ${formatBytes(document.fileSize)}`}
          </p>
          <p className="mt-1 flex items-center gap-1 text-xs text-muted-foreground">
            <Clock className="h-3 w-3" />
            {formatDate(document.createdAt)}
          </p>
          {document.processingError && <p className="mt-2 text-xs text-destructive">{document.processingError}</p>}
        </div>
      </div>
      <div className="flex items-center justify-between gap-3 border-t border-border pt-3">
        <div className="text-xs text-muted-foreground">
          <span className="font-medium text-foreground">{document.chunkCount}</span> chunks
          <span className="mx-2">/</span>
          <span className="font-medium text-foreground">{document.tokenCount.toLocaleString()}</span> tokens
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" onClick={onReindex}>
            <RefreshCw className="h-4 w-4" />
            Reindex
          </Button>
          <Button size="icon" variant="ghost" onClick={onDelete}>
            <Trash2 className="h-4 w-4 text-destructive" />
          </Button>
        </div>
      </div>
    </motion.div>
  );
}

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: ChatSource[];
  retrievedChunks?: RetrievedChunk[];
};

function SourceList({
  sources = [],
  retrievedChunks = [],
}: {
  sources?: ChatSource[];
  retrievedChunks?: RetrievedChunk[];
}) {
  if (sources.length === 0 && retrievedChunks.length === 0) {
    return (
      <div className="mt-3 rounded-lg border border-dashed border-border bg-background p-3 text-xs text-muted-foreground">
        No source details for this response.
      </div>
    );
  }

  return (
    <div className="mt-3 space-y-2">
      {retrievedChunks.map((chunk) => (
        <details key={chunk.chunkId} className="rounded-lg border border-border bg-background p-3">
          <summary className="cursor-pointer list-none text-xs">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate font-medium text-foreground">{chunk.sourceFilename}</p>
                <p className="mt-1 text-muted-foreground">Chunk #{chunk.chunkIndex}</p>
              </div>
              {typeof chunk.score === "number" && (
                <span className="rounded-full bg-muted px-2 py-1 text-[11px] text-muted-foreground">
                  {chunk.score.toFixed(3)}
                </span>
              )}
            </div>
          </summary>
          <p className="mt-3 line-clamp-none text-xs leading-5 text-muted-foreground">{chunk.content}</p>
          {chunk.sourceUrl && (
            <a
              href={chunk.sourceUrl}
              target="_blank"
              rel="noreferrer"
              className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-primary"
            >
              Open source
              <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </details>
      ))}
      {retrievedChunks.length === 0 &&
        sources.map((source, index) => (
          <div key={`${source.filename}-${index}`} className="rounded-lg border border-border bg-background p-3 text-xs">
            <p className="font-medium text-foreground">{source.filename}</p>
            {source.chunkRefs.length > 0 && (
              <p className="mt-1 text-muted-foreground">Chunks {source.chunkRefs.map((ref) => `#${ref}`).join(", ")}</p>
            )}
          </div>
        ))}
    </div>
  );
}

function ChatPlayground({
  botId,
  botName,
  welcomeMessage,
  hasCompletedSources,
}: {
  botId: string;
  botName: string;
  welcomeMessage?: string;
  hasCompletedSources: boolean;
}) {
  const showToast = useToastStore((state) => state.showToast);
  const accessToken = useAuthStore((state) => state.accessToken);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const frameRef = useRef<number | null>(null);
  const streamedRef = useRef("");
  const [apiKey] = useState(() => {
    if (typeof window === "undefined") {
      return "";
    }
    return window.localStorage.getItem("chatbot-saas-customer-api-key") || "transitioned_dummy_key";
  });
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const container = scrollRef.current;
    if (!container) {
      return;
    }
    const distanceFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
    if (distanceFromBottom < 120) {
      container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
    }
  }, [messages, generating]);

  useEffect(
    () => () => {
      abortRef.current?.abort();
      if (frameRef.current !== null) {
        cancelAnimationFrame(frameRef.current);
      }
    },
    [],
  );

  useEffect(() => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem("chatbot-saas-customer-api-key", apiKey);
    }
  }, [apiKey]);

  async function sendMessage() {
    const message = draft.trim();
    if (!message || generating) {
      return;
    }

    const userMessage: ChatMessage = { id: crypto.randomUUID(), role: "user", content: message };
    const history = messages.slice(-8).map((item) => ({ role: item.role, content: item.content }));
    const assistantId = crypto.randomUUID();
    setMessages((current) => [...current, userMessage, { id: assistantId, role: "assistant", content: "" }]);
    requestAnimationFrame(() => {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
    });
    setDraft("");
    setGenerating(true);
    setError(null);
    streamedRef.current = "";
    abortRef.current?.abort();
    abortRef.current = new AbortController();

    function flushStream() {
      if (frameRef.current !== null) {
        cancelAnimationFrame(frameRef.current);
      }
      frameRef.current = null;
      const nextContent = streamedRef.current;
      setMessages((current) =>
        current.map((item) => (item.id === assistantId ? { ...item, content: nextContent } : item)),
      );
    }

    function queueFlush() {
      if (frameRef.current === null) {
        frameRef.current = requestAnimationFrame(flushStream);
      }
    }

    try {
      await streamChatMessage({
        botId,
        message,
        history,
        onToken: (token) => {
          streamedRef.current += token;
          queueFlush();
        },
        signal: abortRef.current.signal,
        accessToken: accessToken ?? undefined,
      });
      flushStream();
      if (!streamedRef.current.trim()) {
        throw new Error("Empty streamed reply.");
      }
    } catch (streamError) {
      if (streamError instanceof DOMException && streamError.name === "AbortError") {
        return;
      }
      try {
        const response = await sendChatMessage({
          botId,
          message,
          history,
          accessToken: accessToken ?? undefined,
        });
        setMessages((current) =>
          current.map((item) =>
            item.id === assistantId
              ? {
                  ...item,
                  content: response.reply,
                  sources: response.sources,
                  retrievedChunks: response.retrievedChunks,
                }
              : item,
          ),
        );
      } catch (fallbackError) {
        const friendly = getFriendlyError(fallbackError);
        setMessages((current) => current.filter((item) => item.id !== assistantId));
        setError(friendly);
        showToast({ title: "Chat request failed", description: friendly, variant: "error" });
      }
    } finally {
      abortRef.current = null;
      setGenerating(false);
    }
  }

  return (
    <Card className="flex min-h-[720px] flex-col overflow-hidden">
      <CardHeader className="border-b border-border">
        <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
          <div>
            <CardTitle className="flex items-center gap-2">
              <MessageSquare className="h-5 w-5 text-primary" />
              Chat playground
            </CardTitle>
            <CardDescription>Test grounded responses from {botName} against the current knowledge base.</CardDescription>
          </div>
        </div>
      </CardHeader>

      <CardContent className="flex min-h-0 flex-1 flex-col p-0">
        {!hasCompletedSources && (
          <div className="border-b border-amber-500/20 bg-amber-500/10 px-5 py-3 text-sm text-amber-700 dark:text-amber-300">
            Add at least one completed source for grounded answers.
          </div>
        )}
        {error && <div className="border-b border-destructive/20 bg-destructive/5 px-5 py-3 text-sm text-destructive">{error}</div>}

        <div ref={scrollRef} className="min-h-0 flex-1 space-y-4 overflow-y-auto p-5">
          {messages.length === 0 ? (
            <div className="flex min-h-[420px] flex-col items-center justify-center text-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <MessageSquare className="h-6 w-6" />
              </div>
              <h2 className="mt-4 text-lg font-semibold">{welcomeMessage || "Ask a question about your knowledge base"}</h2>
              <p className="mt-2 max-w-md text-sm text-muted-foreground">
                Test natural assistant replies, follow-up questions, and grounded answers from your knowledge base.
              </p>
            </div>
          ) : (
            messages.map((message) => (
              <div key={message.id} className={cn("flex", message.role === "user" ? "justify-end" : "justify-start")}>
                <div
                  className={cn(
                    "max-w-[86%] rounded-lg px-4 py-3 text-sm leading-6",
                    message.role === "user" ? "bg-primary text-primary-foreground" : "border border-border bg-muted/50 text-foreground",
                  )}
                >
                  {message.content ? (
                    <p className="whitespace-pre-wrap">{message.content}</p>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 text-muted-foreground">
                      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-current [animation-delay:-0.2s]" />
                      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-current [animation-delay:-0.1s]" />
                      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-current" />
                    </span>
                  )}
                  {message.role === "assistant" &&
                    Boolean(message.sources?.length || message.retrievedChunks?.length) && (
                    <SourceList sources={message.sources} retrievedChunks={message.retrievedChunks} />
                  )}
                </div>
              </div>
            ))
          )}
        </div>

        <div className="border-t border-border p-4">
          <div className="flex items-end gap-2 rounded-lg border border-input bg-background p-2">
            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void sendMessage();
                }
              }}
              className="max-h-40 min-h-11 flex-1 resize-none bg-transparent px-2 py-2 text-sm outline-none"
              placeholder="Ask about uploaded docs or crawled pages..."
              rows={1}
              disabled={generating}
            />
            <Button size="icon" disabled={generating || !draft.trim()} onClick={() => void sendMessage()}>
              {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export function KnowledgeBotClient({ botId }: { botId: string }) {
  const bot = useBotStore((state) => state.selectedBot);
  const fetchBot = useBotStore((state) => state.fetchBot);
  const documents = useKnowledgeStore((state) => state.documentsByBot[botId] ?? emptyDocuments);
  const loading = useKnowledgeStore((state) => state.loading);
  const error = useKnowledgeStore((state) => state.error);
  const pollingBotIds = useKnowledgeStore((state) => state.pollingBotIds);
  const fetchDocuments = useKnowledgeStore((state) => state.fetchDocuments);
  const stopPolling = useKnowledgeStore((state) => state.stopPolling);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [crawlOpen, setCrawlOpen] = useState(false);

  useEffect(() => {
    if (!bot || bot.id !== botId) {
      void fetchBot(botId);
    }
  }, [botId, bot, fetchBot]);

  useEffect(() => {
    void fetchDocuments(botId);
    return () => stopPolling(botId);
  }, [botId, fetchDocuments, stopPolling]);

  const stats = useMemo(
    () => ({
      documents: documents.length,
      chunks: documents.reduce((sum, document) => sum + document.chunkCount, 0),
      processing: documents.filter((document) => ["pending", "processing"].includes(document.processingStatus)).length,
    }),
    [documents],
  );
  const hasCompletedSources = useMemo(
    () => documents.some((document) => document.processingStatus === "completed"),
    [documents],
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
        <div>
          <p className="text-sm font-medium text-primary">Knowledge base</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-normal sm:text-4xl">{bot?.name ?? `Bot ${botId}`}</h1>
          <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
            Manage files and crawled pages used for grounded retrieval in chat responses.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => void fetchDocuments(botId)}>
            <RefreshCw className={cn("h-4 w-4", pollingBotIds.includes(botId) && "animate-spin")} />
            Refresh
          </Button>
          <Button variant="outline" onClick={() => setCrawlOpen(true)}>
            <Globe className="h-4 w-4" />
            Crawl URL
          </Button>
          <Button onClick={() => setUploadOpen(true)}>
            <Upload className="h-4 w-4" />
            Upload
          </Button>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        {[
          ["Sources", stats.documents],
          ["Chunks", stats.chunks],
          ["Processing", stats.processing],
        ].map(([label, value]) => (
          <Card key={label}>
            <CardContent className="p-5">
              <p className="text-sm text-muted-foreground">{label}</p>
              <p className="mt-2 text-3xl font-semibold">{value}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {error && <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">{error}</div>}

      <div className="grid gap-6 xl:grid-cols-[420px_1fr]">
        <Card className="xl:sticky xl:top-24 xl:max-h-[calc(100vh-7rem)] xl:overflow-hidden">
          <CardHeader className="border-b border-border">
            <div className="flex items-center justify-between gap-3">
              <div>
                <CardTitle>Knowledge sources</CardTitle>
                <CardDescription>Files and URLs available for retrieval.</CardDescription>
              </div>
              {pollingBotIds.includes(botId) && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
            </div>
          </CardHeader>
          <CardContent className="max-h-[620px] space-y-3 overflow-y-auto p-4">
            {loading && documents.length === 0 ? (
              Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-28 rounded-lg" />)
            ) : documents.length > 0 ? (
              <AnimatePresence>
                {documents.map((document) => (
                  <DocumentRow key={document.id} botId={botId} document={document} />
                ))}
              </AnimatePresence>
            ) : (
              <div className="flex min-h-72 flex-col items-center justify-center rounded-lg border border-dashed border-border bg-background p-5 text-center">
                <DatabaseIcon />
                <h2 className="mt-4 text-lg font-semibold">No knowledge sources yet</h2>
                <p className="mt-2 max-w-md text-sm text-muted-foreground">
                  Upload a document or crawl a page to start grounding chatbot answers.
                </p>
                <div className="mt-5 flex gap-2">
                  <Button variant="outline" onClick={() => setCrawlOpen(true)}>
                    <Globe className="h-4 w-4" />
                    Crawl URL
                  </Button>
                  <Button onClick={() => setUploadOpen(true)}>
                    <Upload className="h-4 w-4" />
                    Upload
                  </Button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        <ChatPlayground
          botId={botId}
          botName={bot?.name ?? `Bot ${botId}`}
          welcomeMessage={bot?.welcomeMessage}
          hasCompletedSources={hasCompletedSources}
        />
      </div>

      <AnimatePresence>
        {uploadOpen && <UploadModal botId={botId} onClose={() => setUploadOpen(false)} />}
        {crawlOpen && <CrawlModal botId={botId} onClose={() => setCrawlOpen(false)} />}
      </AnimatePresence>
    </div>
  );
}

function DatabaseIcon() {
  return (
    <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-primary/10 text-primary">
      <FileText className="h-6 w-6" />
    </div>
  );
}
