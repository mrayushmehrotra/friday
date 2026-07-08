"use client";

import {
  cloneElement,
  type ReactNode,
  useEffect,
  useRef,
  useState,
} from "react";
import { cn } from "@/lib/utils";

interface TooltipProps {
  content: ReactNode;
  children: React.ReactElement;
  position?: "top" | "bottom" | "left" | "right";
  delay?: number;
  className?: string;
}

export function Tooltip({
  content,
  children,
  position = "top",
  delay = 300,
  className,
}: TooltipProps) {
  const [isVisible, setIsVisible] = useState(false);
  const [coords, setCoords] = useState({ x: 0, y: 0 });
  const timeoutRef = useRef<NodeJS.Timeout>();
  const triggerRef = useRef<HTMLDivElement>(null);

  const showTooltip = () => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    timeoutRef.current = setTimeout(() => setIsVisible(true), delay);
  };

  const hideTooltip = () => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    setIsVisible(false);
  };

  const updatePosition = () => {
    if (!triggerRef.current) return;

    const rect = triggerRef.current.getBoundingClientRect();
    const tooltipHeight = 40; // Approximate height
    const tooltipWidth = 200; // Approximate width

    let x = 0;
    let y = 0;

    switch (position) {
      case "top":
        x = rect.left + rect.width / 2 - tooltipWidth / 2;
        y = rect.top - tooltipHeight - 8;
        break;
      case "bottom":
        x = rect.left + rect.width / 2 - tooltipWidth / 2;
        y = rect.bottom + 8;
        break;
      case "left":
        x = rect.left - tooltipWidth - 8;
        y = rect.top + rect.height / 2 - tooltipHeight / 2;
        break;
      case "right":
        x = rect.right + 8;
        y = rect.top + rect.height / 2 - tooltipHeight / 2;
        break;
    }

    // Keep tooltip within viewport
    x = Math.max(8, Math.min(x, window.innerWidth - tooltipWidth - 8));
    y = Math.max(8, Math.min(y, window.innerHeight - tooltipHeight - 8));

    setCoords({ x, y });
  };

  useEffect(() => {
    if (isVisible) {
      updatePosition();
      window.addEventListener("scroll", updatePosition);
      window.addEventListener("resize", updatePosition);
      return () => {
        window.removeEventListener("scroll", updatePosition);
        window.removeEventListener("resize", updatePosition);
      };
    }
  }, [isVisible, position]);

  return (
    <>
      <div
        ref={triggerRef}
        onMouseEnter={showTooltip}
        onMouseLeave={hideTooltip}
        className="inline-block"
      >
        {children}
      </div>

      {isVisible && (
        <div
          className={cn(
            "fixed z-[9999] glass-strong rounded-lg px-3 py-2 text-sm text-white",
            "pointer-events-none transition-all duration-200 animate-fade-in",
            "max-w-xs text-center",
            className,
          )}
          style={{
            left: `${coords.x}px`,
            top: `${coords.y}px`,
          }}
        >
          {content}
          {/* Arrow */}
          <div
            className={cn(
              "absolute w-2 h-2 bg-purple-500/20 backdrop-blur-md border border-white/10",
              "transform rotate-45",
              {
                "bottom-[-5px] left-1/2 -translate-x-1/2 border-b-0 border-r-0":
                  position === "top",
                "top-[-5px] left-1/2 -translate-x-1/2 border-t-0 border-l-0":
                  position === "bottom",
                "right-[-5px] top-1/2 -translate-y-1/2 border-r-0 border-t-0":
                  position === "left",
                "left-[-5px] top-1/2 -translate-y-1/2 border-l-0 border-b-0":
                  position === "right",
              },
            )}
          />
        </div>
      )}
    </>
  );
}

interface HoverCardProps {
  children: ReactNode;
  content: ReactNode;
  trigger?: "hover" | "click";
  width?: "sm" | "md" | "lg" | "xl";
  className?: string;
}

export function HoverCard({
  children,
  content,
  trigger = "hover",
  width = "md",
  className,
}: HoverCardProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [coords, setCoords] = useState({ x: 0, y: 0 });
  const triggerRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);

  const widthClasses = {
    sm: "w-64",
    md: "w-80",
    lg: "w-96",
    xl: "w-[28rem]",
  };

  const showCard = () => {
    if (!triggerRef.current) return;

    const rect = triggerRef.current.getBoundingClientRect();
    const cardWidth = 320; // Approximate width for md
    const cardHeight = 200; // Approximate height

    // Position below the trigger, aligned to the left
    let x = rect.left;
    const y = rect.bottom + 8;

    // Keep card within viewport
    if (x + cardWidth > window.innerWidth) {
      x = window.innerWidth - cardWidth - 16;
    }
    if (x < 16) x = 16;

    setCoords({ x, y });
    setIsOpen(true);
  };

  const hideCard = () => {
    setIsOpen(false);
  };

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (isOpen) {
      hideCard();
    } else {
      showCard();
    }
  };

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        cardRef.current &&
        !cardRef.current.contains(event.target as Node) &&
        triggerRef.current &&
        !triggerRef.current.contains(event.target as Node)
      ) {
        hideCard();
      }
    };

    if (isOpen && trigger === "click") {
      document.addEventListener("mousedown", handleClickOutside);
      return () =>
        document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [isOpen, trigger]);

  const triggerProps =
    trigger === "hover"
      ? { onMouseEnter: showCard, onMouseLeave: hideCard }
      : { onClick: handleClick };

  return (
    <div className="relative inline-block">
      <div ref={triggerRef} {...triggerProps} className="cursor-pointer">
        {children}
      </div>

      {isOpen && (
        <div
          ref={cardRef}
          className={cn(
            "fixed z-[9999] glass-strong rounded-2xl border border-white/10",
            "p-6 shadow-2xl animate-fade-in transition-all duration-200",
            widthClasses[width],
            className,
          )}
          style={{
            left: `${coords.x}px`,
            top: `${coords.y}px`,
          }}
          onMouseEnter={trigger === "hover" ? showCard : undefined}
          onMouseLeave={trigger === "hover" ? hideCard : undefined}
        >
          {content}
        </div>
      )}
    </div>
  );
}

interface PopoverProps {
  trigger: ReactNode;
  content: ReactNode;
  isOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  width?: "sm" | "md" | "lg" | "xl";
  className?: string;
}

export function Popover({
  trigger,
  content,
  isOpen,
  onOpenChange,
  width = "md",
  className,
}: PopoverProps) {
  const [internalOpen, setInternalOpen] = useState(false);
  const isControlled = isOpen !== undefined;
  const open = isControlled ? isOpen : internalOpen;
  const setOpen = isControlled ? onOpenChange! : setInternalOpen;

  const [coords, setCoords] = useState({ x: 0, y: 0 });
  const triggerRef = useRef<HTMLDivElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);

  const widthClasses = {
    sm: "w-64",
    md: "w-80",
    lg: "w-96",
    xl: "w-[28rem]",
  };

  const showPopover = () => {
    if (!triggerRef.current) return;

    const rect = triggerRef.current.getBoundingClientRect();
    const popoverWidth = 320; // Approximate width for md

    // Position below the trigger, centered
    let x = rect.left + rect.width / 2 - popoverWidth / 2;
    const y = rect.bottom + 8;

    // Keep popover within viewport
    if (x < 16) x = 16;
    if (x + popoverWidth > window.innerWidth) {
      x = window.innerWidth - popoverWidth - 16;
    }

    setCoords({ x, y });
    setOpen(true);
  };

  const hidePopover = () => {
    setOpen(false);
  };

  const handleTriggerClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (open) {
      hidePopover();
    } else {
      showPopover();
    }
  };

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        popoverRef.current &&
        !popoverRef.current.contains(event.target as Node) &&
        triggerRef.current &&
        !triggerRef.current.contains(event.target as Node)
      ) {
        hidePopover();
      }
    };

    if (open) {
      document.addEventListener("mousedown", handleClickOutside);
      return () =>
        document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [open]);

  return (
    <div className="relative inline-block">
      <div
        ref={triggerRef}
        onClick={handleTriggerClick}
        className="cursor-pointer"
      >
        {trigger}
      </div>

      {open && (
        <div
          ref={popoverRef}
          className={cn(
            "fixed z-[9999] glass-strong rounded-2xl border border-white/10",
            "p-6 shadow-2xl animate-fade-in transition-all duration-200",
            widthClasses[width],
            className,
          )}
          style={{
            left: `${coords.x}px`,
            top: `${coords.y}px`,
          }}
        >
          {content}
        </div>
      )}
    </div>
  );
}

// Interactive Card Component
interface InteractiveCardProps {
  children: ReactNode;
  className?: string;
  hover?: boolean;
  tilt?: boolean;
  glow?: boolean;
  onClick?: () => void;
}

export function InteractiveCard({
  children,
  className,
  hover = true,
  tilt = false,
  glow = false,
  onClick,
}: InteractiveCardProps) {
  const [isHovered, setIsHovered] = useState(false);
  const [tiltStyle, setTiltStyle] = useState({});

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!tilt) return;

    const rect = e.currentTarget.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    const y = (e.clientY - rect.top) / rect.height;

    const rotateX = (y - 0.5) * -10;
    const rotateY = (x - 0.5) * 10;

    setTiltStyle({
      transform: `perspective(1000px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale3d(1.05, 1.05, 1.05)`,
    });
  };

  const handleMouseLeave = () => {
    setIsHovered(false);
    setTiltStyle({});
  };

  const cardClasses = cn(
    "glass-strong rounded-2xl border border-white/10 p-6 transition-all duration-300",
    hover && "hover-lift cursor-pointer",
    glow && "hover:shadow-2xl hover:shadow-purple-500/20",
    isHovered && "border-purple-500/30",
    className,
  );

  return (
    <div
      className={cardClasses}
      style={tiltStyle}
      onMouseEnter={() => setIsHovered(true)}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
      onClick={onClick}
    >
      {children}

      {/* Glow effect */}
      {glow && isHovered && (
        <div className="absolute inset-0 rounded-2xl bg-gradient-to-r from-purple-500/10 via-pink-500/10 to-indigo-500/10 animate-pulse-slow pointer-events-none" />
      )}
    </div>
  );
}
