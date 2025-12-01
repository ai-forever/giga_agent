import React, { useRef, useState } from "react";
import Chat from "./components/Chat";
import { SettingsProvider } from "./components/Settings.tsx";
import { BrowserRouter, Route, Routes } from "react-router-dom";
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
import { Toaster } from "@/components/ui/sonner.tsx";
import MemoriesPage from "@/components/memories/MemoriesPage.tsx";

const InnerApp: React.FC = () => {
  const { demoItemsLoaded } = useDemoItems();
  // Можно использовать булево или просто число-счётчик
  const [reloadKey, setReloadKey] = useState(0);
  const [currentThreadId, setCurrentThreadId] = useState<string | null>(null);
  const currentThreadRef = useRef<UseStream<GraphState> | null>(null);

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
      </Routes>
    </Sidebar>
  );
};

const App: React.FC = () => {
  return (
    <DemoItemsProvider>
            <Toaster />
      <SettingsProvider>
        <RagProvider>
          <UserInfoProvider>
            <div className="flex h-auto w-full mx-auto print:h-auto">
              <BrowserRouter>
                <InnerApp />
              </BrowserRouter>
            </div>
          </UserInfoProvider>
        </RagProvider>
      </SettingsProvider>
    </DemoItemsProvider>
  );
};

export default App;
