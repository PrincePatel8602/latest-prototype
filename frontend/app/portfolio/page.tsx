import type { Metadata } from "next";
import PortfolioClient from "@/components/portfolio/PortfolioClient";

export const metadata: Metadata = { title: "Portfolio", description: "What you hold, how it has moved, and what drives its risk." };

export default function Page() {
  return <PortfolioClient />;
}
