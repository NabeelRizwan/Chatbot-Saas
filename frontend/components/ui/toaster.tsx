"use client";

import { CheckCircle2, Info, X, XCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useToastStore, type ToastVariant } from "@/store/toast-store";

const icons: Record<ToastVariant, typeof CheckCircle2> = {
  success: CheckCircle2,
  error: XCircle,
  info: Info,
};

const variants: Record<ToastVariant, string> = {
  success: "border-accent/30 bg-card text-card-foreground",
  error: "border-destructive/30 bg-card text-card-foreground",
  info: "border-primary/30 bg-card text-card-foreground",
};

export function Toaster() {
  const toasts = useToastStore((state) => state.toasts);
  const dismissToast = useToastStore((state) => state.dismissToast);

  return (
    <div className="fixed right-4 top-4 z-[80] flex w-[calc(100vw-2rem)] max-w-sm flex-col gap-3">
      {toasts.map((toast) => {
        const Icon = icons[toast.variant];

        return (
          <div
            key={toast.id}
            className={cn("rounded-lg border p-4 shadow-soft backdrop-blur-xl", variants[toast.variant])}
          >
            <div className="flex gap-3">
              <Icon className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">{toast.title}</p>
                {toast.description && <p className="mt-1 text-sm text-muted-foreground">{toast.description}</p>}
              </div>
              <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => dismissToast(toast.id)}>
                <X className="h-4 w-4" />
              </Button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
