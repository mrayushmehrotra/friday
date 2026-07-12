"use client";

import { Sparkles, TrendingUp, Youtube } from "lucide-react";
import { memo, useEffect, useRef, useState } from "react";
import DashboardCard from "@/components/myComponents/DashboardCard";
import { Skeleton } from "@/components/ui/skeleton";
import { SmartTooltip } from "@/components/ui/smart-tooltip";
import gsap from "gsap";

const Page = () => {
  const [loading, setLoading] = useState(true);
  const rootRef = useRef<HTMLDivElement>(null);
  const badgeRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const descRef = useRef<HTMLParagraphElement>(null);
  const statsRef = useRef<HTMLDivElement>(null);
  const sectionRef = useRef<HTMLElement>(null);
  const orb1Ref = useRef<HTMLDivElement>(null);
  const orb2Ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const t = setTimeout(() => setLoading(false), 1200);
    return () => clearTimeout(t);
  }, []);

  useEffect(() => {
    const ctx = gsap.context(() => {
      const tl = gsap.timeline({ defaults: { ease: "power3.out" } });
      tl.from(badgeRef.current, { y: -20, opacity: 0, duration: 0.6 })
        .from(
          headingRef.current?.children || [],
          { y: 40, opacity: 0, duration: 0.8, stagger: 0.12 },
          "-=0.2",
        )
        .from(descRef.current, { y: 20, opacity: 0, duration: 0.6 }, "-=0.4")
        .from(
          statsRef.current?.children || [],
          { y: 16, opacity: 0, scale: 0.9, duration: 0.5, stagger: 0.1 },
          "-=0.3",
        );

      if (!loading && sectionRef.current) {
        gsap.from(sectionRef.current.querySelectorAll("[data-card]"), {
          y: 50,
          opacity: 0,
          scale: 0.95,
          duration: 0.7,
          stagger: 0.15,
          ease: "power3.out",
          delay: 0.1,
        });
      }

      if (orb1Ref.current) {
        gsap.to(orb1Ref.current, {
          yPercent: 20,
          xPercent: 10,
          duration: 8,
          repeat: -1,
          yoyo: true,
          ease: "sine.inOut",
        });
      }
      if (orb2Ref.current) {
        gsap.to(orb2Ref.current, {
          yPercent: -25,
          xPercent: -15,
          duration: 10,
          repeat: -1,
          yoyo: true,
          ease: "sine.inOut",
        });
      }
    }, rootRef);

    return () => ctx.revert();
  }, [loading]);

  const Data = [
    {
      title: {
        origin: "YouTube Manager",
        main: "YouTube Upload & Analytics",
        description:
          "Connect your YouTube channel to upload videos, manage metadata, and view analytics.",
      },
      goto: "/dashboard/yt",
      icon: Youtube,
    },
  ];

  return (
    <div
      ref={rootRef}
      className="relative min-h-screen overflow-hidden bg-black"
    >
      <div
        ref={orb1Ref}
        className="pointer-events-none absolute -top-32 -left-24 w-96 h-96 rounded-full bg-indigo-400/20 blur-[120px]"
      />
      <div
        ref={orb2Ref}
        className="pointer-events-none absolute bottom-0 -right-24 w-[28rem] h-[28rem] rounded-full bg-purple-400/15 blur-[130px]"
      />

      <header className="relative pt-8 pb-6 px-4 sm:px-6 lg:px-8">
        <div className="max-w-7xl mx-auto text-center">
          <div className="flex justify-center mb-6">
            <div
              ref={badgeRef}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-full glass text-sm font-medium text-gray-600"
              role="status"
            >
              <Sparkles className="w-4 h-4 text-indigo-500" aria-hidden="true" />
              <span className="bg-gradient-to-r from-indigo-600 to-purple-600 bg-clip-text text-transparent font-semibold">
                Dashboard
              </span>
            </div>
          </div>

          <h1
            ref={headingRef}
            className="text-3xl sm:text-4xl lg:text-5xl font-bold mb-4 leading-tight"
          >
            <span className="text-gray-800">Create Content That</span>
            <br />
            <span className="bg-gradient-to-r from-indigo-600 via-purple-600 to-pink-600 bg-clip-text text-transparent">
              Converts & Engages
            </span>
          </h1>

          <p
            ref={descRef}
            className="text-base sm:text-lg text-gray-500 max-w-2xl mx-auto mb-8"
          >
            Upload and manage your YouTube videos with ease.
          </p>

          <div
            ref={statsRef}
            className="flex flex-wrap justify-center gap-3 sm:gap-4"
            role="list"
          >
            <div
              className="flex items-center gap-2 px-4 py-2 glass rounded-full text-sm text-gray-600"
              role="listitem"
            >
              <TrendingUp className="w-4 h-4 text-emerald-500" aria-hidden="true" />
              <span>95% Engagement Boost</span>
            </div>
            <div
              className="flex items-center gap-2 px-4 py-2 glass rounded-full text-sm text-gray-600"
              role="listitem"
            >
              <Sparkles className="w-4 h-4 text-indigo-500" aria-hidden="true" />
              <span>AI-Powered Optimization</span>
            </div>
          </div>
        </div>
      </header>

      <main className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pb-16">
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
          <section
            ref={sectionRef}
            className="lg:col-span-3"
            aria-labelledby="content-tools-heading"
          >
            <div className="mb-6">
              <h2 id="content-tools-heading" className="text-2xl font-bold text-gray-800 mb-2">
                Content Tools
              </h2>
              <p className="text-sm text-gray-500">
                Select a tool to start creating optimized content
              </p>
            </div>

            <div
              className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 sm:gap-6"
              data-tour="dashboard-cards"
              role="list"
            >
              {loading
                ? Data.map((_, index) => (
                    <div key={index} className="w-full" data-card>
                      <div className="glass rounded-2xl p-6 animate-pulse">
                        <Skeleton className="h-4 w-28 mb-4 bg-black/5 rounded-lg" />
                        <Skeleton className="h-7 w-full mb-3 bg-black/5 rounded-lg" />
                        <Skeleton className="h-20 w-full mb-6 bg-black/5 rounded-lg" />
                        <Skeleton className="h-11 w-36 bg-black/5 rounded-xl" />
                      </div>
                    </div>
                  ))
                : Data.map((item, key) => (
                    <div key={key} data-card>
                      <SmartTooltip content={`Open ${item.title.origin}`}>
                        <DashboardCard
                          origin={item.title.origin}
                          about={item.title.description}
                          CardTitle={item.title.main}
                          link={item.goto}
                          icon={item.icon}
                        />
                      </SmartTooltip>
                    </div>
                  ))}
            </div>
          </section>

          <aside className="lg:col-span-1 space-y-6" aria-label="Dashboard sidebar" />
        </div>
      </main>
    </div>
  );
};

export default memo(Page);
