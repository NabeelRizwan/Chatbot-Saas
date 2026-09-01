"use client";

import { Check, Clipboard, Code2 } from "lucide-react";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { buildWidgetScriptSnippet, resolveWidgetBaseUrl } from "@/lib/deployment-contract";
import { API_BASE_URL } from "@/services/api";

const apiBaseUrl = API_BASE_URL.replace(/\/$/, "");

export function EmbedSnippetCard({ botId }: { botId: string }) {
  const [copied, setCopied] = useState(false);
  const snippet = useMemo(() => {
    const runtimeOrigin = typeof window !== "undefined" ? window.location.origin : "";
    const widgetHost = resolveWidgetBaseUrl(process.env.NEXT_PUBLIC_APP_URL, runtimeOrigin);
    return buildWidgetScriptSnippet(widgetHost, apiBaseUrl, botId);
  }, [botId]);

  async function copySnippet() {
    await navigator.clipboard.writeText(snippet);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Code2 className="h-5 w-5 text-primary" />
          Embed Widget
        </CardTitle>
        <CardDescription>Paste this snippet before the closing body tag on any website.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <pre className="max-h-44 overflow-auto rounded-lg border border-border bg-muted/40 p-3 text-xs leading-5 text-foreground">
          <code>{snippet}</code>
        </pre>
        <Button type="button" className="w-full" variant="outline" onClick={() => void copySnippet()}>
          {copied ? <Check className="h-4 w-4" /> : <Clipboard className="h-4 w-4" />}
          {copied ? "Copied" : "Copy snippet"}
        </Button>
      </CardContent>
    </Card>
  );
}
