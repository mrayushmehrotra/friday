"use client";
import { BarChart3, Globe, Sparkles } from "lucide-react";
import Link from "next/link";

export function Hero2() {
  const features = [
    {
      icon: Globe,
      title: "Multi-Platform Reach",
      description:
        "Optimize content for TikTok, Instagram, YouTube, and more from a single workflow.",
      tags: ["TikTok", "Instagram", "YouTube"],
    },
    {
      icon: Sparkles,
      title: "AI-Powered Optimization",
      description:
        "AI analyzes trends and enhances your content for maximum engagement across platforms.",
      tags: ["Real-time Analytics", "Trend Analysis"],
    },
    {
      icon: BarChart3,
      title: "Trusted by Creators",
      description:
        "Join 100+ creators boosting their views and engagement with proven tools and strategies.",
      tags: ["100+ Creators", "Proven Results"],
    },
  ];

  return (
    <section className="bg-[#272729] w-full py-20 px-6">
      <div className="max-w-[980px] mx-auto text-center mb-14">
        <h2 className="font-[system-ui,-apple-system,sans-serif] text-[40px] font-semibold leading-[1.1] tracking-[0] text-white mb-3">
          Everything you need to
          <br />
          dominate social media
        </h2>
        <p className="font-[system-ui,-apple-system,sans-serif] text-[17px] leading-[1.47] tracking-[-0.374px] text-[#cccccc] max-w-[680px] mx-auto">
          AI-powered tools to create, optimize, and scale your content across
          every major platform.
        </p>
      </div>

      <div className="max-w-[1200px] mx-auto grid grid-cols-1 md:grid-cols-3 gap-4">
        {features.map((feature, index) => {
          const Icon = feature.icon;
          return (
            <div
              key={index}
              className="bg-[#2a2a2c]/80 backdrop-blur-xl border border-[#3a3a3c]/60 rounded-[18px] p-6 hover:bg-[#323234] transition-colors"
            >
              <div className="w-10 h-10 rounded-full bg-[#0066cc]/20 flex items-center justify-center mb-5">
                <Icon className="w-5 h-5 text-[#2997ff]" />
              </div>
              <h3 className="text-[17px] font-semibold leading-[1.24] tracking-[-0.374px] text-white mb-2">
                {feature.title}
              </h3>
              <p className="text-[14px] leading-[1.43] tracking-[-0.224px] text-[#cccccc] mb-5">
                {feature.description}
              </p>
              <div className="flex flex-wrap gap-2">
                {feature.tags.map((tag, tagIndex) => (
                  <span
                    key={tagIndex}
                    className="text-[12px] leading-[1] tracking-[-0.12px] text-[#7a7a7a]"
                  >
                    {tag}
                    {tagIndex < feature.tags.length - 1 && (
                      <span className="ml-2 text-[#3a3a3c]">|</span>
                    )}
                  </span>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      {/* Stats bar */}
      <div className="max-w-[980px] mx-auto mt-16 text-center">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-8">
          {[
            { value: "100+", label: "Active Creators" },
            { value: "50K+", label: "Content Generated" },
            { value: "95%", label: "Engagement Boost" },
            { value: "24/7", label: "AI Support" },
          ].map((stat) => (
            <div key={stat.label}>
              <div className="text-[28px] font-[400] leading-[1.14] tracking-[0.196px] text-white mb-1">
                {stat.value}
              </div>
              <div className="text-[12px] leading-[1] tracking-[-0.12px] text-[#7a7a7a]">
                {stat.label}
              </div>
            </div>
          ))}
        </div>
        <div className="mt-8">
          <Link
            href="/sign-in"
            className="inline-flex items-center px-4 py-2 bg-[#0066cc]/85 backdrop-blur-xl text-white text-[14px] rounded-full hover:bg-[#0066cc] transition-colors active:scale-[0.95] border-[0.5px] border-white/20"
          >
            Join our community
          </Link>
        </div>
      </div>
    </section>
  );
}
