"use client";

import { Bot, Loader2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { useMounted } from "@/hooks/use-mounted";
import { login, register } from "@/services/auth-service";
import { useAuthStore } from "@/store/auth-store";

type AuthPageProps = {
  mode: "login" | "register";
};

export function AuthPage({ mode }: AuthPageProps) {
  const router = useRouter();
  const mounted = useMounted();
  const accessToken = useAuthStore((state) => state.accessToken);
  const setSession = useAuthStore((state) => state.setSession);
  const [name, setName] = useState("");
  const [organizationName, setOrganizationName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (mounted && accessToken) {
      router.replace("/");
    }
  }, [accessToken, mounted, router]);

  async function submit() {
    setLoading(true);
    setError(null);
    try {
      const session =
        mode === "login"
          ? await login({ email, password })
          : await register({ name, email, password, organizationName: organizationName || undefined });
      setSession(session.accessToken, session.user);
      router.push("/");
    } catch (authError) {
      setError(authError instanceof Error ? authError.message : "Authentication failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-background p-4">
      <div className="w-full max-w-md rounded-lg border border-border bg-card p-6 shadow-soft">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <Bot className="h-5 w-5" />
          </div>
          <div>
            <h1 className="text-xl font-semibold">{mode === "login" ? "Sign in" : "Create workspace"}</h1>
            <p className="text-sm text-muted-foreground">Manage bots, teams, usage, and billing.</p>
          </div>
        </div>

        <div className="mt-6 space-y-3">
          {mode === "register" && (
            <>
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                className="h-11 w-full rounded-lg border border-input bg-background px-3 text-sm outline-none"
                placeholder="Your name"
              />
              <input
                value={organizationName}
                onChange={(event) => setOrganizationName(event.target.value)}
                className="h-11 w-full rounded-lg border border-input bg-background px-3 text-sm outline-none"
                placeholder="Organization name"
              />
            </>
          )}
          <input
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="h-11 w-full rounded-lg border border-input bg-background px-3 text-sm outline-none"
            placeholder="Email"
            type="email"
          />
          <input
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="h-11 w-full rounded-lg border border-input bg-background px-3 text-sm outline-none"
            placeholder="Password"
            type="password"
          />
        </div>

        {error && <div className="mt-4 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</div>}

        <Button className="mt-5 w-full" disabled={loading || !email || !password || (mode === "register" && !name)} onClick={() => void submit()}>
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          {mode === "login" ? "Sign in" : "Create account"}
        </Button>

        <Button asChild className="mt-3 w-full" variant="ghost">
          <Link href={mode === "login" ? "/signup" : "/login"}>{mode === "login" ? "Create an account" : "Already have an account? Sign in"}</Link>
        </Button>
      </div>
    </main>
  );
}
