"use client";

import { motion } from "framer-motion";
import { Bot, Database, Search } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useBotStore } from "@/store/bot-store";

export function KnowledgeIndexClient() {
  const bots = useBotStore((state) => state.bots);
  const loading = useBotStore((state) => state.loading);
  const fetchBots = useBotStore((state) => state.fetchBots);
  const [query, setQuery] = useState("");

  useEffect(() => {
    void fetchBots();
  }, [fetchBots]);

  const filteredBots = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return bots.filter((bot) => !normalized || bot.name.toLowerCase().includes(normalized) || bot.id.includes(normalized));
  }, [bots, query]);

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
        <div>
          <p className="flex items-center gap-2 text-sm font-medium text-primary">
            <Database className="h-4 w-4" />
            Knowledge base
          </p>
          <h1 className="mt-2 text-3xl font-semibold tracking-normal sm:text-4xl">Knowledge</h1>
          <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
            Choose a bot to upload files, crawl pages, monitor processing, and manage retrieval sources.
          </p>
        </div>
      </div>

      <Card>
        <CardContent className="flex h-12 items-center gap-2 p-0 px-4">
          <Search className="h-4 w-4 text-muted-foreground" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="h-full w-full bg-transparent text-sm outline-none"
            placeholder="Search bots"
          />
        </CardContent>
      </Card>

      {loading ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, index) => (
            <Skeleton key={index} className="h-36 rounded-lg" />
          ))}
        </div>
      ) : filteredBots.length > 0 ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {filteredBots.map((bot, index) => (
            <motion.div
              key={bot.id}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.03 }}
            >
              <Card className="h-full transition-colors hover:border-primary/50">
                <CardContent className="flex h-full flex-col justify-between gap-5 p-5">
                  <div className="flex items-start gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
                      <Bot className="h-5 w-5" />
                    </div>
                    <div className="min-w-0">
                      <h2 className="truncate text-base font-semibold">{bot.name}</h2>
                      <p className="mt-1 text-sm text-muted-foreground">
                        {bot.provider} · {bot.model}
                      </p>
                    </div>
                  </div>
                  <Button asChild className="w-full">
                    <Link href={`/knowledge/${bot.id}`}>Manage knowledge</Link>
                  </Button>
                </CardContent>
              </Card>
            </motion.div>
          ))}
        </div>
      ) : (
        <Card>
          <CardContent className="flex min-h-64 flex-col items-center justify-center text-center">
            <Database className="h-10 w-10 text-muted-foreground" />
            <h2 className="mt-4 text-lg font-semibold">No bots found</h2>
            <p className="mt-2 max-w-md text-sm text-muted-foreground">
              Create a bot first, then attach files and website pages as retrieval knowledge.
            </p>
            <Button asChild className="mt-5">
              <Link href="/bots/create">Create bot</Link>
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
