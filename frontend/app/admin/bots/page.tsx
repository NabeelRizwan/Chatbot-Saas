import { Suspense } from "react";
import { AdminBots } from "@/components/admin/admin-console";
export default function Page() { return <Suspense fallback={<p>Loading bots…</p>}><AdminBots /></Suspense>; }
