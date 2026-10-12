import type { Metadata } from "next";
import { LandingPage } from "@/components/landing/landing-page";

export const metadata: Metadata = {
  title: "Chatbot SaaS — Your website, in conversation",
  description: "A helpful customer chatbot built around your website content, documents and business.",
};

export default function WelcomePage() {
  return <LandingPage />;
}
