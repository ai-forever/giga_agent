import React, { useCallback, useEffect, useRef, useState } from "react";
import Chat from "./components/Chat";
import ExperimentalChat from "./components/ExperimentalChat";
import { useExperimentalMode } from "@/hooks/useExperimentalMode.ts";
import { SettingsProvider, useSettings } from "./components/Settings.tsx";
import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import Sidebar from "./components/Sidebar.tsx";
import DemoSettings from "./components/demo/DemoSettings.tsx";
import type { UseStream } from "@langchain/langgraph-sdk/react";
import { GraphState } from "./interfaces.ts";
import { RagProvider } from "@/components/rag/providers/RAG.tsx";
import RAGInterface from "@/components/rag";
import { OAuthCallback } from "@/components/mcp/oauth-callback.tsx";
import { UserInfoProvider } from "@/components/providers/user-info.tsx";
import { SkillsProvider } from "@/components/providers/skills.tsx";
import { AuthProvider } from "@/components/providers/auth.tsx";
import { ApiProvider } from "@/components/providers/api.tsx";
import { ThemeProvider } from "@/components/providers/theme.tsx";
import { ConfirmProvider } from "@/components/providers/confirm.tsx";
import { Toaster } from "@/components/ui/sonner.tsx";
import MemoriesPage from "@/components/memories/MemoriesPage.tsx";
import ProjectPage from "@/components/projects/ProjectPage.tsx";
import LoginPage from "@/components/auth/LoginPage.tsx";
import JoinPage from "@/components/auth/JoinPage.tsx";
import ProtectedRoute from "@/components/auth/ProtectedRoute.tsx";
import SettingsPage from "@/components/settings-page";
import AdminPanelPage from "@/components/admin-panel";
import SchedulerPage from "@/components/scheduler";
import AgentsPage from "@/components/agents";
import { runtimeConfig } from "@/config";
import OnboardingWizard from "@/components/onboarding/OnboardingWizard";
import FunctionalityOnboarding from "@/components/onboarding/FunctionalityOnboarding";
import { FunctionalityOnboardingProvider } from "@/components/onboarding/FunctionalityOnboardingContext";

const normalizeHttpBaseUrl = (input: string): string | null => {
  const trimmed = input.trim();
  if (!trimmed) {
    return null;
  }

  try {
    const parsed = new URL(trimmed);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return null;
    }

    const normalizedPath = parsed.pathname.replace(/\/+$/, "");
    return `${parsed.origin}${normalizedPath}`;
  } catch {
    return null;
  }
};

const InnerApp: React.FC = () => {
  const location = useLocation();
  const prevPathRef = useRef(location.pathname);
  // Можно использовать булево или просто число-счётчик
  const [reloadKey, setReloadKey] = useState(0);
  const currentThreadIdRef = useRef<string | null>(null);
  const currentThreadRef = useRef<UseStream<GraphState> | null>(null);

  useEffect(() => {
    if (location.pathname === "/" && prevPathRef.current !== "/") {
      setReloadKey((prev) => prev + 1);
    }
    prevPathRef.current = location.pathname;
  }, [location.pathname]);

  // эта функция будет прокидываться в Sidebar
  const handleNavigateAndReload = useCallback(() => {
    // Только останавливаем текущий стрим. Remount (новый reloadKey) выполняет
    // эффект выше — он меняет key лишь когда маршрут уже стал "/". Если бампать
    // key здесь, <Chat> успевает перемонтироваться, пока маршрут ещё
    // /threads/:id, и новый useStream грузит state предыдущего треда.
    if (currentThreadRef.current) {
      // currentThreadRef.current.stop();
    }
  }, []);

  const handleThreadIdChange = useCallback((threadId: string) => {
    currentThreadIdRef.current = threadId;
  }, []);

  const handleThreadReady = useCallback((thread: UseStream<GraphState>) => {
    currentThreadRef.current = thread;
  }, []);

  // Тред мог получить новые сообщения, пока вкладка была в фоне (ран успел
  // завершиться). Перемонтируем <Chat>, чтобы useStream заново подтянул state.
  const handleRequestReload = useCallback(() => {
    setReloadKey((prev) => prev + 1);
  }, []);

  return (
    <FunctionalityOnboardingProvider>
      <Sidebar onNewChat={handleNavigateAndReload} />
      <MainContent>
        <AppRoutes
          reloadKey={reloadKey}
          onNavigateAndReload={handleNavigateAndReload}
          onThreadIdChange={handleThreadIdChange}
          onThreadReady={handleThreadReady}
          onRequestReload={handleRequestReload}
        />
      </MainContent>
      <OnboardingWizard />
      <FunctionalityOnboarding />
    </FunctionalityOnboardingProvider>
  );
};

const AppRoutes: React.FC<{
  reloadKey: number;
  onNavigateAndReload: () => void;
  onThreadIdChange: (threadId: string) => void;
  onThreadReady: (thread: UseStream<GraphState>) => void;
  onRequestReload: () => void;
}> = React.memo(
  ({ reloadKey, onThreadIdChange, onThreadReady, onRequestReload }) => {
    const { experimentalActive } = useExperimentalMode();
    const ChatComponent = experimentalActive ? ExperimentalChat : Chat;
    return (
      <Routes>
        <Route
          path="/"
          element={
            <ChatComponent
              key={reloadKey}
              onThreadIdChange={onThreadIdChange}
              onThreadReady={onThreadReady}
              onRequestReload={onRequestReload}
            />
          }
        />
        <Route
          path="/threads/:threadId"
          element={
            <ChatComponent
              key={reloadKey}
              onThreadIdChange={onThreadIdChange}
              onThreadReady={onThreadReady}
              onRequestReload={onRequestReload}
            />
          }
        />
        {/*
          Dev-маршрут: всегда рендерит ОРИГИНАЛЬНЫЙ Chat (assistant "giga_agent"),
          даже в экспериментальном режиме. Нужен, чтобы посмотреть сырой inner-тред
          (id берётся из state внешнего треда: inner_thread_id) в обычном UI.
        */}
        <Route
          path="/dev"
          element={
            <Chat
              key={reloadKey}
              assistantId="giga_agent"
              onThreadIdChange={onThreadIdChange}
              onThreadReady={onThreadReady}
              onRequestReload={onRequestReload}
            />
          }
        />
        <Route
          path="/dev/threads/:threadId"
          element={
            <Chat
              key={reloadKey}
              assistantId="giga_agent"
              onThreadIdChange={onThreadIdChange}
              onThreadReady={onThreadReady}
              onRequestReload={onRequestReload}
            />
          }
        />
        <Route path="/oauth/callback" element={<OAuthCallback />} />
        <Route path="/rag" element={<RAGInterface />} />
        <Route path="/memories" element={<MemoriesPage />} />
        <Route path="/scheduler" element={<SchedulerPage />} />
        <Route path="/agents/*" element={<AgentsPage />} />
        <Route path="/projects/:projectId" element={<ProjectPage />} />
        <Route path="/demo/settings" element={<DemoSettings />} />
        <Route
          path="/settings"
          element={<Navigate to="/settings/general" replace />}
        />
        <Route path="/settings/:tab" element={<SettingsPage />} />
        <Route
          path="/admin-panel"
          element={<Navigate to="/admin-panel/users" replace />}
        />
        <Route path="/admin-panel/users" element={<AdminPanelPage />} />
        <Route path="/admin-panel/groups" element={<AdminPanelPage />} />
        <Route path="/admin-panel/invites" element={<AdminPanelPage />} />
      </Routes>
    );
  },
);

AppRoutes.displayName = "AppRoutes";

const MainContent: React.FC<{ children: React.ReactNode }> = React.memo(
  ({ children }) => {
    const { settings } = useSettings();
    return (
      <div
        className={[
          "flex grow min-h-0 transition-[margin] duration-300 ease-in-out",
          "",
          settings.sideBarOpen ? "min-[900px]:ml-[270px]" : "min-[900px]:ml-0",
          "print:!ml-0",
        ].join(" ")}
      >
        {children}
      </div>
    );
  },
);

MainContent.displayName = "MainContent";

const App: React.FC = () => {
  return (
    <BrowserRouter basename={runtimeConfig.basePath || undefined}>
      <AuthProvider>
        <ThemeProvider>
          <ConfirmProvider>
            <ApiProvider>
              <Toaster />
              <SettingsProvider>
                <RagProvider>
                  <UserInfoProvider>
                    <SkillsProvider>
                      <Routes>
                        <Route path="/login" element={<LoginPage />} />
                        <Route path="/join/:token" element={<JoinPage />} />
                        <Route
                          path="/*"
                          element={
                            <ProtectedRoute>
                              <div className="flex flex-col grow h-svh w-full mx-auto print:h-auto overflow-y-auto print:overflow-visible">
                                <InnerApp />
                              </div>
                            </ProtectedRoute>
                          }
                        />
                      </Routes>
                    </SkillsProvider>
                  </UserInfoProvider>
                </RagProvider>
              </SettingsProvider>
            </ApiProvider>
          </ConfirmProvider>
        </ThemeProvider>
      </AuthProvider>
    </BrowserRouter>
  );
};

export default App;
