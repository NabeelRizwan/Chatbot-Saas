import type { BackendKnowledgeDocument, BackendKnowledgeJob, KnowledgeDocument, KnowledgeJob, KnowledgeJobStatus } from "@/types/knowledge";

export const activeKnowledgeJobStatuses = new Set<KnowledgeJobStatus>([
  "queued", "crawling", "processing", "embedding", "validating", "retrying", "cancelling",
]);
export function isKnowledgeJobActive(status: KnowledgeJobStatus) { return activeKnowledgeJobStatuses.has(status); }

export function normalizeKnowledgeDocument(document: BackendKnowledgeDocument): KnowledgeDocument {
  return {
    id: String(document.id), botId: String(document.bot_id), filename: document.filename, sourceType: document.source_type,
    sourceUrl: document.source_url, fileSize: document.file_size, logicalSizeBytes: document.logical_size_bytes ?? 0,
    processingStatus: document.processing_status, processingError: document.processing_error,
    lifecycleStatus: document.lifecycle_status ?? "ready", active: document.active ?? document.processing_status === "completed",
    version: document.version ?? 1, pageCount: document.page_count ?? 1, lastIndexedAt: document.last_indexed_at,
    chunkCount: document.chunk_count ?? 0, tokenCount: document.token_count ?? 0, metadata: document.metadata ?? {},
    createdAt: document.created_at, updatedAt: document.updated_at,
  };
}

export function normalizeKnowledgeJob(job: BackendKnowledgeJob): KnowledgeJob {
  const coverage = job.crawl_coverage;
  return {
    jobId: job.job_id, botId: String(job.bot_id), sourceName: job.source_name, sourceUrl: job.source_url,
    ingestionType: job.ingestion_type, status: job.status, stage: job.stage, progressPercent: job.progress_percent,
    attemptNumber: job.attempt_number, retryable: job.retryable, cancellable: job.cancellable, createdAt: job.created_at,
    startedAt: job.started_at, completedAt: job.completed_at, errorCode: job.error_code, errorMessage: job.error_message,
    crawlCoverage: coverage ? { discovered: coverage.discovered, eligible: coverage.eligible, crawled: coverage.crawled,
      indexed: coverage.indexed, skipped: coverage.skipped, failed: coverage.failed, duplicates: coverage.duplicates,
      maximumDepth: coverage.maximum_depth, coveragePercent: coverage.coverage_percent, documents: coverage.documents,
      chunks: coverage.chunks, urlResults: coverage.url_results ?? [] } : null,
    activeVersion: job.active_version, candidateVersion: job.candidate_version, versionState: job.version_state,
    chunksCreated: job.chunks_created ?? 0,
  };
}
