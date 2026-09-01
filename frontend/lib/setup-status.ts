export type SetupUploadSummary = {
  title: string;
  description: string;
  variant: "success" | "error";
};

export function summarizeSetupUploads(total: number, rejected: number): SetupUploadSummary {
  const accepted = total - rejected;
  if (total === 0) {
    return {
      title: "Bot created",
      description: "The assistant was created successfully.",
      variant: "success",
    };
  }
  if (rejected === 0) {
    return {
      title: "Bot created; knowledge processing",
      description: `${accepted} file upload${accepted === 1 ? " was" : "s were"} accepted. Indexing continues in the background.`,
      variant: "success",
    };
  }
  if (accepted === 0) {
    return {
      title: "Bot created; uploads failed",
      description: `All ${rejected} file upload${rejected === 1 ? " was" : "s were"} rejected. Open Knowledge Base to review and retry.`,
      variant: "error",
    };
  }
  return {
    title: "Bot created with upload errors",
    description: `${accepted} accepted and processing; ${rejected} rejected. Open Knowledge Base to review failed uploads.`,
    variant: "error",
  };
}
