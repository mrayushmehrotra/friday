"use client";

import { Clock, type LucideIcon } from "lucide-react";

interface Props {
  CardTitle: string;
  about: string;
  origin: string;
  icon: LucideIcon;
}

const UnderConstructionCard = ({ CardTitle, about, origin, icon }: Props) => {
  const Icon = icon;

  return (
    <div className="w-full animate-fade-in">
      <div
        className="relative overflow-hidden rounded-2xl glass border border-orange-500/30 
                      bg-gradient-to-br from-orange-500/5 via-yellow-500/5 to-transparent
                      opacity-80 cursor-not-allowed hover:opacity-90 transition-opacity duration-300"
      >
        {/* Animated gradient background */}
        <div
          className="absolute inset-0 bg-gradient-to-br from-orange-500/10 to-yellow-500/10 
                        opacity-50 animate-pulse"
        />

        <div className="relative p-6 h-full flex flex-col">
          {/* Header with Icon and Status Badge */}
          <div className="flex items-start justify-between mb-4">
            <div
              className="p-3 rounded-xl bg-gradient-to-br from-orange-500/25 to-yellow-500/25 
                            border border-orange-400/20"
            >
              <Icon className="w-6 h-6 text-orange-300" />
            </div>
            <div
              className="px-3 py-1 rounded-full bg-orange-500/15 border border-orange-500/30 
                            text-xs font-medium text-orange-300 flex items-center gap-2"
            >
              <div className="w-1.5 h-1.5 bg-orange-400 rounded-full animate-pulse" />
              <span>In Development</span>
            </div>
          </div>

          {/* Title with Status */}
          <h3 className="text-lg font-bold text-white mb-2 leading-tight">
            {CardTitle}
          </h3>
          <div className="flex items-center gap-2 mb-4">
            <Clock className="w-3.5 h-3.5 text-yellow-400" />
            <span className="text-xs text-orange-300 font-medium uppercase tracking-wide">
              {origin} - Coming Soon
            </span>
          </div>

          {/* Description */}
          <div className="flex-1 mb-5">
            <p className="text-gray-400 text-sm leading-relaxed">{about}</p>
          </div>

          {/* Placeholder Button */}
          <div
            className="w-full h-11 rounded-xl bg-orange-500/10 border border-orange-500/30
                          text-orange-300 font-medium text-sm
                          flex items-center justify-center gap-2"
          >
            <Clock className="w-4 h-4" />
            <span>Coming Soon</span>
          </div>
        </div>

        {/* Bottom accent with animation */}
        <div
          className="absolute bottom-0 left-0 right-0 h-1 bg-gradient-to-r 
                        from-orange-500 via-yellow-500 to-orange-500 opacity-40
                        animate-pulse"
        />
      </div>
    </div>
  );
};

export default UnderConstructionCard;
