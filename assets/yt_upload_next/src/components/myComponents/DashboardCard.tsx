"use client";

import { ArrowRight, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import gsap from "gsap";
import { useEffect, useRef } from "react";

interface Props {
  CardTitle: string;
  about: string;
  link: string;
  origin: string;
  icon: LucideIcon;
}

const DashboardCard = ({ CardTitle, about, link, origin, icon }: Props) => {
  const Icon = icon;
  const cardRef = useRef<HTMLDivElement>(null);
  const iconRef = useRef<HTMLDivElement>(null);
  const glowRef = useRef<HTMLDivElement>(null);
  const shineRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const card = cardRef.current;
    if (!card) return;

    const enter = () => {
      const tl = gsap.timeline({ defaults: { ease: "power3.out" } });
      tl.to(card, { y: -6, scale: 1.015, duration: 0.35 }, 0)
        .to(glowRef.current, { opacity: 1, duration: 0.35 }, 0)
        .to(iconRef.current, { scale: 1.12, rotate: 4, duration: 0.35 }, 0)
        .to(buttonRef.current, { scale: 1.03, duration: 0.3 }, 0.1);
      if (shineRef.current) {
        gsap.fromTo(
          shineRef.current,
          { xPercent: -120, opacity: 0.5 },
          { xPercent: 120, opacity: 0, duration: 0.6, ease: "power2.out" },
        );
      }
    };

    const leave = () => {
      const tl = gsap.timeline({ defaults: { ease: "power3.out" } });
      tl.to(card, { y: 0, scale: 1, duration: 0.35 }, 0)
        .to(glowRef.current, { opacity: 0, duration: 0.3 }, 0)
        .to(iconRef.current, { scale: 1, rotate: 0, duration: 0.35 }, 0)
        .to(buttonRef.current, { scale: 1, duration: 0.3 }, 0);
    };

    card.addEventListener("mouseenter", enter);
    card.addEventListener("mouseleave", leave);
    return () => {
      card.removeEventListener("mouseenter", enter);
      card.removeEventListener("mouseleave", leave);
    };
  }, []);

  return (
    <div className="group w-full">
      <Link href={link}>
        <div
          ref={cardRef}
          className="relative glass rounded-2xl p-6 h-full flex flex-col overflow-hidden will-change-transform"
        >
          <div
            ref={glowRef}
            className="absolute inset-0 bg-gradient-to-br from-indigo-500/10 via-purple-500/8 to-transparent opacity-0"
          />

          <div
            ref={shineRef}
            className="pointer-events-none absolute top-0 left-0 h-full w-1/3 -skew-x-12 bg-gradient-to-r from-transparent via-white/30 to-transparent opacity-0"
          />

          <div className="relative z-10 flex flex-col h-full">
            <div className="flex items-start justify-between mb-4">
              <div
                ref={iconRef}
                className="p-3 rounded-xl bg-gradient-to-br from-indigo-50 to-purple-50 border border-indigo-100/50 will-change-transform"
              >
                <Icon className="w-6 h-6 text-indigo-600" />
              </div>
              <div className="px-3 py-1 rounded-full glass text-xs font-medium text-gray-500">
                {origin}
              </div>
            </div>

            <h3 className="text-lg font-bold text-gray-800 mb-3 leading-tight transition-colors duration-300 group-hover:text-transparent group-hover:bg-gradient-to-r group-hover:from-indigo-700 group-hover:to-purple-700 group-hover:bg-clip-text">
              {CardTitle}
            </h3>

            <div className="flex-1 mb-5">
              <p className="text-gray-500 text-sm leading-relaxed transition-colors duration-300 group-hover:text-gray-600">
                {about}
              </p>
            </div>

            <Button
              ref={buttonRef}
              className="w-full h-11 bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-700 hover:to-purple-700 text-white font-medium rounded-xl text-sm shadow-lg shadow-indigo-500/20 hover:shadow-indigo-500/30 transition-all duration-300 flex items-center justify-center gap-2"
            >
              <span>Launch Tool</span>
              <ArrowRight className="w-4 h-4 transition-transform group-hover:translate-x-1" />
            </Button>
          </div>
        </div>
      </Link>
    </div>
  );
};

export default DashboardCard;
