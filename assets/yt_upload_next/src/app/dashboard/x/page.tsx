"use client";

import { Copy, ExternalLink, Sparkles, Loader2, Check } from "lucide-react";
import { useState } from "react";
import toast from "react-hot-toast";

export default function XPage() {
  const [mood, setMood] = useState("");
  const [context, setContext] = useState("");
  const [tweet, setTweet] = useState("");
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);

  const generate = async () => {
    if (!mood.trim() || !context.trim()) {
      toast.error("Please enter both mood and context");
      return;
    }
    setLoading(true);
    setTweet("");
    try {
      const res = await fetch("/api/generate-tweet", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "generateTweet", mood, context }),
      });
      const data = await res.json();
      if (data.success) {
        setTweet(data.tweet);
        toast.success("Tweet generated!");
      } else {
        toast.error(data.error || "Failed to generate tweet");
      }
    } catch {
      toast.error("Something went wrong");
    } finally {
      setLoading(false);
    }
  };

  const copyToClipboard = async () => {
    try {
      await navigator.clipboard.writeText(tweet);
      setCopied(true);
      toast.success("Copied to clipboard");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Failed to copy");
    }
  };

  const postToX = () => {
    window.open(
      `https://x.com/compose/post?text=${encodeURIComponent(tweet)}`,
      "_blank",
      "noopener,noreferrer",
    );
  };

  return (
    <div className="mx-auto max-w-2xl space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Tweet Generator</h1>
        <p className="mt-1 text-sm text-white/50">
          AI-powered tweet creation. Enter the mood and context, and let AI
          craft the perfect tweet.
        </p>
      </div>

      <div className="space-y-4">
        <div>
          <label className="mb-1.5 block text-sm font-medium text-white/70">
            Mood
          </label>
          <input
            value={mood}
            onChange={(e) => setMood(e.target.value)}
            placeholder="e.g. excited, thoughtful, humorous, inspiring"
            className="w-full rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-sm text-white placeholder-white/30 outline-none transition-colors focus:border-indigo-500/50"
          />
        </div>

        <div>
          <label className="mb-1.5 block text-sm font-medium text-white/70">
            Context
          </label>
          <textarea
            value={context}
            onChange={(e) => setContext(e.target.value)}
            placeholder="e.g. Just launched a new product, celebrating a milestone, sharing a lesson learned"
            rows={3}
            className="w-full rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-sm text-white placeholder-white/30 outline-none transition-colors focus:border-indigo-500/50 resize-none"
          />
        </div>

        <button
          onClick={generate}
          disabled={loading}
          className="flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-indigo-500 to-purple-500 px-4 py-2.5 text-sm font-medium text-white transition-all hover:opacity-90 disabled:opacity-50"
        >
          {loading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Sparkles className="h-4 w-4" />
          )}
          {loading ? "Generating..." : "Generate Tweet"}
        </button>
      </div>

      {tweet && (
        <div className="rounded-xl border border-white/10 bg-white/5 p-4 space-y-4">
          <div className="flex items-start justify-between gap-2">
            <p className="text-sm text-white leading-relaxed">{tweet}</p>
            <span className={`shrink-0 text-xs font-medium ${tweet.length > 140 ? "text-red-400" : "text-white/40"}`}>
              {tweet.length}/140
            </span>
          </div>

          <div className="flex gap-2">
            <button
              onClick={copyToClipboard}
              className="flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-2 text-xs font-medium text-white/70 transition-colors hover:bg-white/5 hover:text-white"
            >
              {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
              {copied ? "Copied" : "Copy"}
            </button>
            <button
              onClick={postToX}
              className="flex items-center gap-1.5 rounded-lg bg-white/10 px-3 py-2 text-xs font-medium text-white transition-colors hover:bg-white/20"
            >
              <ExternalLink className="h-3.5 w-3.5" />
              Post to X
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
