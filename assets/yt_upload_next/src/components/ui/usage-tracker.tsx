"use client";
import { Clock, Zap } from "lucide-react";
import { useEffect, useState } from "react";

export const UsageTracker = () => {
  const [usage, _setUsage] = useState({ used: 3, limit: 10 });
  const [timeLeft, setTimeLeft] = useState("23:45:12");

  useEffect(() => {
    const timer = setInterval(() => {
      const now = new Date();
      const tomorrow = new Date(now);
      tomorrow.setDate(tomorrow.getDate() + 1);
      tomorrow.setHours(0, 0, 0, 0);

      const diff = tomorrow.getTime() - now.getTime();
      const hours = Math.floor(diff / (1000 * 60 * 60));
      const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
      const seconds = Math.floor((diff % (1000 * 60)) / 1000);

      setTimeLeft(
        `${hours.toString().padStart(2, "0")}:${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`,
      );
    }, 1000);

    return () => clearInterval(timer);
  }, []);

  const percentage = (usage.used / usage.limit) * 100;

  return (
    <div className="glass rounded-2xl p-4 border border-white/10 max-w-sm">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Zap className="w-4 h-4 text-yellow-400" />
          <span className="text-sm font-medium text-white">Daily Usage</span>
        </div>
        <span className="text-xs text-gray-400">
          {usage.used}/{usage.limit}
        </span>
      </div>

      <div className="w-full bg-gray-700 rounded-full h-2 mb-3">
        <div
          className="bg-gradient-to-r from-green-400 to-yellow-400 h-2 rounded-full transition-all duration-500"
          style={{ width: `${percentage}%` }}
        />
      </div>

      <div className="flex items-center gap-2 text-xs text-gray-400">
        <Clock className="w-3 h-3" />
        <span>Resets in {timeLeft}</span>
      </div>
    </div>
  );
};
