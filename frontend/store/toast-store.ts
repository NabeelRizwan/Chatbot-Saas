import { create } from "zustand";

export type ToastVariant = "success" | "error" | "info";

export type ToastMessage = {
  id: string;
  title: string;
  description?: string;
  variant: ToastVariant;
};

type ToastState = {
  toasts: ToastMessage[];
  showToast: (toast: Omit<ToastMessage, "id">) => void;
  dismissToast: (id: string) => void;
};

export const useToastStore = create<ToastState>()((set) => ({
  toasts: [],
  showToast: (toast) => {
    const id = crypto.randomUUID();
    set((state) => ({ toasts: [...state.toasts, { ...toast, id }] }));
    window.setTimeout(() => {
      set((state) => ({ toasts: state.toasts.filter((item) => item.id !== id) }));
    }, 4500);
  },
  dismissToast: (id) => set((state) => ({ toasts: state.toasts.filter((toast) => toast.id !== id) })),
}));
