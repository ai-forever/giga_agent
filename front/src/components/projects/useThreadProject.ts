import { useEffect, useMemo, useState } from "react";
import { Client } from "@langchain/langgraph-sdk";

import { useAuth } from "@/components/providers/auth.tsx";
import { API_BASE_URL } from "@/config.ts";

import { getProject, Project } from "./api";

/**
 * Resolve which Project a LangGraph thread belongs to.
 *
 * Reads thread.metadata.project_id via LangGraph SDK, then fetches the
 * project record. Returns null when the thread isn't part of any project.
 */
export function useThreadProject(threadId: string | undefined | null) {
  const { token } = useAuth();
  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(false);

  const langGraphClient = useMemo(() => {
    if (!token) return null;
    return new Client({
      apiUrl: API_BASE_URL,
      apiKey: token,
      defaultHeaders: { Authorization: `Bearer ${token}` },
    });
  }, [token]);

  useEffect(() => {
    if (!threadId || !langGraphClient) {
      setProject(null);
      return;
    }
    const ctrl = new AbortController();
    setLoading(true);
    (async () => {
      try {
        const thread = await langGraphClient.threads.get(threadId);
        const projectId = (thread.metadata as { project_id?: string } | null)
          ?.project_id;
        if (!projectId) {
          if (!ctrl.signal.aborted) setProject(null);
          return;
        }
        const p = await getProject(projectId, { signal: ctrl.signal });
        if (!ctrl.signal.aborted) setProject(p);
      } catch (e) {
        if (ctrl.signal.aborted) return;
        console.error("useThreadProject: failed", e);
        setProject(null);
      } finally {
        if (!ctrl.signal.aborted) setLoading(false);
      }
    })();
    return () => ctrl.abort();
  }, [threadId, langGraphClient]);

  return { project, loading };
}
