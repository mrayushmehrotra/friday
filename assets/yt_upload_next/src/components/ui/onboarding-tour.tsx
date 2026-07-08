"use client";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowLeft, ArrowRight, Sparkles, X } from "lucide-react";
import Image from "next/image";
import { useEffect, useState } from "react";

interface TourStep {
  title: string;
  content: string;
  image: string;
  highlight?: string;
}

const tourSteps: TourStep[] = [
  {
    title: "Welcome to invid.ai! 🎉",
    content:
      "Your AI-powered YouTube content creation suite. Let's take a quick tour to help you get started and unlock your creative potential.",
    image: "/onboarding_yt.jpg",
    highlight: "Connect your YouTube channel to get started",
  },
  {
    title: "Create Amazing Content",
    content:
      "Generate viral titles, descriptions, hashtags, and even AI voiceovers. Everything you need to grow your channel is right here.",
    image: "/onboarding_yt_2.png",
    highlight: "Track your daily usage in the sidebar",
  },
];

export const OnboardingTour = () => {
  const [isActive, setIsActive] = useState(false);
  const [currentStep, setCurrentStep] = useState(0);

  useEffect(() => {
    const hasSeenTour = localStorage.getItem("hasSeenTour");
    if (!hasSeenTour) {
      setTimeout(() => setIsActive(true), 1500);
    }
  }, []);

  const nextStep = () => {
    if (currentStep < tourSteps.length - 1) {
      setCurrentStep(currentStep + 1);
    } else {
      completeTour();
    }
  };

  const prevStep = () => {
    if (currentStep > 0) {
      setCurrentStep(currentStep - 1);
    }
  };

  const completeTour = () => {
    setIsActive(false);
    localStorage.setItem("hasSeenTour", "true");
  };

  const skipTour = () => {
    completeTour();
  };

  if (!isActive) return null;

  const step = tourSteps[currentStep];

  return (
    <AnimatePresence>
      {isActive && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/80 backdrop-blur-sm z-[100]"
            onClick={skipTour}
          />

          {/* Modal Container - Flexbox for reliable centering */}
          <div className="fixed inset-0 z-[101] flex items-center justify-center p-4 pointer-events-none">
            <motion.div
              initial={{ opacity: 0, scale: 0.9, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.9, y: 20 }}
              transition={{ type: "spring", damping: 25, stiffness: 300 }}
              className="w-full max-w-2xl pointer-events-auto
                         bg-gradient-to-br from-gray-900/95 via-gray-950/95 to-black/95
                         backdrop-blur-xl rounded-3xl overflow-hidden
                         border border-white/10 shadow-2xl shadow-purple-500/20"
            >
              {/* Close Button */}
              <button
                onClick={skipTour}
                className="absolute top-4 right-4 z-10 p-2 rounded-xl 
                       bg-black/50 hover:bg-white/10 
                       text-gray-400 hover:text-white
                       transition-all duration-300"
              >
                <X className="w-5 h-5" />
              </button>

              {/* Image Section */}
              <motion.div
                key={currentStep}
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -20 }}
                transition={{ duration: 0.3 }}
                className="relative w-full h-56 sm:h-64 overflow-hidden"
              >
                <Image
                  src={step.image}
                  fill
                  className="object-cover"
                  alt={step.title}
                  priority
                />
                {/* Gradient overlay */}
                <div className="absolute inset-0 bg-gradient-to-t from-gray-950 via-transparent to-transparent" />

                {/* Floating badge */}
                <div className="absolute top-4 left-4 px-3 py-1.5 rounded-full 
                            bg-purple-500/20 backdrop-blur-md border border-purple-500/30
                            flex items-center gap-2">
                  <Sparkles className="w-4 h-4 text-purple-400" />
                  <span className="text-sm font-medium text-purple-200">
                    Step {currentStep + 1} of {tourSteps.length}
                  </span>
                </div>
              </motion.div>

              {/* Content Section */}
              <div className="p-6 sm:p-8">
                <motion.div
                  key={`content-${currentStep}`}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3, delay: 0.1 }}
                >
                  <h2 className="text-2xl sm:text-3xl font-bold text-white mb-3">
                    {step.title}
                  </h2>
                  <p className="text-gray-300 text-base sm:text-lg leading-relaxed mb-4">
                    {step.content}
                  </p>

                  {/* Highlight tip */}
                  {step.highlight && (
                    <div className="px-4 py-3 rounded-xl bg-gradient-to-r from-purple-500/10 to-pink-500/10
                                border border-purple-500/20 mb-6">
                      <p className="text-sm text-purple-200 flex items-center gap-2">
                        <span className="text-purple-400">💡</span>
                        {step.highlight}
                      </p>
                    </div>
                  )}
                </motion.div>

                {/* Footer */}
                <div className="flex justify-between items-center pt-4 border-t border-white/10">
                  {/* Progress dots */}
                  <div className="flex gap-2">
                    {tourSteps.map((_, index) => (
                      <button
                        key={index}
                        onClick={() => setCurrentStep(index)}
                        className={`w-2.5 h-2.5 rounded-full transition-all duration-300 ${index === currentStep
                          ? "bg-gradient-to-r from-purple-500 to-pink-500 w-8"
                          : "bg-gray-600 hover:bg-gray-500"
                          }`}
                      />
                    ))}
                  </div>

                  {/* Navigation buttons */}
                  <div className="flex gap-3">
                    {currentStep > 0 && (
                      <motion.button
                        initial={{ opacity: 0, x: 10 }}
                        animate={{ opacity: 1, x: 0 }}
                        onClick={prevStep}
                        className="px-5 py-2.5 rounded-xl 
                               bg-white/5 hover:bg-white/10 
                               border border-white/10 hover:border-white/20
                               text-white font-medium
                               transition-all duration-300 flex items-center gap-2"
                      >
                        <ArrowLeft className="w-4 h-4" />
                        Back
                      </motion.button>
                    )}
                    <motion.button
                      whileHover={{ scale: 1.02 }}
                      whileTap={{ scale: 0.98 }}
                      onClick={nextStep}
                      className="px-6 py-2.5 rounded-xl 
                             bg-gradient-to-r from-purple-600 to-pink-600 
                             hover:from-purple-500 hover:to-pink-500
                             text-white font-medium shadow-lg shadow-purple-500/25
                             transition-all duration-300 flex items-center gap-2"
                    >
                      {currentStep === tourSteps.length - 1 ? (
                        <>
                          Get Started
                          <Sparkles className="w-4 h-4" />
                        </>
                      ) : (
                        <>
                          Next
                          <ArrowRight className="w-4 h-4" />
                        </>
                      )}
                    </motion.button>
                  </div>
                </div>
              </div>
            </motion.div>
          </div>
        </>
      )}
    </AnimatePresence>
  );
};
