"use client";
import { usePathname, useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { Home, Youtube, PanelLeftClose, PanelLeft, LogOut, BarChart3, ExternalLink } from "lucide-react";
import { useSidebar } from "@/contexts/SidebarContext";

const XIcon = ({ className }: { className?: string }) => (
  <svg viewBox="0 0 24 24" className={className} fill="currentColor">
    <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
  </svg>
);

const LinkedInIcon = ({ className }: { className?: string }) => (
  <svg viewBox="0 0 24 24" className={className} fill="currentColor">
    <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z" />
  </svg>
);

const navItems = [
  { name: "Dashboard", href: "/dashboard", icon: Home },
  { name: "YouTube", href: "/dashboard/yt", icon: Youtube },
  { name: "Stock Research", href: "/dashboard/stock-research", icon: BarChart3 },
  { name: "X (Twitter)", href: "/dashboard/x", icon: XIcon },
  { name: "LinkedIn", href: "https://linkedin.com", icon: LinkedInIcon, external: true },
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
              onClick={() => item.external ? window.open(item.href, '_blank', 'noopener,noreferrer') : router.push(item.href)}
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
