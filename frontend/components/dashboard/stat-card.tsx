"use client";

import { motion } from "framer-motion";
import type { LucideIcon } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type StatCardProps = {
  label: string;
  value: string;
  change: string;
  icon: LucideIcon;
  tone: "blue" | "green" | "amber" | "neutral";
  index: number;
};

const tones = {
  blue: "bg-primary/10 text-primary",
  green: "bg-accent/15 text-accent",
  amber: "bg-amber-500/15 text-amber-600 dark:text-amber-300",
  neutral: "bg-muted text-muted-foreground",
};

export function StatCard({ label, value, change, icon: Icon, tone, index }: StatCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: index * 0.05 }}
    >
      <Card>
        <CardContent className="p-5">
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-sm text-muted-foreground">{label}</p>
              <p className="mt-2 text-2xl font-semibold tracking-normal">{value}</p>
            </div>
            <div className={cn("flex h-10 w-10 items-center justify-center rounded-lg", tones[tone])}>
              <Icon className="h-5 w-5" />
            </div>
          </div>
          <p className="mt-4 text-sm text-muted-foreground">{change}</p>
        </CardContent>
      </Card>
    </motion.div>
  );
}
