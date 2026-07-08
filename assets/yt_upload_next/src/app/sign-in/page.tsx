"use client";
import { CheckCircle2, LogIn, Sparkles, Youtube } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import React, { Suspense, useEffect } from "react";
import toast from "react-hot-toast";

const AuthContent = () => {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [processing, setProcessing] = React.useState(false);
  const [checkingAuth, setCheckingAuth] = React.useState(true);
  const exchangeAttempted = React.useRef(false);
  const authUrlCache = React.useRef<string | null>(null);

  // Check for existing valid session first
  useEffect(() => {
    const checkExistingAuth = async () => {
      const existingToken = localStorage.getItem("youtube_access_token");
      const userId = localStorage.getItem("user_id") || document.cookie.match(/user_id=([^;]+)/)?.[1];

      if (existingToken && userId) {
        try {
          // Validate session with backend
          const response = await fetch("/api/google", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action: "checkSession", userId }),
          });
          const result = await response.json();

          if (result.valid) {
            console.log("✅ Existing valid session found, redirecting to dashboard");
            router.push("/dashboard");
            return;
          }
        } catch (error) {
          console.log("Session check failed, showing sign-in");
        }
      }
      setCheckingAuth(false);
    };

    // Only check if no code in URL (not in callback flow)
    if (!searchParams.get("code")) {
      checkExistingAuth();
    } else {
      setCheckingAuth(false);
    }
  }, [router, searchParams]);

  // Handle OAuth callback
  useEffect(() => {
    const code = searchParams.get("code");
    if (code && !processing && !exchangeAttempted.current) {
      // Clear code from URL immediately to prevent retries on refresh
      window.history.replaceState({}, '', '/sign-in');

      exchangeAttempted.current = true;
      setProcessing(true);
      const toastId = toast.loading("Connecting to YouTube...");

      const exchangeCode = async () => {
        try {
          console.log("🔍 Sign In Callback: Exchanging code for tokens");
          const response = await fetch("/api/google", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action: "exchangeCode", code }),
          });

          if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`HTTP ${response.status}: ${errorText}`);
          }

          const result = await response.json();

          if (result.success && result.tokens) {
            console.log("✅ Sign In Callback: Successfully connected!");
            localStorage.setItem(
              "youtube_access_token",
              result.tokens.access_token,
            );
            // The server also sets a cookie now, so both are covered
            toast.success("Successfully connected!", { id: toastId });
            router.push("/dashboard");
          } else {
            toast.error(
              `Failed to exchange code: ${result.error || "Unknown error"}`,
              { id: toastId },
            );
            setProcessing(false);
            // Don't reset exchangeAttempted - the code is already burned
          }
        } catch (error: any) {
          console.error("❌ Sign In Callback: Error details:", error);
          toast.error(`Authentication error: ${error.message}`, {
            id: toastId,
          });
          setProcessing(false);
          // Don't reset exchangeAttempted - the code is already burned
        }
      };
      exchangeCode();
    }
  }, [searchParams, router, processing]);

  const authenticateWithGoogle = async () => {
    try {
      console.log("🔍 Sign In: Starting Google authentication");

      // Use cached auth URL if available
      if (authUrlCache.current) {
        console.log("✅ Sign In: Using cached auth URL");
        window.location.href = authUrlCache.current;
        return;
      }

      const response = await fetch("/api/google?action=auth");
      const { authUrl } = await response.json();

      // Cache the auth URL for future use
      authUrlCache.current = authUrl;

      console.log("✅ Sign In: Got auth URL, redirecting...");
      window.location.href = authUrl;
    } catch (_error) {
      console.error("❌ Sign In: Auth failed:", _error);
      toast.error("Authentication failed", { id: "21312" });
    }
  };

  // Show loading state while checking existing auth
  if (checkingAuth) {
    return (
      <div className="flex h-screen items-center justify-center bg-black">
        <div className="w-8 h-8 border-2 border-purple-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen flex bg-black text-white overflow-hidden relative">
      {/* Background Ambience */}
      <div className="absolute inset-0 z-0">
        <div className="absolute top-0 -left-1/4 w-1/2 h-1/2 bg-purple-900/20 rounded-full blur-[120px] animate-pulse-slow" />
        <div className="absolute bottom-0 -right-1/4 w-1/2 h-1/2 bg-indigo-900/20 rounded-full blur-[120px] animate-pulse-slow font-delay-2000" />
      </div>

      {/* Left visual side (Desktop only) */}
      <div className="hidden lg:flex w-1/2 relative z-10 flex-col items-center justify-center p-12 bg-gradient-to-br from-gray-900/50 to-black/50 border-r border-white/5 backdrop-blur-sm">
        <div className="max-w-lg space-y-8">
          <div className="relative">
            <div className="absolute -inset-1 bg-gradient-to-r from-purple-600 to-pink-600 rounded-2xl blur opacity-75 animate-glow" />
            <div className="relative bg-black border border-white/10 rounded-2xl p-8 shadow-2xl">
              <div className="flex items-center gap-3 mb-6">
                <div className="h-3 w-3 rounded-full bg-red-500" />
                <div className="h-3 w-3 rounded-full bg-yellow-500" />
                <div className="h-3 w-3 rounded-full bg-green-500" />
              </div>
              <div className="space-y-4">
                <div className="h-4 bg-white/10 rounded w-3/4" />
                <div className="h-4 bg-white/10 rounded w-1/2" />
                <div className="flex gap-2 pt-2">
                  <div className="h-20 w-32 bg-purple-500/10 rounded border border-purple-500/20" />
                  <div className="h-20 w-32 bg-pink-500/10 rounded border border-pink-500/20" />
                </div>
              </div>
            </div>
          </div>

          <div className="text-center">
            <h2 className="text-3xl font-bold mb-4 bg-clip-text text-transparent bg-gradient-to-r from-purple-400 to-pink-600">
              Content Creation Superpowers
            </h2>
            <p className="text-gray-400 text-lg">
              Join thousands of creators using AI to optimize their social media
              growth.
            </p>
          </div>

          <div className="grid grid-cols-2 gap-4 pt-8">
            {[
              "AI Title Generator",
              "Smart Descriptions",
              "Viral Hashtags",
              "Growth Analytics",
            ].map((feature, i) => (
              <div key={i} className="flex items-center gap-2 text-gray-300">
                <CheckCircle2 className="w-5 h-5 text-green-400" />
                <span>{feature}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Right form side */}
      <div className="w-full lg:w-1/2 flex flex-col items-center justify-center p-6 relative z-10">
        <div className="glass-strong rounded-3xl p-8 md:p-12 w-full max-w-md border border-white/10 shadow-2xl relative overflow-hidden group">
          {/* Decorative elements */}
          <div className="absolute top-0 right-0 w-32 h-32 bg-gradient-to-br from-purple-500/10 to-transparent rounded-bl-full" />
          <div className="absolute bottom-0 left-0 w-32 h-32 bg-gradient-to-tr from-pink-500/10 to-transparent rounded-tr-full" />

          <div className="relative z-10">
            <div className="flex justify-center mb-8">
              <div className="p-4 rounded-2xl bg-gradient-to-br from-red-600 to-red-700 shadow-lg shadow-red-500/20 group-hover:scale-110 transition-transform duration-300">
                <Youtube className="w-10 h-10 text-white" />
              </div>
            </div>

            <div className="text-center mb-8">
              <h1 className="text-3xl font-bold text-white mb-2 tracking-tight">
                Welcome Back
              </h1>
              <p className="text-gray-400">Connect your account to continue</p>
            </div>

            <button
              onClick={authenticateWithGoogle}
              disabled={processing}
              className="w-full group/btn relative overflow-hidden rounded-xl p-[1px] focus:outline-none focus:ring-2 focus:ring-purple-500 focus:ring-offset-2 focus:ring-offset-black disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <div className="absolute inset-0 bg-gradient-to-r from-red-600 via-purple-600 to-blue-600 animate-border-spin" />
              <div className="relative h-full bg-black rounded-xl px-8 py-4 flex items-center justify-center gap-3 transition-colors group-hover/btn:bg-gray-900">
                {processing ? (
                  <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                ) : (
                  <LogIn className="w-5 h-5 text-white" />
                )}
                <span className="font-semibold text-white">
                  {processing ? "Connecting..." : "Connect with YouTube"}
                </span>
              </div>
            </button>

            <div className="mt-8 text-center">
              <p className="text-sm text-gray-500">
                By connecting, you agree to our{" "}
                <Link
                  href="/terms"
                  className="text-gray-400 hover:text-white underline decoration-gray-600 hover:decoration-white transition-all"
                >
                  Terms
                </Link>{" "}
                and{" "}
                <Link
                  href="/privacy"
                  className="text-gray-400 hover:text-white underline decoration-gray-600 hover:decoration-white transition-all"
                >
                  Privacy Policy
                </Link>
              </p>
            </div>

            <div className="mt-6 pt-6 border-t border-white/5 text-center">
              <Link
                href="/dashboard"
                className="inline-flex items-center gap-1 text-sm text-purple-400 hover:text-purple-300 transition-colors"
              >
                Already connected?{" "}
                <span className="font-semibold">Go to dashboard &rarr;</span>
              </Link>
            </div>
          </div>
        </div>

        {/* Footer brand */}
        <div className="absolute bottom-8 left-0 w-full text-center">
          <div className="inline-flex items-center gap-2 text-white/20">
            <Sparkles className="w-4 h-4" />
            <span className="text-sm font-medium tracking-widest uppercase">
              invid.ai
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};

export default function Page() {
  return (
    <Suspense
      fallback={
        <div className="flex h-screen items-center justify-center bg-black">
          <div className="w-8 h-8 border-2 border-red-500 border-t-transparent rounded-full animate-spin" />
        </div>
      }
    >
      <AuthContent />
    </Suspense>
  );
}
