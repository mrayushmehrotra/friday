"use client";
import { CheckCircle2, LogIn, Youtube } from "lucide-react";
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

  useEffect(() => {
    const checkExistingAuth = async () => {
      const existingToken = localStorage.getItem("youtube_access_token");
      const userId = localStorage.getItem("user_id") || document.cookie.match(/user_id=([^;]+)/)?.[1];

      if (existingToken && userId) {
        try {
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

    if (!searchParams.get("code")) {
      checkExistingAuth();
    } else {
      setCheckingAuth(false);
    }
  }, [router, searchParams]);

  useEffect(() => {
    const code = searchParams.get("code");
    if (code && !processing && !exchangeAttempted.current) {
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
            toast.success("Successfully connected!", { id: toastId });
            router.push("/dashboard");
          } else {
            toast.error(
              `Failed to exchange code: ${result.error || "Unknown error"}`,
              { id: toastId },
            );
            setProcessing(false);
          }
        } catch (error: any) {
          console.error("❌ Sign In Callback: Error details:", error);
          toast.error(`Authentication error: ${error.message}`, {
            id: toastId,
          });
          setProcessing(false);
        }
      };
      exchangeCode();
    }
  }, [searchParams, router, processing]);

  const authenticateWithGoogle = async () => {
    try {
      console.log("🔍 Sign In: Starting Google authentication");

      if (authUrlCache.current) {
        console.log("✅ Sign In: Using cached auth URL");
        window.location.href = authUrlCache.current;
        return;
      }

      const response = await fetch("/api/google?action=auth");
      const { authUrl } = await response.json();

      authUrlCache.current = authUrl;

      console.log("✅ Sign In: Got auth URL, redirecting...");
      window.location.href = authUrl;
    } catch (_error) {
      console.error("❌ Sign In: Auth failed:", _error);
      toast.error("Authentication failed", { id: "21312" });
    }
  };

  if (checkingAuth) {
    return (
      <div className="flex h-screen items-center justify-center bg-black">
        <div className="w-8 h-8 border-2 border-[#0066cc] border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen flex bg-black overflow-hidden relative">
      {/* Left visual side */}
      <div className="hidden lg:flex w-1/2 relative z-10 flex-col items-center justify-center p-12">
        <div className="max-w-lg space-y-8">
          <div className="text-center">
            <h2 className="text-[40px] font-semibold leading-[1.1] tracking-[0] text-white mb-3">
              Content Creation
              <br />
              Superpowers
            </h2>
            <p className="text-[17px] leading-[1.47] tracking-[-0.374px] text-white/60">
              AI-powered tools to optimize your social media growth.
            </p>
          </div>

          <div className="grid grid-cols-2 gap-3 pt-4">
            {[
              "AI Title Generator",
              "Smart Descriptions",
              "Viral Hashtags",
              "Growth Analytics",
            ].map((feature, i) => (
              <div key={i} className="flex items-center gap-2 text-[14px] text-white bg-white/5 backdrop-blur-xl rounded-full px-4 py-2 border border-white/10">
                <CheckCircle2 className="w-4 h-4 text-[#0066cc]" />
                <span>{feature}</span>
              </div>
            ))}
          </div>

          {/* Preview card */}
          <div className="mt-8 bg-white/5 backdrop-blur-xl rounded-[18px] p-6 border border-white/10 shadow-[0_8px_32px_rgba(0,0,0,0.3)]">
            <div className="flex items-center gap-2 mb-4">
              <div className="h-2.5 w-2.5 rounded-full bg-[#0066cc]" />
              <div className="h-2.5 w-2.5 rounded-full bg-white/20" />
              <div className="h-2.5 w-2.5 rounded-full bg-white/20" />
            </div>
            <div className="space-y-3">
              <div className="h-3 bg-white/10 rounded w-3/4" />
              <div className="h-3 bg-white/10 rounded w-1/2" />
              <div className="flex gap-2 pt-2">
                <div className="h-16 w-24 rounded-lg bg-[#0066cc]/20" />
                <div className="h-16 w-24 rounded-lg bg-[#0066cc]/20" />
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Right form side */}
      <div className="w-full lg:w-1/2 flex flex-col items-center justify-center p-6 relative z-10">
        <div className="w-full max-w-md rounded-[18px] p-8 md:p-12 bg-white/5 backdrop-blur-2xl shadow-[0_8px_32px_rgba(0,0,0,0.5),0_1px_2px_rgba(0,0,0,0.2)] border border-white/10 relative overflow-hidden">
          <div className="relative z-10">
            <div className="flex justify-center mb-8">
              <div className="p-4 rounded-2xl bg-[#0066cc]/10">
                <Youtube className="w-10 h-10 text-[#0066cc]" />
              </div>
            </div>

            <div className="text-center mb-8">
              <h1 className="text-[28px] font-[400] leading-[1.14] tracking-[0.196px] text-white mb-2">
                Welcome Back
              </h1>
              <p className="text-[17px] leading-[1.47] tracking-[-0.374px] text-white/60">
                Connect your account to continue
              </p>
            </div>

            <button
              onClick={authenticateWithGoogle}
              disabled={processing}
              className="w-full inline-flex items-center justify-center gap-3 px-5 py-3 bg-[#0066cc]/85 backdrop-blur-xl text-white text-[17px] rounded-full hover:bg-[#0066cc] transition-colors active:scale-[0.95] border-[0.5px] border-white/20 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {processing ? (
                <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              ) : (
                <LogIn className="w-5 h-5" />
              )}
              <span className="font-semibold">
                {processing ? "Connecting..." : "Connect with YouTube"}
              </span>
            </button>

            <div className="mt-8 text-center">
              <p className="text-[12px] leading-[1] tracking-[-0.12px] text-white/50">
                By connecting, you agree to our{" "}
                <Link
                  href="/terms"
                  className="text-[#0066cc] hover:underline"
                >
                  Terms
                </Link>{" "}
                and{" "}
                <Link
                  href="/privacy"
                  className="text-[#0066cc] hover:underline"
                >
                  Privacy Policy
                </Link>
              </p>
            </div>

            <div className="mt-6 pt-6 border-t border-white/10 text-center">
              <Link
                href="/dashboard"
                className="inline-flex items-center gap-1 text-[14px] text-[#0066cc] hover:underline"
              >
                Already connected?{" "}
                <span className="font-semibold">Go to dashboard &rarr;</span>
              </Link>
            </div>
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
          <div className="w-8 h-8 border-2 border-[#0066cc] border-t-transparent rounded-full animate-spin" />
        </div>
      }
    >
      <AuthContent />
    </Suspense>
  );
}
