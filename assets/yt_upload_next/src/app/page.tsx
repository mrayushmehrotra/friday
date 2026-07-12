import CreativeFooter from "@/components/myComponents/CreativeFooter";
import Hero from "@/components/myComponents/Hero";
import Navbar from "@/components/myComponents/Navbar";
import ValueSection from "@/components/myComponents/ValueSection";

export default function Home() {
  return (
    <div className="min-h-screen bg-black">
      <Navbar />
      <Hero />
      <ValueSection />
      <CreativeFooter />
    </div>
  );
}
