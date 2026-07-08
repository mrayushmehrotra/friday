"use client";

import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { useEffect, useRef } from "react";

if (typeof window !== "undefined") {
  gsap.registerPlugin(ScrollTrigger);
}

interface UseGsapScrollAnimationOptions {
  trigger?: string;
  start?: string;
  end?: string;
  scrub?: boolean | number;
  markers?: boolean;
}

export function useGsapScrollAnimation<T extends HTMLElement>(
  options: UseGsapScrollAnimationOptions = {},
) {
  const ref = useRef<T>(null);

  useEffect(() => {
    if (!ref.current) return;

    const el = ref.current;

    gsap.fromTo(
      el,
      { opacity: 0, y: 60 },
      {
        opacity: 1,
        y: 0,
        duration: 1,
        ease: "power3.out",
        scrollTrigger: {
          trigger: el,
          start: options.start ?? "top 85%",
          end: options.end ?? "top 20%",
          toggleActions: "play none none reverse",
          ...(options.markers ? { markers: true } : {}),
        },
      },
    );

    return () => {
      ScrollTrigger.getAll().forEach((t) => {
        if (t.trigger === el) t.kill();
      });
    };
  }, [options.start, options.end, options.markers]);

  return ref;
}

export function useGsapStagger<T extends HTMLElement>(
  itemSelector: string,
  options: UseGsapScrollAnimationOptions = {},
) {
  const containerRef = useRef<T>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const container = containerRef.current;
    const items = container.querySelectorAll(itemSelector);

    if (items.length === 0) return;

    gsap.fromTo(
      items,
      { opacity: 0, y: 50, scale: 0.95 },
      {
        opacity: 1,
        y: 0,
        scale: 1,
        duration: 0.8,
        stagger: 0.15,
        ease: "power3.out",
        scrollTrigger: {
          trigger: container,
          start: options.start ?? "top 80%",
          toggleActions: "play none none reverse",
          ...(options.markers ? { markers: true } : {}),
        },
      },
    );

    return () => {
      ScrollTrigger.getAll().forEach((t) => {
        if (t.trigger === container) t.kill();
      });
    };
  }, [itemSelector, options.start, options.markers]);

  return containerRef;
}

export function useGsapParallax<T extends HTMLElement>(speed: number = 0.5) {
  const ref = useRef<T>(null);

  useEffect(() => {
    if (!ref.current) return;

    const el = ref.current;

    gsap.to(el, {
      yPercent: speed * 30,
      ease: "none",
      scrollTrigger: {
        trigger: el,
        start: "top bottom",
        end: "bottom top",
        scrub: true,
      },
    });

    return () => {
      ScrollTrigger.getAll().forEach((t) => {
        if (t.trigger === el) t.kill();
      });
    };
  }, [speed]);

  return ref;
}
