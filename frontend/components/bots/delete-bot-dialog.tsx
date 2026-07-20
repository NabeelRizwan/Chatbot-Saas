"use client";

import { AlertTriangle, Loader2, Trash2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { Bot } from "@/types/bot";

type DeleteBotDialogProps = {
  bot: Bot | null;
  open: boolean;
  loading?: boolean;
  onClose: () => void;
  onConfirm: () => void;
};

export function DeleteBotDialog({ bot, open, loading = false, onClose, onConfirm }: DeleteBotDialogProps) {
  if (!open || !bot) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-background/70 p-4 backdrop-blur-sm">
      <Card className="w-full max-w-md">
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-destructive/10 text-destructive">
              <AlertTriangle className="h-5 w-5" />
            </div>
            <CardTitle>Delete bot</CardTitle>
          </div>
          <Button size="icon" variant="ghost" onClick={onClose} disabled={loading}>
            <X className="h-4 w-4" />
          </Button>
        </CardHeader>
        <CardContent className="space-y-5">
          <p className="text-sm text-muted-foreground">
            This will delete <span className="font-medium text-foreground">{bot.name}</span>. The UI updates
            optimistically, but the backend must support `DELETE /bot/{bot.id}` for this to persist.
          </p>
          <div className="flex justify-end gap-3">
            <Button type="button" variant="outline" onClick={onClose} disabled={loading}>
              Cancel
            </Button>
            <Button type="button" className="bg-destructive text-destructive-foreground hover:bg-destructive/90" onClick={onConfirm} disabled={loading}>
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
              Delete
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
