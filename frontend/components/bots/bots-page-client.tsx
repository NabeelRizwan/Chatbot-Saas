"use client";

import { Filter, Plus, Search } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { BotCard } from "@/components/bots/bot-card";
import { BotsEmptyState } from "@/components/bots/bots-empty-state";
import { BotsLoading } from "@/components/bots/bots-loading";
import { DeleteBotDialog } from "@/components/bots/delete-bot-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useBotStore } from "@/store/bot-store";
import { useToastStore } from "@/store/toast-store";
import { providerLabels, providers, type Bot, type BotProvider } from "@/types/bot";

type ProviderFilter = "all" | BotProvider;

export function BotsPageClient() {
  const bots = useBotStore((state) => state.bots);
  const loading = useBotStore((state) => state.loading);
  const mutating = useBotStore((state) => state.mutating);
  const error = useBotStore((state) => state.error);
  const fetchBots = useBotStore((state) => state.fetchBots);
  const deleteBot = useBotStore((state) => state.deleteBot);
  const showToast = useToastStore((state) => state.showToast);

  const [query, setQuery] = useState("");
  const [provider, setProvider] = useState<ProviderFilter>("all");
  const [botToDelete, setBotToDelete] = useState<Bot | null>(null);

  useEffect(() => {
    void fetchBots();
  }, [fetchBots]);

  const filteredBots = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();

    return bots.filter((bot) => {
      const matchesQuery =
        !normalizedQuery ||
        bot.name.toLowerCase().includes(normalizedQuery) ||
        bot.id.toLowerCase().includes(normalizedQuery) ||
        bot.model.toLowerCase().includes(normalizedQuery);
      const matchesProvider = provider === "all" || bot.provider === provider;
      return matchesQuery && matchesProvider;
    });
  }, [bots, provider, query]);

  async function confirmDelete() {
    if (!botToDelete) {
      return;
    }

    const bot = botToDelete;
    setBotToDelete(null);

    try {
      await deleteBot(bot.id);
      showToast({
        title: "Bot deleted",
        description: `${bot.name} was removed from the list.`,
        variant: "success",
      });
    } catch (deleteError) {
      showToast({
        title: "Delete failed",
        description:
          deleteError instanceof Error
            ? `${deleteError.message}. Backend requirement: DELETE /bot/${bot.id}.`
            : `Backend requirement: DELETE /bot/${bot.id}.`,
        variant: "error",
      });
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
        <div>
          <p className="text-sm font-medium text-primary">Bot management</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-normal sm:text-4xl">Bots</h1>
          <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
            Manage assistants, provider configuration, model choices, and prompt behavior.
          </p>
        </div>
        <Button asChild>
          <Link href="/bots/create">
            <Plus className="h-4 w-4" />
            Create bot
          </Link>
        </Button>
      </div>

      <Card>
        <CardContent className="flex flex-col gap-3 p-4 lg:flex-row lg:items-center">
          <div className="flex h-11 flex-1 items-center gap-2 rounded-lg border border-input bg-background px-3">
            <Search className="h-4 w-4 text-muted-foreground" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="w-full bg-transparent text-sm outline-none"
              placeholder="Search by name, bot ID, or model"
            />
          </div>
          <div className="flex h-11 items-center gap-2 rounded-lg border border-input bg-background px-3">
            <Filter className="h-4 w-4 text-muted-foreground" />
            <select
              value={provider}
              onChange={(event) => setProvider(event.target.value as ProviderFilter)}
              className="bg-transparent text-sm outline-none"
            >
              <option value="all">All providers</option>
              {providers.map((item) => (
                <option key={item} value={item}>
                  {providerLabels[item]}
                </option>
              ))}
            </select>
          </div>
        </CardContent>
      </Card>

      {error && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          {error}. Backend requirement for this page: `GET /bots`.
        </div>
      )}

      {loading ? (
        <BotsLoading />
      ) : filteredBots.length > 0 ? (
        <div className="space-y-4">
          {filteredBots.map((bot, index) => (
            <BotCard key={bot.id} bot={bot} index={index} onDelete={setBotToDelete} />
          ))}
        </div>
      ) : (
        !error && <BotsEmptyState />
      )}

      <DeleteBotDialog
        bot={botToDelete}
        open={Boolean(botToDelete)}
        loading={mutating}
        onClose={() => setBotToDelete(null)}
        onConfirm={confirmDelete}
      />
    </div>
  );
}
