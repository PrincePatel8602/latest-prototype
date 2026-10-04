import type { Metadata } from "next";
import HistoryDetail from "@/components/history/HistoryDetail";

export const metadata: Metadata = { title: "Saved analysis" };

export default function Page() {
  return <HistoryDetail />;
}
