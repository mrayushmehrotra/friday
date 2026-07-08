"use client";

import { motion } from "framer-motion";
import { AlertTriangle, Clock, Zap } from "lucide-react";
import { useEffect, useState } from "react";

interface LimitExceededBannerProps {
  actionName: string;
  used: number;
  limit: number;
}

export function LimitExceededBanner({
  actionName,
  used,
  limit,
}: LimitExceededBannerProps) {
  const [timeLeft, setTimeLeft] = useState("");

  useEffect(() => {
    const updateTimeLeft = () => {
      const now = new Date();
      const tomorrow = new Date(now);
      tomorrow.setDate(tomorrow.getDate() + 1);
      tomorrow.setHours(0, 0, 0, 0);

      const diff = tomorrow.getTime() - now.getTime();
      const hours = Math.floor(diff / (1000 * 60 * 60));
      const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));

      setTimeLeft(`${hours}h ${minutes}m`);
    };

    updateTimeLeft();
    const timer = setInterval(updateTimeLeft, 60000);

    return () => clearInterval(timer);
  }, []);

  return (
    <motion.div
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-2xl p-6 bg-gradient-to-r from-red-500/10 via-orange-500/10 to-red-500/10 
                border border-red-500/30 mb-6"
    >
      <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4">
        <div className="p-3 rounded-xl bg-red-500/20">
          <AlertTriangle className="w-6 h-6 text-red-400" />
        </div>

        <div className="flex-1">
          <h3 className="text-lg font-bold text-white mb-1">
            Daily Limit Reached
          </h3>
          <p className="text-gray-300 text-sm">
            You've used all <strong>{limit}</strong> {actionName} for today
            ({used}/{limit} used). Your limit will reset in{" "}
            <span className="text-yellow-400 font-medium">{timeLeft}</span>.
          </p>
        </div>

        <div className="flex gap-3 w-full sm:w-auto">
          <div className="flex items-center gap-2 px-4 py-2 rounded-xl bg-white/5 border border-white/10">
            <Clock className="w-4 h-4 text-yellow-400" />
            <span className="text-sm text-gray-300">{timeLeft}</span>
          </div>
        </div>
      </div>
    </motion.div>
  );
}

interface UsageWarningProps {
  used: number;
  limit: number;
  remaining: number;
}

export function UsageWarning({ used, limit, remaining }: UsageWarningProps) {
  if (remaining > 2) return null;

  const isLastOne = remaining === 1;

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium
        ${isLastOne
          ? "bg-red-500/20 text-red-300 border border-red-500/30"
          : "bg-yellow-500/20 text-yellow-300 border border-yellow-500/30"
        }`}
    >
      <Zap className="w-3 h-3" />
      {isLastOne
        ? `Last generation! (${used}/${limit})`
        : `${remaining} left today (${used}/${limit})`
      }
    </motion.div>
  );
}

export function LimitBadge() {
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium
                   bg-red-500/20 text-red-300 border border-red-500/30">
      <AlertTriangle className="w-3 h-3" />
      Limit Reached
    </span>
  );
}
