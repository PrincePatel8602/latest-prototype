import type { Metadata } from "next";
import HistoryClient from "@/components/history/HistoryClient";

export const metadata: Metadata = { title: "History", description: "Every analysis you have run, kept in this browser." };

export default function Page() {
  return <HistoryClient />;
}
