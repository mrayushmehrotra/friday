"use client";

import { motion } from "framer-motion";
import type React from "react";
import { type ReactNode, useState } from "react";

interface SectionProps {
  children: ReactNode;
  className?: string;
  title: string;
  glowColor?: string;
}

const Section: React.FC<SectionProps> = ({
  children,
  glowColor = "#555",
  className = "",
  title,
}) => {
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });
  const [isHovering, setIsHovering] = useState(false);

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement, MouseEvent>) => {
    const rect = (e.currentTarget as HTMLDivElement).getBoundingClientRect();
    setMousePos({
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
    });
  };

  const blurSize = 96;
  const blurRadius = blurSize / 2;

  return (
    <section
      style={{
        backgroundColor: "var(--bg)",
        color: "var(--text)",
      }}
      className={`relative overflow-hidden mt-4 mb-4 p-6 
              border border-zinc-300 dark:border-zinc-700 

              rounded-lg shadow-sm ${className}`}
      onMouseEnter={() => setIsHovering(true)}
      onMouseLeave={() => setIsHovering(false)}
      onMouseMove={handleMouseMove}
    >
      <h1 className="text-2xl font-bold">{title}</h1>
      {children}
      {isHovering && (
        <motion.div
          className="absolute w-24 h-24 bg-gray-500  dark:bg-gray-400/60 rounded-full blur-3xl pointer-events-none"
          style={{
            top: mousePos.y - blurRadius,
            left: mousePos.x - blurRadius,
          }}
          animate={{
            top: mousePos.y - blurRadius,
            left: mousePos.x - blurRadius,
          }}
          transition={{ type: "spring", stiffness: 300, damping: 30 }}
        />
      )}
    </section>
  );
};

export default Section;
