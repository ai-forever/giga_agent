import React from "react";
import { ArrowLeft } from "lucide-react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { GeneralSettings } from "./general";
import { LLMSettings } from "./llms";
import { EmbeddingsSettings } from "./embeddings";
import { SandboxSettings } from "./sandbox";
import { ImageGeneratorsSettings } from "./image-generators";
import { SearchEnginesSettings } from "./search-engines";
import { ConnectorsSettings } from "./connectors";
import { ChannelsSettings } from "./channels";
import { SkillsSettings } from "./skills";

const SETTINGS_TABS = [
  "general",
  "llm",
  "embedding",
  "connectors",
  "sandbox",
  "image",
  "search",
  "channels",
  "skills",
] as const;

type SettingsTab = (typeof SETTINGS_TABS)[number];

const isSettingsTab = (value: string | undefined): value is SettingsTab =>
  value !== undefined && SETTINGS_TABS.includes(value as SettingsTab);

const SettingsPage: React.FC = () => {
  const navigate = useNavigate();
  const { tab } = useParams<{ tab?: string }>();

  if (!isSettingsTab(tab)) {
    return <Navigate to="/settings/general" replace />;
  }

  const activeTab = tab;

  const tabs: { id: SettingsTab; label: string }[] = [
    { id: "general", label: "Основные" },
    { id: "llm", label: "LLM" },
    { id: "embedding", label: "Embeddings" },
    { id: "connectors", label: "Коннекторы" },
    { id: "image", label: "Image" },
    { id: "search", label: "Поиск" },
    { id: "sandbox", label: "Sandbox" },
    { id: "channels", label: "Каналы" },
    { id: "skills", label: "Скиллы" },
  ];

  const renderContent = () => {
    switch (activeTab) {
      case "general":
        return <GeneralSettings />;
      case "llm":
        return <LLMSettings />;
      case "embedding":
        return <EmbeddingsSettings />;
      case "connectors":
        return <ConnectorsSettings />;
      case "image":
        return <ImageGeneratorsSettings />;
      case "search":
        return <SearchEnginesSettings />;
      case "sandbox":
        return <SandboxSettings />;
      case "channels":
        return <ChannelsSettings />;
      case "skills":
        return <SkillsSettings />;
      default:
        return null;
    }
  };

  return (
    <div className="w-full flex lg:p-5 p-0 lg:mt-0 bg-card overflow-auto">
      <div className="flex flex-col max-w-[1000px] mx-auto h-full w-full flex-1 bg-card  print:overflow-visible print:shadow-none">
        {/* Header */}
        <div className="flex items-center gap-4 p-6 border-b border-border">
          <h1 className="text-xl font-semibold">Настройки</h1>
        </div>

        {/* Tab badges */}
        <div className="flex flex-none overflow-x-auto gap-2 p-4 border-b border-border">
          {tabs.map((tab) => (
            <Badge
              key={tab.id}
              variant={activeTab === tab.id ? "default" : "outline"}
              className="cursor-pointer px-4 py-1.5 text-sm"
              onClick={() => navigate(`/settings/${tab.id}`)}
            >
              {tab.label}
            </Badge>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 p-6 flex flex-col">{renderContent()}</div>
      </div>
    </div>
  );
};

export default SettingsPage;
