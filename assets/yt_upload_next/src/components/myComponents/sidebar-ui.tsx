"use client";
import { usePathname, useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { Home, Youtube, PanelLeftClose, PanelLeft, LogOut, BarChart3 } from "lucide-react";
import { useSidebar } from "@/contexts/SidebarContext";

const navItems = [
  { name: "Dashboard", href: "/dashboard", icon: Home },
  { name: "YouTube", href: "/dashboard/yt", icon: Youtube },
  { name: "Stock Research", href: "/dashboard/stock-research", icon: BarChart3 },
];

export function SecondNav() {
  const pathname = usePathname();
  const router = useRouter();
  const { isCollapsed, setIsCollapsed } = useSidebar();

  const handleSignOut = async () => {
    localStorage.removeItem("youtube_access_token");
    localStorage.removeItem("user_id");
    document.cookie =
      "youtube_access_token=; path=/; max-age=0; samesite=lax";
    document.cookie = "user_id=; path=/; max-age=0; samesite=lax";
    router.push("/sign-in");
  };

  return (
    <aside
      className={cn(
        "fixed left-0 top-0 z-40 flex h-screen flex-col border-r",
        "bg-[#111]/90 backdrop-blur-2xl",
        "border-white/10",
        "transition-all duration-300 ease-in-out",
        isCollapsed ? "w-[72px]" : "w-[240px]",
      )}
    >
      {/* Logo area */}
      <div
        className={cn(
          "flex h-16 items-center border-b border-white/10",
          isCollapsed ? "justify-center px-3" : "px-5",
        )}
      >
        {isCollapsed ? (
          <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-purple-500 text-xs font-bold text-white shadow-sm">
            F
          </div>
        ) : (
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-purple-500 text-xs font-bold text-white shadow-sm">
              F
            </div>
            <span className="text-sm font-semibold text-white">Friday</span>
          </div>
        )}
      </div>

      {/* Nav items */}
      <nav className="flex-1 space-y-1 px-3 py-4">
        {navItems.map((item) => {
          const isActive = pathname === item.href;
          const Icon = item.icon;
          return (
            <button
              key={item.href}
              onClick={() => router.push(item.href)}
              className={cn(
                "flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-all duration-200",
                isCollapsed ? "justify-center px-2" : "",
                isActive
                  ? "bg-indigo-500/20 text-indigo-400 shadow-sm"
                  : "text-white/50 hover:bg-white/5 hover:text-white",
              )}
            >
              <Icon
                className={cn(
                  "h-5 w-5 shrink-0",
                  isActive ? "text-indigo-400" : "text-white/40",
                )}
              />
              {!isCollapsed && <span className="truncate">{item.name}</span>}
            </button>
          );
        })}
      </nav>

      {/* Bottom area */}
      <div className="border-t border-white/10 p-3 space-y-1">
        <button
          onClick={() => setIsCollapsed(!isCollapsed)}
          className={cn(
            "flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-white/40 transition-all duration-200 hover:bg-white/5 hover:text-white",
            isCollapsed ? "justify-center px-2" : "",
          )}
        >
          {isCollapsed ? (
            <PanelLeft className="h-5 w-5" />
          ) : (
            <>
              <PanelLeftClose className="h-5 w-5" />
              <span>Collapse</span>
            </>
          )}
        </button>
        <button
          onClick={handleSignOut}
          className={cn(
            "flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-white/40 transition-all duration-200 hover:bg-red-500/10 hover:text-red-400",
            isCollapsed ? "justify-center px-2" : "",
          )}
        >
          <LogOut className="h-5 w-5 shrink-0" />
          {!isCollapsed && <span>Sign Out</span>}
        </button>
      </div>
    </aside>
  );
}
