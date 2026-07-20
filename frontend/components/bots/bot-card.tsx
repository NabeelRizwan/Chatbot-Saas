"use client";

import { motion } from "framer-motion";
import { Calendar, KeyRound, Pencil, Trash2 } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { providerLabels, type Bot } from "@/types/bot";

type BotCardProps = {
  bot: Bot;
  index: number;
  onDelete: (bot: Bot) => void;
};

const statusStyles = {
  active: "bg-accent/15 text-accent",
  draft: "bg-amber-500/15 text-amber-600 dark:text-amber-300",
  disabled: "bg-muted text-muted-foreground",
};

export function BotCard({ bot, index, onDelete }: BotCardProps) {
  return (
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.04 }}>
      <Card className="transition hover:-translate-y-0.5 hover:border-primary/30">
        <CardContent className="p-5">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
            <div className="min-w-0 space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="truncate text-lg font-semibold">{bot.name}</h2>
                <span className={cn("rounded-full px-2.5 py-1 text-xs font-medium capitalize", statusStyles[bot.status])}>
                  {bot.status}
                </span>
              </div>
              <div className="flex flex-wrap gap-2">
                <Badge>{providerLabels[bot.provider]}</Badge>
                <Badge>{bot.model}</Badge>
                <Badge>ID {bot.id}</Badge>
              </div>
              <div className="flex flex-wrap gap-4 text-sm text-muted-foreground">
                <span className="flex items-center gap-2">
                  <KeyRound className="h-4 w-4" />
                  {bot.apiKeyMasked ?? "Key masked"}
                </span>
                <span className="flex items-center gap-2">
                  <Calendar className="h-4 w-4" />
                  {bot.createdAt ? new Intl.DateTimeFormat("en", { dateStyle: "medium" }).format(new Date(bot.createdAt)) : "Created date unavailable"}
                </span>
              </div>
            </div>
            <div className="flex shrink-0 gap-2">
              <Button asChild variant="outline">
                <Link href={`/bots/${bot.id}`}>
                  <Pencil className="h-4 w-4" />
                  Edit
                </Link>
              </Button>
              <Button variant="ghost" onClick={() => onDelete(bot)}>
                <Trash2 className="h-4 w-4" />
                Delete
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}

function Badge({ children }: { children: React.ReactNode }) {
  return <span className="rounded-full border border-border bg-background px-2.5 py-1 text-xs text-muted-foreground">{children}</span>;
}
