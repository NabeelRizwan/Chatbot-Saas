"use client";

import { ArrowLeft, ArrowUpRight, Bot, Check, Loader2, MessageSquare, BookOpen } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { BrandMark } from "@/components/brand/brand-mark";
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
    <main className="auth-layout">
      <section className="auth-story" aria-label="Chatbot SaaS">
        <Link href="/welcome" className="auth-brand"><span><BrandMark size={35} /></span>Chatbot SaaS</Link>
        <div className="auth-story-body">
          <p className="auth-eyebrow">A little more human.</p>
          <h2>Your knowledge.<br />Better conversations.</h2>
          <p>Give every visitor a helpful place to start. Build an assistant that knows your business and feels like part of your team.</p>
          <div className="auth-flow" aria-hidden="true"><BookOpen /><span /><Bot /><span /><MessageSquare /></div>
          <ul>
            <li><Check />Answers grounded in your content</li>
            <li><Check />A chat experience that fits your brand</li>
            <li><Check />Your assistants, together in one workspace</li>
          </ul>
        </div>
        <Link href="/welcome" className="auth-back"><ArrowLeft className="h-4 w-4" />Back to the website</Link>
      </section>
      <section className="auth-form-side">
      <div className="auth-form-card">
        <div className="mb-7 flex h-12 w-12 items-center justify-center text-primary"><BrandMark size={44} /></div>
        <div className="flex items-center gap-3">
          <div>
            <p className="mb-3 text-xs font-medium uppercase tracking-[0.16em] text-primary">{mode === "login" ? "Welcome back" : "Make yourself at home"}</p>
            <h1 className="text-3xl font-semibold tracking-tight">{mode === "login" ? "Sign in" : "Create workspace"}</h1>
            <p className="mt-3 text-sm leading-6 text-muted-foreground">{mode === "login" ? "Your assistants and conversations are waiting for you." : "Start with your account. Then bring your first assistant to life."}</p>
          </div>
        </div>

        <form onSubmit={(event) => { event.preventDefault(); void submit(); }}>
        <fieldset disabled={loading || !mounted} className="mt-6 space-y-3">
          {mode === "register" && (
            <>
              <label htmlFor="auth-name" className="block text-sm font-medium">Your name</label>
              <input
                id="auth-name"
                autoComplete="name"
                required
                value={name}
                onChange={(event) => setName(event.target.value)}
                className="h-11 w-full rounded-lg border border-input bg-background px-3 text-sm outline-none"
                placeholder="Your name"
              />
              <label htmlFor="auth-organization" className="block text-sm font-medium">Organization name <span className="font-normal text-muted-foreground">(optional)</span></label>
              <input
                id="auth-organization"
                autoComplete="organization"
                value={organizationName}
                onChange={(event) => setOrganizationName(event.target.value)}
                className="h-11 w-full rounded-lg border border-input bg-background px-3 text-sm outline-none"
                placeholder="Organization name"
              />
            </>
          )}
          <label htmlFor="auth-email" className="block text-sm font-medium">Email</label>
          <input
            id="auth-email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="h-11 w-full rounded-lg border border-input bg-background px-3 text-sm outline-none"
            placeholder="Email"
            type="email"
          />
          <label htmlFor="auth-password" className="block text-sm font-medium">Password</label>
          <input
            id="auth-password"
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="h-11 w-full rounded-lg border border-input bg-background px-3 text-sm outline-none"
            placeholder="Password"
            type="password"
          />
        </fieldset>

        {error && <div role="alert" className="mt-4 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</div>}

        <Button type="submit" className="mt-5 w-full" disabled={!mounted || loading || !email || !password || (mode === "register" && !name)}>
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          {mode === "login" ? "Sign in" : "Create account"}
          {!loading && <ArrowUpRight className="h-4 w-4" />}
        </Button>
        </form>

        <Button asChild className="mt-3 w-full" variant="ghost">
          <Link href={mode === "login" ? "/signup" : "/login"}>{mode === "login" ? "Create an account" : "Already have an account? Sign in"}</Link>
        </Button>
      </div>
      </section>
    </main>
  );
}
