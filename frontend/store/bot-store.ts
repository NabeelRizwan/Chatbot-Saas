import { create } from "zustand";

import * as botService from "@/services/bot-service";
import type { Bot, BotCreateInput, BotUpdateInput } from "@/types/bot";

type BotState = {
  bots: Bot[];
  selectedBot: Bot | null;
  loading: boolean;
  selectedLoading: boolean;
  mutating: boolean;
  error: string | null;
  fetchBots: () => Promise<void>;
  fetchBot: (id: string) => Promise<void>;
  createBot: (input: BotCreateInput) => Promise<Bot>;
  updateBot: (id: string, input: BotUpdateInput) => Promise<Bot>;
  deleteBot: (id: string) => Promise<void>;
  clearError: () => void;
};

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong";
}

export const useBotStore = create<BotState>()((set, get) => ({
  bots: [],
  selectedBot: null,
  loading: false,
  selectedLoading: false,
  mutating: false,
  error: null,
  fetchBots: async () => {
    set({ loading: true, error: null });
    try {
      const bots = await botService.getBots();
      set({ bots, loading: false });
    } catch (error) {
      set({ error: getErrorMessage(error), loading: false });
    }
  },
  fetchBot: async (id) => {
    set({ selectedLoading: true, error: null });
    try {
      const bot = await botService.getBot(id);
      set({ selectedBot: bot, selectedLoading: false });
    } catch (error) {
      set({ error: getErrorMessage(error), selectedBot: null, selectedLoading: false });
    }
  },
  createBot: async (input) => {
    set({ mutating: true, error: null });
    try {
      const bot = await botService.createBot(input);
      set((state) => ({ bots: [bot, ...state.bots], selectedBot: bot, mutating: false }));
      return bot;
    } catch (error) {
      set({ error: getErrorMessage(error), mutating: false });
      throw error;
    }
  },
  updateBot: async (id, input) => {
    set({ mutating: true, error: null });
    try {
      const bot = await botService.updateBot(id, input);
      set((state) => ({
        bots: state.bots.map((item) => (item.id === id ? bot : item)),
        selectedBot: bot,
        mutating: false,
      }));
      return bot;
    } catch (error) {
      set({ error: getErrorMessage(error), mutating: false });
      throw error;
    }
  },
  deleteBot: async (id) => {
    const previousBots = get().bots;
    set((state) => ({
      bots: state.bots.filter((bot) => bot.id !== id),
      selectedBot: state.selectedBot?.id === id ? null : state.selectedBot,
      mutating: true,
      error: null,
    }));

    try {
      await botService.deleteBot(id);
      set({ mutating: false });
    } catch (error) {
      set({ bots: previousBots, error: getErrorMessage(error), mutating: false });
      throw error;
    }
  },
  clearError: () => set({ error: null }),
}));
