import React, { useRef, useState, useEffect } from "react";
import Chat from "./components/Chat";
import { SettingsProvider } from "./components/Settings.tsx";
import { BrowserRouter, Route, Routes, useLocation } from "react-router-dom";
import Sidebar from "./components/Sidebar.tsx";
import DemoSettings from "./components/demo/DemoSettings.tsx";
import { DemoItemsProvider, useDemoItems } from "./hooks/DemoItemsProvider.tsx";
import DemoChat from "./components/demo/DemoChat.tsx";
import type { UseStream } from "@langchain/langgraph-sdk/react";
import { GraphState } from "./interfaces.ts";
import { RagProvider } from "@/components/rag/providers/RAG.tsx";
import RAGInterface from "@/components/rag";
import { OAuthCallback } from "@/components/mcp/oauth-callback.tsx";
import { UserInfoProvider } from "@/components/providers/user-info.tsx";
import { AuthProvider } from "@/components/providers/auth.tsx";
import { ApiProvider } from "@/components/providers/api.tsx";
import { ThemeProvider } from "@/components/providers/theme.tsx";
import { Toaster } from "@/components/ui/sonner.tsx";
import MemoriesPage from "@/components/memories/MemoriesPage.tsx";
import LoginPage from "@/components/auth/LoginPage.tsx";
import ProtectedRoute from "@/components/auth/ProtectedRoute.tsx";
import SettingsPage from "@/components/settings-page";

const InnerApp: React.FC = () => {
  const location = useLocation();
  const prevPathRef = useRef(location.pathname);
  const { demoItemsLoaded } = useDemoItems();
  // Можно использовать булево или просто число-счётчик
  const [reloadKey, setReloadKey] = useState(0);
  const [currentThreadId, setCurrentThreadId] = useState<string | null>(null);
  const currentThreadRef = useRef<UseStream<GraphState> | null>(null);

  useEffect(() => {
    if (location.pathname === "/" && prevPathRef.current !== "/") {
      setReloadKey((prev) => prev + 1);
    }
    prevPathRef.current = location.pathname;
  }, [location.pathname]);

  // эта функция будет прокидываться в SidebarComponent
  const handleNavigateAndReload = () => {
    // переключаем флаг, чтобы сделать новый key у соседнего компонента
    setReloadKey((prev) => prev + 1);
    if (currentThreadRef.current) {
      currentThreadRef.current.stop();
    }
  };

  const handleThreadIdChange = (threadId: string) => {
    setCurrentThreadId(threadId);
  };

  const handleThreadReady = (thread: UseStream<GraphState>) => {
    currentThreadRef.current = thread;
  };
  if (!demoItemsLoaded) {
    return null;
  }
  return (
    <Sidebar onNewChat={handleNavigateAndReload}>
      <Routes>
        <Route
          path="/"
          element={
            <Chat
              key={reloadKey}
              onThreadIdChange={handleThreadIdChange}
              onThreadReady={handleThreadReady}
            />
          }
        />
        <Route
          path="/threads/:threadId"
          element={
            <Chat
              key={reloadKey}
              onThreadIdChange={handleThreadIdChange}
              onThreadReady={handleThreadReady}
            />
          }
        />
        <Route
          path="/demo/:demoIndex"
          element={
            <DemoChat
              key={reloadKey}
              onContinue={handleNavigateAndReload}
              onThreadIdChange={handleThreadIdChange}
              onThreadReady={handleThreadReady}
            />
          }
        />
        <Route path="/oauth/callback" element={<OAuthCallback />} />
        <Route path="/rag" element={<RAGInterface />} />
        <Route path="/memories" element={<MemoriesPage />} />
        <Route path="/demo/settings" element={<DemoSettings />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Routes>
    </Sidebar>
  );
};

const App: React.FC = () => {
  return (
      <BrowserRouter>
        <AuthProvider>
        <ThemeProvider>
          <ApiProvider>
            <DemoItemsProvider>
              <Toaster />
              <SettingsProvider>
                <RagProvider>
                  <UserInfoProvider>
                    <Routes>
                      <Route path="/login" element={<LoginPage />} />
                      <Route
                        path="/*"
                        element={
                          <ProtectedRoute>
                            <div className="flex h-auto w-full mx-auto print:h-auto">
                              <InnerApp />
                            </div>
                          </ProtectedRoute>
                        }
                      />
                    </Routes>
                  </UserInfoProvider>
                </RagProvider>
              </SettingsProvider>
            </DemoItemsProvider>
          </ApiProvider>
          </ThemeProvider>
        </AuthProvider>
      </BrowserRouter>
  );
};

export default App;
