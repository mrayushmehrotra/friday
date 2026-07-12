"use client";
import { useEffect, useRef } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import Link from "next/link";

gsap.registerPlugin(ScrollTrigger);

export default function CreativeFooter() {
  const sectionRef = useRef<HTMLElement>(null);
  const marqueeRef = useRef<HTMLDivElement>(null);
  const shapesRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const shapes = shapesRef.current?.children;
    if (!shapes) return;

    gsap.fromTo(
      shapes,
      { y: 40, opacity: 0 },
      {
        y: 0,
        opacity: 1,
        duration: 1.2,
        stagger: 0.15,
        ease: "power3.out",
        scrollTrigger: {
          trigger: sectionRef.current,
          start: "top 85%",
        },
      },
    );

    gsap.to(shapes, {
      y: -20,
      duration: 2,
      ease: "sine.inOut",
      yoyo: true,
      repeat: -1,
      stagger: { each: 0.3, from: "random" },
    });
  }, []);

  useEffect(() => {
    const marquee = marqueeRef.current;
    if (!marquee) return;

    const ctx = gsap.context(() => {
      gsap.to(marquee, {
        x: "-50%",
        duration: 20,
        ease: "none",
        repeat: -1,
      });
    }, marquee);

    return () => ctx.revert();
  }, []);

  return (
    <section
      ref={sectionRef}
      className="relative w-full overflow-hidden bg-black pt-24 pb-0"
    >
      {/* Floating shapes */}
      <div
        ref={shapesRef}
        className="absolute inset-0 pointer-events-none overflow-hidden"
      >
        <div className="absolute top-10 left-[10%] w-20 h-20 rounded-full" style={{ background: 'rgba(0,102,204,0.05)' }} />
        <div className="absolute top-20 right-[15%] w-14 h-14 rounded-xl rotate-45" style={{ background: 'rgba(0,102,204,0.08)' }} />
        <div className="absolute bottom-32 left-[25%] w-16 h-16 rounded-2xl rotate-12" style={{ background: 'rgba(0,102,204,0.06)' }} />
        <div className="absolute bottom-40 right-[30%] w-10 h-10 rounded-full" style={{ background: 'rgba(0,102,204,0.10)' }} />
        <div className="absolute top-1/2 left-[60%] w-24 h-24" style={{ background: 'rgba(0,102,204,0.04)', borderRadius: '40% 60% 65% 35% / 45% 50% 50% 55%' }} />
      </div>

      {/* Marquee strip */}
      <div className="relative overflow-hidden border-y border-[#0066cc]/10 py-5 mb-16">
        <div ref={marqueeRef} className="flex w-max gap-12">
          {Array.from({ length: 2 }).map((_, setIdx) => (
            <div key={setIdx} className="flex gap-12 items-center">
              {[
                "Create",
                "Engage",
                "Grow",
                "Create",
                "Engage",
                "Grow",
                "Create",
                "Engage",
                "Grow",
              ].map((word, i) => (
                <span
                  key={`${setIdx}-${i}`}
                  className="text-[64px] md:text-[96px] font-semibold leading-none text-[#0066cc]/8 select-none"
                  style={{ fontFamily: "system-ui, -apple-system, sans-serif" }}
                >
                  {word}
                </span>
              ))}
            </div>
          ))}
        </div>
      </div>

      {/* Bottom bar */}
      <div className="relative z-10 max-w-[1200px] mx-auto px-6 pb-10">
        <div className="flex flex-col md:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-[#0066cc] flex items-center justify-center text-white text-sm font-semibold">
              F
            </div>
            <span className="text-sm text-white/50">Friday</span>
          </div>

          <div className="flex items-center gap-6 text-xs text-white/50">
            <Link href="#" className="hover:text-[#0066cc] transition-colors">
              Privacy
            </Link>
            <Link href="#" className="hover:text-[#0066cc] transition-colors">
              Terms
            </Link>
            <a href="mailto:hello@friday.ai" className="hover:text-[#0066cc] transition-colors">
              Contact
            </a>
          </div>

          <div className="text-xs text-white/50">
            © {new Date().getFullYear()} Friday
          </div>
        </div>
      </div>
    </section>
  );
}
