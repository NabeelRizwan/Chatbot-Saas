import type { Metadata } from "next";
import { HomeEntry } from "@/components/landing/home-entry";

export const metadata: Metadata = {
  title: "Chatbot SaaS — Your website, in conversation",
  description: "Turn your website content and documents into helpful customer conversations. Customize your chatbot, review answers and give visitors a clear next step.",
};

export default function HomePage() {
  return <HomeEntry />;
}
