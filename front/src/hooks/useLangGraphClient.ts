import { useMemo } from "react";
import { Client } from "@langchain/langgraph-sdk";
import { useAuth } from "@/components/providers/auth.tsx";
import { API_BASE_URL } from "@/config.ts";

/**
 * Returns a LangGraph SDK Client configured with the current user's token.
 * Returns null while the user is not authenticated.
 */
export const useLangGraphClient = (): Client | null => {
  const { token } = useAuth();
  return useMemo(() => {
    if (!token) return null;
    return new Client({
      apiUrl: API_BASE_URL,
      apiKey: token,
      defaultHeaders: {
        Authorization: `Bearer ${token}`,
      },
    });
  }, [token]);
};
