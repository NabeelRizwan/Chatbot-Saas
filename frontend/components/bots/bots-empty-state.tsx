import { Bot, Plus } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";

export function BotsEmptyState() {
  return (
    <div className="rounded-lg border border-dashed border-border bg-card/60 px-6 py-14 text-center">
      <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-lg bg-primary/10 text-primary">
        <Bot className="h-6 w-6" />
      </div>
      <h2 className="mt-5 text-lg font-semibold">No bots yet</h2>
      <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">
        Create your first assistant and connect it to Gemini or OpenAI. Knowledge ingestion and chat tools come later.
      </p>
      <Button asChild className="mt-6">
        <Link href="/bots/create">
          <Plus className="h-4 w-4" />
          Create bot
        </Link>
      </Button>
    </div>
  );
}
