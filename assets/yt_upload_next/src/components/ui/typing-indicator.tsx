"use client";

export const TypingIndicator = () => {
  return (
    <div className="flex items-center gap-1 p-4">
      <div className="flex gap-1">
        <div
          className="w-2 h-2 bg-purple-400 rounded-full animate-bounce"
          style={{ animationDelay: "0ms" }}
        />
        <div
          className="w-2 h-2 bg-purple-400 rounded-full animate-bounce"
          style={{ animationDelay: "150ms" }}
        />
        <div
          className="w-2 h-2 bg-purple-400 rounded-full animate-bounce"
          style={{ animationDelay: "300ms" }}
        />
      </div>
      <span className="text-sm text-gray-400 ml-2">AI is thinking...</span>
    </div>
  );
};
