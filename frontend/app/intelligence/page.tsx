import type { Metadata } from "next";
import IntelligenceClient from "@/components/pipeline/IntelligenceClient";

export const metadata: Metadata = { title: "How it works", description: "The whole FinSight system in one interactive picture: agents, data and the flow from question to evidence." };

export default function Page() {
  return <IntelligenceClient />;
}
