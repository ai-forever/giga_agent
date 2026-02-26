import React from "react";
import { useNavigate } from "react-router-dom";
import {
  ChevronRight,
  Plus,
  Printer,
  Files,
  Settings as SettingsIcon,
  Brain,
  Sun,
  Moon,
  Monitor,
  User,
  LogOut,
} from "lucide-react";
import LogoImage from "../assets/logo.png";
import LogoWhiteImage from "../assets/logo-white.png";
import QRImage from "../assets/qr.png";
import { useSettings } from "./Settings.tsx";
import { ragEnabled } from "@/config.ts";
import { Switch } from "@/components/ui/switch";
import { useTheme, ThemeMode } from "@/components/providers/theme.tsx";
import { useAuth } from "@/components/providers/auth.tsx";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

interface SidebarProps {
  children: React.ReactNode;
  onNewChat: () => void;
}

const SidebarComponent = ({ children, onNewChat }: SidebarProps) => {
  const navigate = useNavigate();
  const { settings, setSettings } = useSettings();
  const { isDark } = useTheme();
  const { user, logout } = useAuth();

  // Получаем отображаемое имя пользователя (email обрезается)
  const displayName = user?.email
    ? user.email.length > 20
      ? user.email.slice(0, 17) + "..."
      : user.email
    : "";

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  const handleProfile = () => {
    // TODO: Реализовать страницу профиля
    navigate("/profile");
  };

  const toggle = (e: React.MouseEvent) => {
    e.stopPropagation();
    setSettings({ ...settings, ...{ sideBarOpen: !settings.sideBarOpen } });
  };

  const handlePrint = (e: React.MouseEvent) => {
    e.stopPropagation();
    window.print();
  };

  const handleDemo = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigate("/demo/settings");
  };

  const handleSettings = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigate("/settings");
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
          "fixed top-0 left-0 h-full w-full bg-black/50 z-10 print:hidden max-[900px]:block min-[901px]:hidden transition-opacity duration-300 ease-in-out",
        ].join(" ")}
      />

      {/* Sidebar */}
      <div
        className={[
          "fixed top-0 left-0 h-full w-[250px] p-5 backdrop-blur-2xl rounded-r-lg z-[10] transition-transform duration-300 ease-in-out print:hidden",
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

        {/* <div
          className="flex items-center p-2 text-sm rounded-lg cursor-pointer hover:bg-white/10"
          onClick={handleDemo}
        >
          <SettingsIcon size={24} className="mr-2" />
          Настройки демо
        </div> */}
        <div
          className="flex items-center p-2 text-sm rounded-lg cursor-pointer hover:bg-white/10"
          onClick={handleSettings}
        >
          <SettingsIcon size={24} className="mr-2" />
          Настройки
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

        <div
          className="w-[150px] h-[150px] mt-2 bg-cover invert opacity-90 dark:invert-0 dark:opacity-100"
          style={{ backgroundImage: `url(${QRImage})` }}
        />

        {/* Меню пользователя */}
        {user && (
          <div className="absolute bottom-5 left-5 right-5">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <div className="flex items-center p-2 text-sm rounded-lg cursor-pointer hover:bg-accent/50 border border-border">
                  <div className="flex items-center justify-center w-8 h-8 rounded-full bg-primary/10 mr-2">
                    <User size={18} className="text-primary" />
                  </div>
                  <span className="truncate">{displayName}</span>
                </div>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                align="start"
                side="top"
                className="w-[200px]"
              >
                {/* <DropdownMenuItem onSelect={handleProfile}>
                  <User className="mr-2 h-4 w-4" />
                  Профиль
                </DropdownMenuItem> */}
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={handleLogout}>
                  <LogOut className="mr-2 h-4 w-4 text-destructive" />
                  Выход
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        )}
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
