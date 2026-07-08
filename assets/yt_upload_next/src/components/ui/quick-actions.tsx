"use client";
import { Bookmark, History, Plus, Zap } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

export const QuickActions = () => {
  const [isOpen, setIsOpen] = useState(false);

  const actions = [
    {
      icon: Zap,
      label: "Quick Title",
      href: "/dashboard/getTitle",
      color: "bg-yellow-500",
    },
    {
      icon: Plus,
      label: "New Project",
      href: "/dashboard",
      color: "bg-green-500",
    },
    { icon: History, label: "Recent", href: "#", color: "bg-blue-500" },
    { icon: Bookmark, label: "Saved", href: "#", color: "bg-purple-500" },
  ];

  return (
    <div className="fixed bottom-6 right-6 z-40">
      {/* Action Buttons */}
      {isOpen && (
        <div className="absolute bottom-16 right-0 space-y-3 animate-fade-in">
          {actions.map((action, index) => {
            const Icon = action.icon;
            return (
              <Link
                key={index}
                href={action.href}
                className={`flex items-center gap-3 ${action.color} text-white px-4 py-3 
                          rounded-2xl shadow-lg hover:scale-105 transition-all duration-300 
                          glass border border-white/20`}
                style={{ animationDelay: `${index * 100}ms` }}
              >
                <Icon className="w-5 h-5" />
                <span className="text-sm font-medium whitespace-nowrap">
                  {action.label}
                </span>
              </Link>
            );
          })}
        </div>
      )}

      {/* Main FAB */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={`w-14 h-14 bg-gradient-to-r from-purple-600 to-pink-600 rounded-full 
                   shadow-2xl hover:shadow-purple-500/25 flex items-center justify-center 
                   transition-all duration-300 transform hover:scale-110 ${
                     isOpen ? "rotate-45" : ""
                   }`}
      >
        <Plus className="w-6 h-6 text-white" />
      </button>
    </div>
  );
};
