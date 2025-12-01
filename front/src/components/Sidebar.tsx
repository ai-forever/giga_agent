import React from "react";
import { useNavigate } from "react-router-dom";
import {
  Check,
  ChevronRight,
  Plus,
  Printer,
  Files,
  Settings as SettingsIcon,
  Brain,
} from "lucide-react";
import LogoImage from "../assets/logo.png";
import LogoWhiteImage from "../assets/logo-white.png";
import QRImage from "../assets/qr.png";
import { useSettings } from "./Settings.tsx";
import { useEffect, useRef, useState } from "react";
import { ragEnabled } from "@/components/rag/utils.ts";
import { Switch } from "@/components/ui/switch";

interface SidebarProps {
  children: React.ReactNode;
  onNewChat: () => void;
}

const SidebarComponent = ({ children, onNewChat }: SidebarProps) => {
  const navigate = useNavigate();
  const { settings, setSettings } = useSettings();
  const [isDark, setIsDark] = useState<boolean>(false);

  const didInitRef = useRef<boolean>(false);

  // Инициализация темы из системных настроек/локального значения (без анимации)
  useEffect(() => {
    const stored =
      typeof window !== "undefined" ? localStorage.getItem("theme") : null;
    const prefersDark =
      typeof window !== "undefined" &&
      window.matchMedia &&
      window.matchMedia("(prefers-color-scheme: dark)").matches;
    const initialDark = stored ? stored === "dark" : prefersDark;
    setIsDark(initialDark);
    if (initialDark) {
      document.documentElement.classList.add("dark");
    } else {
      document.documentElement.classList.remove("dark");
    }
    didInitRef.current = true;
  }, []);

  // Реакция на изменения системной темы
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = (e: MediaQueryListEvent) => {
      setIsDark(e.matches);
    };
    if (media.addEventListener) {
      media.addEventListener("change", onChange);
    } else {
      // @ts-ignore: Safari
      media.addListener(onChange);
    }
    return () => {
      if (media.removeEventListener) {
        media.removeEventListener("change", onChange);
      } else {
        // @ts-ignore: Safari
        media.removeListener(onChange);
      }
    };
  }, []);

  // Применение темы при переключении (с анимацией)
  useEffect(() => {
    if (!didInitRef.current) return;
    const root = document.documentElement;
    root.classList.add("theme-animating");
    const timeout = window.setTimeout(() => {
      root.classList.remove("theme-animating");
    }, 300);
    if (isDark) {
      root.classList.add("dark");
    } else {
      root.classList.remove("dark");
    }
    // Храним выбор только при ручном переключении; в авто-режиме — очищаем
    try {
      localStorage.setItem("theme", isDark ? "dark" : "light");
    } catch {}
    return () => window.clearTimeout(timeout);
  }, [isDark]);

  const toggle = (e: React.MouseEvent) => {
    e.stopPropagation();
    setSettings({ ...settings, ...{ sideBarOpen: !settings.sideBarOpen } });
  };

  const handlePrint = (e: React.MouseEvent) => {
    e.stopPropagation();
    window.print();
  };

  const handleSettings = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigate("/demo/settings");
  };

  const handleRag = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigate("/rag");
  };

  const handleMemories = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigate("/memories");
  };

  const handleNewChat = () => {
    navigate("/");
    onNewChat();
  };

  return (
    <>
      {/* Overlay (только мобильные) */}
      <div
        onClick={toggle}
        className={[
          settings.sideBarOpen
            ? "opacity-100 pointer-events-auto"
            : "opacity-0 pointer-events-none",
          "fixed top-0 left-0 h-full w-full bg-black/50 z-50 print:hidden max-[900px]:block min-[901px]:hidden transition-opacity duration-300 ease-in-out",
        ].join(" ")}
      />

      {/* Sidebar */}
      <div
        className={[
          "fixed top-0 left-0 h-full w-[250px] p-5 backdrop-blur-2xl rounded-r-lg z-[100] transition-transform duration-300 ease-in-out print:hidden",
          "bg-card border text-card-foreground",
          settings.sideBarOpen ? "translate-x-0" : "-translate-x-[250px]",
          "max-[900px]:rounded-none",
        ].join(" ")}
      >
        <div
          className="h-10 bg-cover transition-[width] duration-300 ease-in-out mb-2 opacity-0"
          style={{
            width: settings.sideBarOpen ? 156 : 40,
            backgroundImage: `url(${isDark ? LogoImage : LogoWhiteImage})`,
          }}
        />

        <div
          className="flex items-center p-2 text-sm rounded-lg cursor-pointer hover:bg-white/10"
          onClick={handleNewChat}
        >
          <Plus size={24} className="mr-2" />
          Новый чат
        </div>

        <div
          className="flex items-center p-2 text-sm rounded-lg cursor-pointer hover:bg-white/10"
          onClick={handlePrint}
        >
          <Printer size={24} className="mr-2" />
          Печать
        </div>

        {ragEnabled() && (
          <div
            className="flex items-center p-2 text-sm rounded-lg cursor-pointer hover:bg-white/10"
            onClick={handleRag}
          >
            <Files size={24} className="mr-2" />
            База знаний
          </div>
        )}

        <div
          className="flex items-center p-2 text-sm rounded-lg cursor-pointer hover:bg-white/10"
          onClick={handleMemories}
        >
          <Brain size={24} className="mr-2" />
          Долгосрочная память
        </div>

        <div
          className="flex items-center p-2 text-sm rounded-lg cursor-pointer hover:bg-white/10"
          onClick={handleSettings}
        >
          <SettingsIcon size={24} className="mr-2" />
          Настройки демо
        </div>

        <label className="flex items-center p-2 pl-2.5 cursor-pointer text-sm">
          <Switch
            checked={settings.autoApprove ?? false}
            onCheckedChange={(checked) =>
              setSettings({ ...settings, ...{ autoApprove: checked } })
            }
          />
          <span className="ml-2">Auto Approve</span>
        </label>

        {/* Тумблер темы */}
        <label className="flex items-center p-2 pl-2.5 cursor-pointer text-sm select-none">
          <Switch
            checked={isDark}
            onCheckedChange={(checked) => {
              setIsDark(checked);
            }}
          />
          <span className="ml-2">Тёмная тема</span>
        </label>

        <div
          className="w-[150px] h-[150px] mt-2 bg-cover invert opacity-90 dark:invert-0 dark:opacity-100"
          style={{ backgroundImage: `url(${QRImage})` }}
        />
      </div>

      {/* Opener button */}
      <button
        className="fixed top-5 left-5 z-[200] bg-transparent border-0 cursor-pointer flex items-center text-card-foreground transition-[left] duration-300 ease-in-out print:[&>svg]:hidden"
        onClick={toggle}
      >
        <div
          className="h-10 bg-cover transition-[width] duration-300 ease-in-out"
          style={{
            width: settings.sideBarOpen ? 156 : 40,
            backgroundImage: `url(${isDark ? LogoImage : LogoWhiteImage})`,
          }}
        />
        <ChevronRight
          style={{
            transform: settings.sideBarOpen ? "rotate(180deg)" : "rotate(0)",
            marginLeft: "0.3rem",
          }}
        />
      </button>

      {/* Main content */}
      <div
        className={[
          "flex h-screen w-full mx-auto transition-[margin] duration-300 ease-in-out",
          "max-[900px]:max-h-[calc(100vh-75px)]",
          settings.sideBarOpen ? "min-[900px]:ml-[250px]" : "min-[900px]:ml-0",
          "print:!ml-0",
        ].join(" ")}
      >
        {children}
      </div>
    </>
  );
};

export default SidebarComponent;
