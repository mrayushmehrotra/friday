"use client";

export default function StockResearchPage() {
  return (
    <div className="h-full w-full">
      <iframe
        src="http://localhost:8501"
        className="w-full h-full"
        style={{ minHeight: "100vh", border: "none" }}
        title="Stock Research"
      />
    </div>
  );
}
