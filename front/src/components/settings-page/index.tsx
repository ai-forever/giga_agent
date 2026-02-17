import React, { useState } from "react";
import { ArrowLeft } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { GeneralSettings } from "./general";
import { LLMSettings } from "./llms";
import { SandboxSettings } from "./sandbox";
import { ImageGeneratorsSettings } from "./image-generators";
import { SearchEnginesSettings } from "./search-engines";

type SettingsTab = "general" | "llm" | "sandbox" | "image" | "search";

const SettingsPage: React.FC = () => {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<SettingsTab>("general");

  const tabs: { id: SettingsTab; label: string }[] = [
    { id: "general", label: "Основные" },
    { id: "llm", label: "LLM" },
    { id: "image", label: "Image" },
    { id: "search", label: "Поиск" },
    { id: "sandbox", label: "Sandbox" },
  ];

  const handleBack = () => {
    navigate(-1);
  };

  const renderContent = () => {
    switch (activeTab) {
      case "general":
        return <GeneralSettings />;
      case "llm":
        return <LLMSettings />;
      case "image":
        return <ImageGeneratorsSettings />;
      case "search":
        return <SearchEnginesSettings />;
      case "sandbox":
        return <SandboxSettings />;
      default:
        return null;
    }
  };

  return (
    <div className="w-full flex lg:p-5 p-0 lg:mt-0 mt-[75px]">
      <div className="flex flex-col max-w-[900px] mx-auto h-full flex-1 bg-card/80 backdrop-blur-xl rounded-lg shadow-2xl overflow-hidden print:overflow-visible print:shadow-none">
        {/* Header */}
        <div className="flex items-center gap-4 p-6 border-b border-border">
          <Button variant="ghost" size="icon" onClick={handleBack}>
            <ArrowLeft className="size-5" />
          </Button>
          <h1 className="text-xl font-semibold">Настройки</h1>
        </div>

        {/* Tab badges */}
        <div className="flex gap-2 p-4 border-b border-border">
          {tabs.map((tab) => (
            <Badge
              key={tab.id}
              variant={activeTab === tab.id ? "default" : "outline"}
              className="cursor-pointer px-4 py-1.5 text-sm"
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
            </Badge>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-auto p-6 flex flex-col">
          {renderContent()}
        </div>
      </div>
    </div>
  );
};

export default SettingsPage;
