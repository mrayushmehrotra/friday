"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";

interface SkeletonProps {
  className?: string;
  variant?: "default" | "text" | "circular" | "rounded";
  width?: string | number;
  height?: string | number;
  lines?: number;
}

export function Skeleton({
  className,
  variant = "default",
  width,
  height,
  lines = 1,
}: SkeletonProps) {
  if (variant === "text" && lines > 1) {
    return (
      <div className={cn("space-y-2", className)}>
        {Array.from({ length: lines }).map((_, i) => (
          <div
            key={i}
            className={cn(
              "loading-shimmer rounded",
              i === lines - 1 ? "w-3/4" : "w-full",
            )}
            style={{
              height: height || "1rem",
            }}
          />
        ))}
      </div>
    );
  }

  const variantClasses = {
    default: "rounded",
    text: "rounded",
    circular: "rounded-full",
    rounded: "rounded-2xl",
  };

  return (
    <div
      className={cn("loading-shimmer", variantClasses[variant], className)}
      style={{
        width,
        height,
      }}
    />
  );
}

interface LoadingCardProps {
  className?: string;
}

export function LoadingCard({ className }: LoadingCardProps) {
  return (
    <div
      className={cn(
        "glass-strong rounded-2xl p-6 border border-white/10",
        className,
      )}
    >
      <div className="space-y-4">
        <Skeleton variant="circular" width={48} height={48} />
        <Skeleton variant="text" height={24} width="60%" />
        <Skeleton variant="text" lines={3} />
        <div className="flex gap-2 pt-2">
          <Skeleton variant="rounded" width={80} height={32} />
          <Skeleton variant="rounded" width={80} height={32} />
        </div>
      </div>
    </div>
  );
}

interface LoadingButtonProps {
  className?: string;
  children?: React.ReactNode;
}

export function LoadingButton({ className, children }: LoadingButtonProps) {
  return (
    <button
      className={cn(
        "btn-interactive px-6 py-3 rounded-xl font-medium transition-all duration-300",
        "bg-gradient-to-r from-purple-600 to-pink-600 text-white",
        "disabled:opacity-50 disabled:cursor-not-allowed",
        className,
      )}
      disabled
    >
      <div className="flex items-center gap-2">
        <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
        <span>{children || "Loading..."}</span>
      </div>
    </button>
  );
}

interface LoadingSpinnerProps {
  size?: "sm" | "md" | "lg";
  className?: string;
}

export function LoadingSpinner({
  size = "md",
  className,
}: LoadingSpinnerProps) {
  const sizeClasses = {
    sm: "w-4 h-4",
    md: "w-6 h-6",
    lg: "w-8 h-8",
  };

  return (
    <div
      className={cn(
        "border-2 border-purple-200 border-t-purple-600 rounded-full animate-spin",
        sizeClasses[size],
        className,
      )}
    />
  );
}

interface LoadingScreenProps {
  message?: string;
}

export function LoadingScreen({
  message = "Loading amazing content...",
}: LoadingScreenProps) {
  return (
    <div className="fixed inset-0 bg-black/80 backdrop-blur-md flex items-center justify-center z-[9999]">
      <div className="text-center space-y-6">
        <div className="relative">
          <div className="w-16 h-16 border-4 border-purple-200 border-t-purple-600 rounded-full animate-spin" />
          <div
            className="absolute inset-0 w-16 h-16 border-4 border-pink-200 border-b-pink-600 rounded-full animate-spin"
            style={{ animationDirection: "reverse", animationDuration: "1.5s" }}
          />
        </div>
        <div className="space-y-2">
          <p className="text-white font-medium">{message}</p>
          <div className="flex justify-center gap-1">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="w-2 h-2 bg-purple-400 rounded-full animate-float"
                style={{ animationDelay: `${i * 0.2}s` }}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

interface ProgressiveImageProps {
  src: string;
  alt: string;
  className?: string;
  fallback?: string;
}

export function ProgressiveImage({
  src,
  alt,
  className,
  fallback = "/placeholder.jpg",
}: ProgressiveImageProps) {
  const [isLoading, setIsLoading] = useState(true);
  const [hasError, setHasError] = useState(false);

  return (
    <div className={cn("relative overflow-hidden", className)}>
      {isLoading && <div className="absolute inset-0 loading-shimmer" />}
      <img
        src={hasError ? fallback : src}
        alt={alt}
        className={cn(
          "w-full h-full object-cover transition-opacity duration-300",
          isLoading ? "opacity-0" : "opacity-100",
        )}
        onLoad={() => setIsLoading(false)}
        onError={() => {
          setHasError(true);
          setIsLoading(false);
        }}
      />
    </div>
  );
}

interface LoadingDotsProps {
  className?: string;
}

export function LoadingDots({ className }: LoadingDotsProps) {
  return (
    <div className={cn("flex gap-1", className)}>
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="w-2 h-2 bg-purple-400 rounded-full animate-pulse"
          style={{ animationDelay: `${i * 0.2}s` }}
        />
      ))}
    </div>
  );
}
