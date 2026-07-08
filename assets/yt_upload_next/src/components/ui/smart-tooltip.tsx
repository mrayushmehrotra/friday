"use client";
import { useState } from "react";

interface SmartTooltipProps {
  content: string;
  children: React.ReactNode;
  delay?: number;
}

export const SmartTooltip = ({
  content,
  children,
  delay = 500,
}: SmartTooltipProps) => {
  const [show, setShow] = useState(false);
  const [timer, setTimer] = useState<NodeJS.Timeout | null>(null);

  const handleMouseEnter = () => {
    const newTimer = setTimeout(() => setShow(true), delay);
    setTimer(newTimer);
  };

  const handleMouseLeave = () => {
    if (timer) clearTimeout(timer);
    setShow(false);
  };

  return (
    <div
      className="relative inline-block"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      {children}
      {show && (
        <div
          className="absolute bottom-full left-1/2 transform -translate-x-1/2 mb-2 px-3 py-2 
                       glass rounded-lg text-sm text-white whitespace-nowrap z-50 animate-fade-in"
        >
          {content}
          <div
            className="absolute top-full left-1/2 transform -translate-x-1/2 border-4 
                         border-transparent border-t-white/20"
          />
        </div>
      )}
    </div>
  );
};
