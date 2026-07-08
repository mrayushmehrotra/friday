"use client";
import { CheckCircle } from "lucide-react";
import { useEffect, useState } from "react";

interface SuccessAnimationProps {
  show: boolean;
  message: string;
  onComplete?: () => void;
}

export const SuccessAnimation = ({
  show,
  message,
  onComplete,
}: SuccessAnimationProps) => {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (show) {
      setVisible(true);
      const timer = setTimeout(() => {
        setVisible(false);
        onComplete?.();
      }, 3000);
      return () => clearTimeout(timer);
    }
  }, [show, onComplete]);

  if (!visible) return null;

  return (
    <div className="fixed top-4 right-4 z-50 animate-fade-in">
      <div className="glass rounded-2xl p-4 border border-green-500/30 bg-green-500/10">
        <div className="flex items-center gap-3">
          <CheckCircle className="w-6 h-6 text-green-400 animate-pulse" />
          <span className="text-white font-medium">{message}</span>
        </div>
      </div>
    </div>
  );
};
