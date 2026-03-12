import React from "react";
import { ArrowLeft } from "lucide-react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/components/providers/auth.tsx";
import AdminUsersTab from "./users";
import AdminGroupsTab from "./groups";

type AdminTab = "users" | "groups";

const resolveActiveTab = (pathname: string): AdminTab => {
  if (pathname.includes("/admin-panel/groups")) {
    return "groups";
  }
  return "users";
};

const AdminPanelPage: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { user } = useAuth();

  if (!user?.is_superuser) {
    return <Navigate to="/" replace />;
  }

  const activeTab = resolveActiveTab(location.pathname);

  const tabs: { id: AdminTab; label: string; url: string }[] = [
    { id: "users", label: "Пользователи", url: "/admin-panel/users" },
    { id: "groups", label: "Группы", url: "/admin-panel/groups" },
  ];

  return (
    <div className="w-full flex lg:p-5 p-0 lg:mt-0 bg-card">
      <div className="flex flex-col max-w-[1000px] mx-auto h-full flex-1 overflow-hidden print:overflow-visible print:shadow-none">
        <div className="flex items-center gap-4 p-6 border-b border-border">
          <h1 className="text-xl font-semibold">Админ панель</h1>
        </div>

        <div className="flex gap-2 p-4 border-b border-border">
          {tabs.map((tab) => (
            <Badge
              key={tab.id}
              variant={activeTab === tab.id ? "default" : "outline"}
              className="cursor-pointer px-4 py-1.5 text-sm"
              onClick={() => navigate(tab.url)}
            >
              {tab.label}
            </Badge>
          ))}
        </div>

        <div className="flex-1 overflow-auto p-6 flex flex-col">
          {activeTab === "users" ? <AdminUsersTab /> : <AdminGroupsTab />}
        </div>
      </div>
    </div>
  );
};

export default AdminPanelPage;
