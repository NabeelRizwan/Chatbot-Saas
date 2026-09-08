import { Suspense } from "react";
import { AdminPlans } from "@/components/admin/admin-management";
export default function Page() { return <Suspense fallback={<p>Loading plans…</p>}><AdminPlans /></Suspense>; }
