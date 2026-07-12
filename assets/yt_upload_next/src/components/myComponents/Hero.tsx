"use client";
import Link from "next/link";
import { Hero2 } from "./Hero2";

const Hero = () => {
  return (
    <main>
      <section className="bg-black w-full pt-24 pb-20 px-6">
        <div className="max-w-[980px] mx-auto text-center">
          <h1 className="font-[system-ui,-apple-system,sans-serif] text-[56px] md:text-[56px] font-semibold leading-[1.07] tracking-[-0.28px] text-white mb-4">
            Engage your audience
            <br />
            with stunning videos
          </h1>
          <p className="font-[system-ui,-apple-system,sans-serif] text-[17px] leading-[1.47] tracking-[-0.374px] text-white/60 max-w-[680px] mx-auto mb-10">
            Transform your content strategy with AI-powered insights that
            maximize visibility, engagement, and growth across all platforms.
          </p>
          <div className="flex items-center justify-center gap-3">
            <Link
              href="/sign-in"
              className="inline-flex items-center px-5 py-2.5 bg-[#0066cc]/85 backdrop-blur-xl text-white text-[17px] rounded-full hover:bg-[#0066cc] transition-colors active:scale-[0.95] border-[0.5px] border-white/20"
            >
              Get Started
            </Link>
            <Link
              href="#demo"
              className="inline-flex items-center px-5 py-2.5 bg-white/5 backdrop-blur-xl text-white text-[17px] rounded-full border border-white/20 hover:bg-white/10 transition-colors active:scale-[0.95]"
            >
              Learn More
            </Link>
          </div>
        </div>
      </section>

      {/* Showcase gallery — Apple-style product imagery row */}
      <section className="bg-black w-full pb-20 overflow-hidden">
        <div className="relative h-[280px] md:h-[360px] [mask-image:linear-gradient(to_bottom,transparent,black_20%,black_80%,transparent)]">
          <div
            className="flex gap-4 animate-scroll-left"
            style={{ width: "max-content" }}
          >
            {[
              "https://images.unsplash.com/photo-1756312148347-611b60723c7a?w=900&auto=format&fit=crop&q=60&ixlib=rb-4.1.0&ixid=M3wxMjA3fDB8MHxmZWF0dXJlZC1waG90b3MtZmVlZHwzN3x8fGVufDB8fHx8fA%3D%3D",
              "https://images.unsplash.com/photo-1757865579201-693dd2080c73?w=900&auto=format&fit=crop&q=60&ixlib=rb-4.1.0&ixid=M3wxMjA3fDB8MHxmZWF0dXJlZC1waG90b3MtZmVlZHw2MXx8fGVufDB8fHx8fA%3D%3D",
              "https://images.unsplash.com/photo-1756786605218-28f7dd95a493?w=900&auto=format&fit=crop&q=60&ixlib=rb-4.1.0&ixid=M3wxMjA3fDB8MHxmZWF0dXJlZC1waG90b3MtZmVlZHwxMzh8fHxlbnwwfHx8fHw%3D",
              "https://images.unsplash.com/photo-1757519740947-eef07a74c4ab?w=900&auto=format&fit=crop&q=60&ixlib=rb-4.1.0&ixid=M3wxMjA3fDB8MHxmZWF0dXJlZC1waG90b3MtZmVlZHwxNDh8fHxlbnwwfHx8fHw%3D",
              "https://images.unsplash.com/photo-1757263005786-43d955f07fb1?w=900&auto=format&fit=crop&q=60&ixlib=rb-4.1.0&ixid=M3wxMjA3fDB8MHxmZWF0dXJlZC1waG90b3MtZmVlZHwxNzB8fHxlbnwwfHx8fHw%3D",
              "https://images.unsplash.com/photo-1757207445614-d1e12b8f753e?w=900&auto=format&fit=crop&q=60&ixlib=rb-4.1.0&ixid=M3wxMjA3fDB8MHxmZWF0dXJlZC1waG90b3MtZmVlZHwxODZ8fHxlbnwwfHx8fHw%3D",
              "https://images.unsplash.com/photo-1757269746970-dc477517268f?w=900&auto=format&fit=crop&q=60&ixlib=rb-4.1.0&ixid=M3wxMjA3fDB8MHxmZWF0dXJlZC1waG90b3MtZmVlZHwyMjN8fHxlbnwwfHx8fHw%3D",
              "https://images.unsplash.com/photo-1755119902709-a53513bcbedc?w=900&auto=format&fit=crop&q=60&ixlib=rb-4.1.0&ixid=M3wxMjA3fDB8MHxmZWF0dXJlZC1waG90b3MtZmVlZHwyNDF8fHxlbnwwfHx8fHw%3D",
            ].concat([
              "https://images.unsplash.com/photo-1756312148347-611b60723c7a?w=900&auto=format&fit=crop&q=60&ixlib=rb-4.1.0&ixid=M3wxMjA3fDB8MHxmZWF0dXJlZC1waG90b3MtZmVlZHwzN3x8fGVufDB8fHx8fA%3D%3D",
              "https://images.unsplash.com/photo-1757865579201-693dd2080c73?w=900&auto=format&fit=crop&q=60&ixlib=rb-4.1.0&ixid=M3wxMjA3fDB8MHxmZWF0dXJlZC1waG90b3MtZmVlZHw2MXx8fGVufDB8fHx8fA%3D%3D",
              "https://images.unsplash.com/photo-1756786605218-28f7dd95a493?w=900&auto=format&fit=crop&q=60&ixlib=rb-4.1.0&ixid=M3wxMjA3fDB8MHxmZWF0dXJlZC1waG90b3MtZmVlZHwxMzh8fHxlbnwwfHx8fHw%3D",
              "https://images.unsplash.com/photo-1757519740947-eef07a74c4ab?w=900&auto=format&fit=crop&q=60&ixlib=rb-4.1.0&ixid=M3wxMjA3fDB8MHxmZWF0dXJlZC1waG90b3MtZmVlZHwxNDh8fHxlbnwwfHx8fHw%3D",
              "https://images.unsplash.com/photo-1757263005786-43d955f07fb1?w=900&auto=format&fit=crop&q=60&ixlib=rb-4.1.0&ixid=M3wxMjA3fDB8MHxmZWF0dXJlZC1waG90b3MtZmVlZHwxNzB8fHxlbnwwfHx8fHw%3D",
              "https://images.unsplash.com/photo-1757207445614-d1e12b8f753e?w=900&auto=format&fit=crop&q=60&ixlib=rb-4.1.0&ixid=M3wxMjA3fDB8MHxmZWF0dXJlZC1waG90b3MtZmVlZHwxODZ8fHxlbnwwfHx8fHw%3D",
              "https://images.unsplash.com/photo-1757269746970-dc477517268f?w=900&auto=format&fit=crop&q=60&ixlib=rb-4.1.0&ixid=M3wxMjA3fDB8MHxmZWF0dXJlZC1waG90b3MtZmVlZHwyMjN8fHxlbnwwfHx8fHw%3D",
              "https://images.unsplash.com/photo-1755119902709-a53513bcbedc?w=900&auto=format&fit=crop&q=60&ixlib=rb-4.1.0&ixid=M3wxMjA3fDB8MHxmZWF0dXJlZC1waG90b3MtZmVlZHwyNDF8fHxlbnwwfHx8fHw%3D",
            ]).map((src, i) => (
              <div
                key={i}
                className="relative aspect-[3/4] h-48 md:h-64 flex-shrink-0"
                style={{ rotate: i % 2 === 0 ? "-2deg" : "3deg" }}
              >
                <img
                  alt={`Showcase image ${i + 1}`}
                  className="w-full h-full object-cover rounded-2xl shadow-[rgba(0,0,0,0.22)_3px_5px_30px_0px]"
                  src={src}
                />
              </div>
            ))}
          </div>
        </div>
      </section>

      <Hero2 />
    </main>
  );
};

export default Hero;
