"use client";

import { useCallback, useEffect, useState } from "react";

// Every request is in exactly one of these states, so the UI can never
// show a blank screen or stale fake data.
export type ApiState<T> =
  | { status: "loading" }
  | { status: "success"; data: T }
  | { status: "error"; message: string };

// `fetcher` must be a stable function (we pass module-level functions).
export function useApi<T>(fetcher: () => Promise<T>) {
  const [state, setState] = useState<ApiState<T>>({ status: "loading" });

  const load = useCallback(() => {
    setState({ status: "loading" });
    fetcher()
      .then((data) => setState({ status: "success", data }))
      .catch((e: unknown) =>
        setState({ status: "error", message: e instanceof Error ? e.message : "Unknown error" }),
      );
  }, [fetcher]);

  useEffect(load, [load]);
  return { state, reload: load };
}
