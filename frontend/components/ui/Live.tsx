"use client";

import type { ReactNode } from "react";
import type { ApiState } from "@/hooks/useApi";
import { ErrorState, Skeleton } from "@/components/ui/ui";

/** Standard loading / error / success handling for any block fed by a real API call. */
export default function Live<T>({ state, onRetry, children, skeleton, errorTitle, quiet }: {
  state: ApiState<T>; onRetry?: () => void; children: (data: T) => ReactNode; skeleton?: ReactNode; errorTitle?: string; quiet?: boolean;
}) {
  if (state.status === "loading") return <>{skeleton ?? <div className="space-y-3"><Skeleton className="h-6 w-1/3" /><Skeleton className="h-32 w-full" /></div>}</>;
  if (state.status === "error") {
    if (quiet) return <p className="text-sm text-subtle">Live data unavailable. Start the FinSight API to see it here.</p>;
    return <ErrorState title={errorTitle ?? "Live data isn’t available"} body="The FinSight API couldn’t be reached, or the data isn’t loaded yet." onRetry={onRetry} />;
  }
  return <>{children(state.data)}</>;
}
