"use client";

import gsap from "gsap";
import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";

export default function PageTransition({
  children,
}: {
  children: React.ReactNode;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const isAnimating = useRef(false);
  const isFirstRender = useRef(true);
  const pathname = usePathname();

  useEffect(() => {
    if (!containerRef.current || !svgRef.current) return;

    if (isFirstRender.current) {
      isFirstRender.current = false;
      gsap.set(svgRef.current, { scale: 0, opacity: 0 });
      gsap.fromTo(
        containerRef.current,
        { opacity: 0 },
        { opacity: 1, duration: 0.5, ease: "power2.out" },
      );
      return;
    }

    if (isAnimating.current) return;
    isAnimating.current = true;

    const svg = svgRef.current;

    const tl = gsap.timeline();

    // Phase 1: SVG scales UP from 0 to full (covers the screen) — 100ms
    tl.set(svg, { scale: 0, opacity: 1, transformOrigin: "50% 50%" })
      .to(svg, {
        scale: 1,
        duration: 0.1,
        ease: "power3.in",
      })
      .to(
        containerRef.current,
        { opacity: 0, duration: 0.08, ease: "power1.in" },
        "-=0.08",
      )
      // Phase 2: SVG scales DOWN from 1 to 0 (shrinks away) — 100ms
      .to(svg, {
        scale: 0,
        duration: 0.1,
        ease: "power3.out",
      })
      .to(svg, {
        opacity: 0,
        duration: 0.05,
      })
      .to(
        containerRef.current,
        { opacity: 1, duration: 0.1, ease: "power2.out" },
        "-=0.1",
      );

    tl.then(() => {
      isAnimating.current = false;
    });
  }, [pathname]);

  return (
    <div className="relative min-h-screen">
      {/* SVG overlay — scales big→small for transition */}
      <svg
        ref={svgRef}
        className="fixed inset-0 w-full h-full z-[9999] pointer-events-none"
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        style={{ scale: 0, opacity: 0 }}
      >
        <rect
          x="0"
          y="0"
          width="100"
          height="100"
          fill="black"
        />
      </svg>

      <div ref={containerRef} className="min-h-screen">
        {children}
      </div>
    </div>
  );
}
