"use client";

import { useCallback, useEffect, useState } from "react";

import { api, apiError, rowsOf } from "./api";
import { screenStateFromHttp, type ScreenState } from "./screens/status";

/**
 * Load ``/orgs/{orgId}{path}`` (or an absolute ``/...`` path when ``orgScoped`` is false).
 * Empty lists become the "empty" state; 501 becomes "off".
 */
export function useOrgData<T>(orgId: string | null, path: string | null, opts: { orgScoped?: boolean; list?: boolean } = {}) {
  const { orgScoped = true, list = false } = opts;
  const [data, setData] = useState<T | null>(null);
  const [state, setState] = useState<ScreenState>("loading");
  const [error, setError] = useState<string | null>(null);

  const fetchNow = useCallback(() => {
    if (path === null || (orgScoped && !orgId)) return;
    const url = orgScoped ? `/orgs/${orgId}${path}` : path;
    api
      .get<T>(url)
      .then((value) => {
        setData(value);
        setState(list && rowsOf(value).length === 0 ? "empty" : "ready");
      })
      .catch((err) => {
        const e = apiError(err);
        setError(e.details || null);
        setState(screenStateFromHttp(e.status || 500));
      });
  }, [orgId, path, orgScoped, list]);

  // The first load happens with state already "loading"; setState runs only in the promise callbacks.
  useEffect(fetchNow, [fetchNow]);

  const reload = useCallback(() => {
    setState("loading");
    fetchNow();
  }, [fetchNow]);

  return { data, state, error, reload, setData };
}
