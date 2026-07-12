"use client";
import {
  Facebook,
  Instagram,
  Linkedin,
  Twitter,
  Youtube,
} from "lucide-react";
import Link from "next/link";

const Footer = () => {
  const currentYear = new Date().getFullYear();

  return (
    <footer className="bg-black w-full py-16 px-6 border-t border-white/10">
      <div className="max-w-[1200px] mx-auto">
        {/* Main grid: 4 columns */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-10 mb-12">
          {/* Brand column */}
          <div className="md:col-span-1">
            <div className="flex items-center gap-2 mb-5">
              <div className="w-8 h-8 rounded-[8px] bg-[#0066cc] flex items-center justify-center text-white text-sm font-semibold">
                F
              </div>
              <span className="text-[17px] font-semibold text-white">
                Friday
              </span>
            </div>
            <p className="text-[14px] leading-[1.43] tracking-[-0.224px] text-white/50 max-w-[260px]">
              AI-powered tools for content creators to generate viral titles,
              engaging descriptions, and trending hashtags.
            </p>
          </div>

          {/* Product links */}
          <div>
            <h4 className="text-[14px] font-semibold leading-[1.29] tracking-[-0.224px] text-white mb-4">
              Product
            </h4>
            <ul className="space-y-2">
              {[
                { name: "Title Generator", href: "/dashboard/getTitle" },
                { name: "Description Gen.", href: "/dashboard/getDescription" },
                { name: "Hashtag Generator", href: "/dashboard/getHashtags" },
                { name: "Analytics", href: "#" },
                { name: "API Access", href: "#" },
              ].map((link) => (
                <li key={link.name}>
                  <Link
                    href={link.href}
                    className="text-[14px] leading-[2.41] tracking-[-0.224px] text-white/50 hover:text-[#0066cc] transition-colors"
                  >
                    {link.name}
                  </Link>
                </li>
              ))}
            </ul>
          </div>

          {/* Company links */}
          <div>
            <h4 className="text-[14px] font-semibold leading-[1.29] tracking-[-0.224px] text-white mb-4">
              Company
            </h4>
            <ul className="space-y-2">
              {[
                { name: "About Us", href: "#about" },
                { name: "Blog", href: "#" },
                { name: "Careers", href: "#" },
                { name: "Privacy Policy", href: "#" },
                { name: "Terms of Service", href: "#" },
              ].map((link) => (
                <li key={link.name}>
                  <Link
                    href={link.href}
                    className="text-[14px] leading-[2.41] tracking-[-0.224px] text-white/50 hover:text-[#0066cc] transition-colors"
                  >
                    {link.name}
                  </Link>
                </li>
              ))}
            </ul>
          </div>

          {/* Contact column */}
          <div>
            <h4 className="text-[14px] font-semibold leading-[1.29] tracking-[-0.224px] text-white mb-4">
              Contact
            </h4>
            <ul className="space-y-2">
              <li>
                <a
                  href="mailto:hello@friday.ai"
                  className="text-[14px] leading-[2.41] tracking-[-0.224px] text-white/50 hover:text-[#0066cc] transition-colors"
                >
                  hello@friday.ai
                </a>
              </li>
              <li className="text-[14px] leading-[2.41] tracking-[-0.224px] text-white/50">
                San Francisco, CA
              </li>
            </ul>
            <div className="flex items-center gap-3 mt-6">
              {[
                { Icon: Youtube, href: "#" },
                { Icon: Twitter, href: "#" },
                { Icon: Instagram, href: "#" },
                { Icon: Facebook, href: "#" },
                { Icon: Linkedin, href: "#" },
              ].map(({ Icon, href }, idx) => (
                <a
                  key={idx}
                  href={href}
                  className="w-9 h-9 rounded-full bg-white/5 backdrop-blur-xl border border-white/10 flex items-center justify-center text-white/40 hover:text-[#0066cc] hover:border-[#0066cc]/30 transition-colors"
                >
                  <Icon size={16} />
                </a>
              ))}
            </div>
          </div>
        </div>

        {/* Bottom legal bar */}
        <div className="border-t border-white/10 pt-6 flex flex-col md:flex-row justify-between items-center gap-4">
          <div className="text-[12px] leading-[1] tracking-[-0.12px] text-white/50">
            © {currentYear} Friday. All rights reserved.
          </div>
          <div className="flex items-center gap-4 text-[12px] leading-[1] tracking-[-0.12px] text-white/50">
            <Link href="#" className="hover:text-[#0066cc] transition-colors">
              Privacy
            </Link>
            <Link href="#" className="hover:text-[#0066cc] transition-colors">
              Terms
            </Link>
          </div>
        </div>
      </div>
    </footer>
  );
};

export default Footer;
