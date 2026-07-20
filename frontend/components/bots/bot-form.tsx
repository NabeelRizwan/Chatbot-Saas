"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { KeyRound, Loader2, Save, Sparkles } from "lucide-react";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { EmbedSnippetCard } from "@/components/bots/embed-snippet-card";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { providerLabels, providerModels, providers, type Bot, type BotCreateInput, type BotUpdateInput } from "@/types/bot";

const baseSchema = z
  .object({
    customerApiKey: z.string().optional(),
    name: z.string().trim().min(2, "Bot name must be at least 2 characters.").max(120, "Bot name is too long."),
    provider: z.enum(providers, "Choose a supported provider."),
    model: z.string().trim().min(1, "Choose a model."),
    providerApiKey: z.string().optional(),
    welcomeMessage: z.string().trim().max(500, "Welcome message must be under 500 characters.").optional(),
    systemPrompt: z.string().trim().min(10, "System prompt must be at least 10 characters.").max(4000, "System prompt is too long."),
  })
  .superRefine((value, context) => {
    if (!providerModels[value.provider].includes(value.model)) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["model"],
        message: "Choose a model supported by the selected provider.",
      });
    }
  });

const createSchema = baseSchema.superRefine((value, context) => {
  if (!value.customerApiKey || value.customerApiKey.trim().length < 12) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["customerApiKey"],
      message: "Customer API key is required by the current backend.",
    });
  }

  if (!value.providerApiKey || value.providerApiKey.trim().length < 12) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["providerApiKey"],
      message: "Provider API key must be at least 12 characters.",
    });
  }
});

const editSchema = baseSchema.superRefine((value, context) => {
  if (value.providerApiKey && value.providerApiKey.trim().length > 0 && value.providerApiKey.trim().length < 12) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["providerApiKey"],
      message: "New provider API key must be at least 12 characters.",
    });
  }
});

type BotFormValues = z.infer<typeof baseSchema>;

type BotFormProps = {
  mode: "create" | "edit";
  bot?: Bot;
  loading?: boolean;
  onSubmit: (values: BotCreateInput | BotUpdateInput) => Promise<void>;
};

const defaultPrompt =
  "You are a helpful AI support assistant. Answer clearly using the available knowledge base and ask clarifying questions when needed.";

export function BotForm({ mode, bot, loading = false, onSubmit }: BotFormProps) {
  const schema = mode === "create" ? createSchema : editSchema;
  const {
    register,
    handleSubmit,
    watch,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<BotFormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      customerApiKey: "",
      name: bot?.name ?? "",
      provider: bot?.provider ?? "gemini",
      model: bot?.model ?? "gemini-2.5-flash",
      providerApiKey: "",
      welcomeMessage: bot?.welcomeMessage ?? "Hi, how can I help you today?",
      systemPrompt: bot?.systemPrompt ?? defaultPrompt,
    },
  });

  const provider = watch("provider");

  useEffect(() => {
    const currentModel = watch("model");
    if (!providerModels[provider].includes(currentModel)) {
      setValue("model", providerModels[provider][0], { shouldValidate: true });
    }
  }, [provider, setValue, watch]);

  const submit = handleSubmit(async (values) => {
    const cleaned = {
      ...values,
      customerApiKey: values.customerApiKey?.trim() ?? "",
      providerApiKey: values.providerApiKey?.trim() ?? "",
      name: values.name.trim(),
      welcomeMessage: values.welcomeMessage?.trim(),
      systemPrompt: values.systemPrompt.trim(),
    };

    if (mode === "create") {
      await onSubmit(cleaned as BotCreateInput);
      return;
    }

    await onSubmit({
      name: cleaned.name,
      provider: cleaned.provider,
      model: cleaned.model,
      providerApiKey: cleaned.providerApiKey || undefined,
      welcomeMessage: cleaned.welcomeMessage,
      systemPrompt: cleaned.systemPrompt,
    });
  });

  return (
    <form onSubmit={submit} className="grid gap-6 lg:grid-cols-[1fr_360px]">
      <div className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle>Bot Details</CardTitle>
            <CardDescription>Name the assistant and choose the model that will power responses.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            {mode === "create" && (
              <Field label="Customer API key" error={errors.customerApiKey?.message}>
                <input
                  {...register("customerApiKey")}
                  className="h-11 w-full rounded-lg border border-input bg-background px-3 text-sm outline-none transition focus:ring-2 focus:ring-ring"
                  placeholder="Customer API key from /customer/create"
                  type="password"
                />
              </Field>
            )}

            <Field label="Bot name" error={errors.name?.message}>
              <input
                {...register("name")}
                className="h-11 w-full rounded-lg border border-input bg-background px-3 text-sm outline-none transition focus:ring-2 focus:ring-ring"
                placeholder="Support Assistant"
              />
            </Field>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Provider" error={errors.provider?.message}>
                <select
                  {...register("provider")}
                  className="h-11 w-full rounded-lg border border-input bg-background px-3 text-sm outline-none transition focus:ring-2 focus:ring-ring"
                >
                  {providers.map((item) => (
                    <option key={item} value={item}>
                      {providerLabels[item]}
                    </option>
                  ))}
                </select>
              </Field>

              <Field label="Model" error={errors.model?.message}>
                <select
                  {...register("model")}
                  className="h-11 w-full rounded-lg border border-input bg-background px-3 text-sm outline-none transition focus:ring-2 focus:ring-ring"
                >
                  {providerModels[provider].map((model) => (
                    <option key={model} value={model}>
                      {model}
                    </option>
                  ))}
                </select>
              </Field>
            </div>

            <Field
              label={mode === "create" ? "Provider API key" : "Rotate provider API key"}
              error={errors.providerApiKey?.message}
              hint={mode === "edit" ? `Current key: ${bot?.apiKeyMasked ?? "masked by backend"}` : undefined}
            >
              <input
                {...register("providerApiKey")}
                className="h-11 w-full rounded-lg border border-input bg-background px-3 text-sm outline-none transition focus:ring-2 focus:ring-ring"
                placeholder={mode === "create" ? "Paste provider API key" : "Leave blank to keep current key"}
                type="password"
              />
            </Field>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Conversation Behavior</CardTitle>
            <CardDescription>Set the opening message and system instructions for the assistant.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <Field label="Welcome message" error={errors.welcomeMessage?.message}>
              <textarea
                {...register("welcomeMessage")}
                className="min-h-24 w-full resize-y rounded-lg border border-input bg-background px-3 py-3 text-sm outline-none transition focus:ring-2 focus:ring-ring"
                placeholder="Hi, how can I help you today?"
              />
            </Field>

            <Field label="System prompt" error={errors.systemPrompt?.message}>
              <textarea
                {...register("systemPrompt")}
                className="min-h-44 w-full resize-y rounded-lg border border-input bg-background px-3 py-3 text-sm outline-none transition focus:ring-2 focus:ring-ring"
                placeholder={defaultPrompt}
              />
            </Field>
          </CardContent>
        </Card>
      </div>

      <aside className="space-y-4">
        {mode === "edit" && bot?.id && <EmbedSnippetCard botId={bot.id} />}
        <Card className="sticky top-24">
          <CardHeader>
            <CardTitle>Provider Configuration</CardTitle>
            <CardDescription>Keys are submitted securely and never rendered back in full.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="rounded-lg border border-border bg-muted/40 p-4">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <Sparkles className="h-5 w-5" />
                </div>
                <div>
                  <p className="text-sm font-medium">{providerLabels[provider]}</p>
                  <p className="text-sm text-muted-foreground">{watch("model")}</p>
                </div>
              </div>
            </div>
            <div className="rounded-lg border border-border bg-background p-4 text-sm text-muted-foreground">
              <div className="mb-2 flex items-center gap-2 font-medium text-foreground">
                <KeyRound className="h-4 w-4" />
                Key handling
              </div>
              Provider keys are masked after creation. Use rotation to replace a key without displaying the original value.
            </div>
            <Button className="w-full" disabled={isSubmitting || loading}>
              {isSubmitting || loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              {mode === "create" ? "Create bot" : "Save changes"}
            </Button>
          </CardContent>
        </Card>
      </aside>
    </form>
  );
}

function Field({
  label,
  error,
  hint,
  children,
}: {
  label: string;
  error?: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block space-y-2">
      <span className="text-sm font-medium">{label}</span>
      {children}
      {hint && <span className="block text-xs text-muted-foreground">{hint}</span>}
      {error && <span className="block text-xs text-destructive">{error}</span>}
    </label>
  );
}
