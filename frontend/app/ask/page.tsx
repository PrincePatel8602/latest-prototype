import type { Metadata } from "next";
import AskClient from "@/components/ask/AskClient";

export const metadata: Metadata = { title: "Ask", description: "Ask a question in plain English and watch the analysis come together." };

export default function Page() {
  return <AskClient />;
}
