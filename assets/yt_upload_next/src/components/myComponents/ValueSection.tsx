"use client";
import { Play, Sparkles, TrendingUp } from "lucide-react";
import Image from "next/image";
import Link from "next/link";

const ValueSection = () => {
  return (
    <section className="bg-[#ffffff] w-full py-20 px-6" id="demo">
      <div className="max-w-[980px] mx-auto text-center mb-14">
          <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-[#f5f5f7]/80 backdrop-blur-xl text-[14px] text-[#7a7a7a] mb-6">
          <Play className="w-3.5 h-3.5 text-[#0066cc]" />
          Live Demo
        </div>

        <h2 className="font-[system-ui,-apple-system,sans-serif] text-[40px] font-semibold leading-[1.1] tracking-[0] text-[#1d1d1f] mb-3">
          See real results from
          <br />
          our community
        </h2>

        <p className="font-[system-ui,-apple-system,sans-serif] text-[17px] leading-[1.47] tracking-[-0.374px] text-[#7a7a7a] max-w-[680px] mx-auto mb-10">
          Discover how content creators are transforming their social media
          presence with our AI-powered tools and achieving remarkable growth.
        </p>

        <div className="flex flex-wrap justify-center gap-3 mb-14">
          <span className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-full bg-[#f5f5f7]/80 backdrop-blur-xl text-[14px] text-[#1d1d1f]">
            <TrendingUp className="w-3.5 h-3.5 text-[#0066cc]" />
            300% Average Growth
          </span>
          <span className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-full bg-[#f5f5f7]/80 backdrop-blur-xl text-[14px] text-[#1d1d1f]">
            <Sparkles className="w-3.5 h-3.5 text-[#0066cc]" />
            AI-Generated Content
          </span>
        </div>
      </div>

      {/* Demo content grid */}
      <div className="max-w-[1200px] mx-auto grid grid-cols-1 lg:grid-cols-2 gap-6 items-center">
        {/* Left: Before vs After card */}
        <div className="bg-[#f5f5f7]/80 backdrop-blur-xl rounded-[18px] p-8">
          <h3 className="font-[system-ui,-apple-system,sans-serif] text-[17px] font-semibold leading-[1.24] tracking-[-0.374px] text-[#1d1d1f] mb-6">
            Before vs After Results
          </h3>
          <div className="space-y-5">
            <div>
              <div className="flex justify-between items-center mb-2">
                <span className="text-[14px] text-[#7a7a7a]">Average Views</span>
                <div className="flex items-center gap-2 text-[14px]">
                  <span className="text-[#7a7a7a]">1.2K</span>
                  <span className="text-[#7a7a7a]">→</span>
                  <span className="text-[#1d1d1f] font-semibold">15.8K</span>
                </div>
              </div>
              <div className="h-1 bg-[#e0e0e0] rounded-full overflow-hidden">
                <div className="h-full bg-[#0066cc] rounded-full" style={{ width: "87%" }} />
              </div>
            </div>
            <div>
              <div className="flex justify-between items-center mb-2">
                <span className="text-[14px] text-[#7a7a7a]">Engagement Rate</span>
                <div className="flex items-center gap-2 text-[14px]">
                  <span className="text-[#7a7a7a]">2.1%</span>
                  <span className="text-[#7a7a7a]">→</span>
                  <span className="text-[#1d1d1f] font-semibold">8.7%</span>
                </div>
              </div>
              <div className="h-1 bg-[#e0e0e0] rounded-full overflow-hidden">
                <div className="h-full bg-[#0066cc] rounded-full" style={{ width: "72%" }} />
              </div>
            </div>
            <div>
              <div className="flex justify-between items-center mb-2">
                <span className="text-[14px] text-[#7a7a7a]">Follower Growth</span>
                <div className="flex items-center gap-2 text-[14px]">
                  <span className="text-[#7a7a7a]">+50/mo</span>
                  <span className="text-[#7a7a7a]">→</span>
                  <span className="text-[#1d1d1f] font-semibold">+1.2K/mo</span>
                </div>
              </div>
              <div className="h-1 bg-[#e0e0e0] rounded-full overflow-hidden">
                <div className="h-full bg-[#0066cc] rounded-full" style={{ width: "95%" }} />
              </div>
            </div>
          </div>
        </div>

        {/* Right: Testimonial card + phone mockups */}
        <div className="space-y-6">
          {/* Testimonial card */}
          <div className="bg-[#f5f5f7]/80 backdrop-blur-xl rounded-[18px] p-8">
            <h4 className="font-[system-ui,-apple-system,sans-serif] text-[17px] font-semibold leading-[1.24] tracking-[-0.374px] text-[#1d1d1f] mb-3">
              What Our Users Say
            </h4>
            <blockquote className="text-[17px] leading-[1.47] tracking-[-0.374px] text-[#7a7a7a] italic">
              &ldquo;Friday transformed my content strategy completely. My
              engagement increased by 400% in just 2 months!&rdquo;
            </blockquote>
            <div className="flex items-center gap-3 mt-4">
              <div className="w-10 h-10 rounded-full bg-[#0066cc] flex items-center justify-center text-white text-[14px] font-semibold">
                S
              </div>
              <div>
                <div className="text-[14px] font-semibold text-[#1d1d1f]">Sarah Johnson</div>
                <div className="text-[12px] text-[#7a7a7a]">Content Creator, 50K followers</div>
              </div>
            </div>
          </div>

          {/* Phone mockups side by side */}
          <div className="flex gap-4 justify-center">
            {["/confi_img.jpg", "/confi2_img.jpg"].map((src, i) => (
              <div
                key={src}
                className="relative w-[180px] h-[360px] rounded-[24px] overflow-hidden border-[3px] border-[#e0e0e0] shadow-[rgba(0,0,0,0.22)_3px_5px_30px_0px]"
              >
                <Image src={src} alt="App screenshot" fill className="object-cover" sizes="180px" />
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* CTA section */}
      <div className="max-w-[680px] mx-auto mt-16 text-center rounded-[18px] bg-[#f5f5f7]/80 backdrop-blur-xl p-10">
        <h3 className="font-[system-ui,-apple-system,sans-serif] text-[28px] font-[400] leading-[1.14] tracking-[0.196px] text-[#1d1d1f] mb-3">
          Ready to Transform Your Content?
        </h3>
        <p className="text-[17px] leading-[1.47] tracking-[-0.374px] text-[#7a7a7a] mb-6">
          Join thousands of creators who are already growing their audience with
          our AI tools.
        </p>
          <Link
            href="/sign-in"
            className="inline-flex items-center px-5 py-2.5 bg-[#0066cc]/85 backdrop-blur-xl text-white text-[17px] rounded-full hover:bg-[#0066cc] transition-colors active:scale-[0.95] border-[0.5px] border-white/20"
          >
            Start Creating Now
          </Link>
      </div>
    </section>
  );
};

export default ValueSection;
