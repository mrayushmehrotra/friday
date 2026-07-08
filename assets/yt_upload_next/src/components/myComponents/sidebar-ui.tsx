"use client";
import { usePathname, useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { Home, Youtube, PanelLeftClose, PanelLeft } from "lucide-react";
import { useSidebar } from "@/contexts/SidebarContext";

const navItems = [
  { name: "Dashboard", href: "/dashboard", icon: Home },
  { name: "YouTube", href: "/dashboard/yt", icon: Youtube },
];

export function SecondNav() {
  const pathname = usePathname();
  const router = useRouter();
  const { isCollapsed, setIsCollapsed } = useSidebar();

  return (
    <aside
      className={cn(
        "fixed left-0 top-0 z-40 flex h-screen flex-col border-r",
        "bg-white/70 backdrop-blur-2xl",
        "border-gray-200/60",
        "transition-all duration-300 ease-in-out",
        isCollapsed ? "w-[72px]" : "w-[240px]",
      )}
    >
      {/* Logo area */}
      <div
        className={cn(
          "flex h-16 items-center border-b border-gray-200/40",
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
            <span className="text-sm font-semibold text-gray-800">Friday</span>
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
                  ? "bg-indigo-50 text-indigo-600 shadow-sm"
                  : "text-gray-500 hover:bg-gray-100/70 hover:text-gray-700",
              )}
            >
              <Icon
                className={cn(
                  "h-5 w-5 shrink-0",
                  isActive ? "text-indigo-600" : "text-gray-400",
                )}
              />
              {!isCollapsed && <span className="truncate">{item.name}</span>}
            </button>
          );
        })}
      </nav>

      {/* Bottom area - collapse toggle */}
      <div className="border-t border-gray-200/40 p-3">
        <button
          onClick={() => setIsCollapsed(!isCollapsed)}
          className={cn(
            "flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-gray-400 transition-all duration-200 hover:bg-gray-100/70 hover:text-gray-600",
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
      </div>
    </aside>
  );
}
