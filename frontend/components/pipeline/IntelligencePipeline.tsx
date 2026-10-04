"use client";

import { motion } from "motion/react";
import { Check, Loader2, Play } from "lucide-react";
import { useAnalysis } from "@/hooks/useAnalysis";
import { cn } from "@/lib/cn";
import { duration } from "@/lib/format";
import { ICONS } from "@/components/pipeline/PipelineView";
import { AGENTS } from "@/lib/agents";

const STAGES = [
  "User Query",
  "Query Understanding",
  "Agent Selection",
  "Data Gathering", // Market / News / Weather / Historical
  "Quant Processing",
  "Synthesis", // Risk / Drivers / Fusion
  "Final Insight"
];

export default function IntelligencePipeline() {
  const { state: run, run: startRun } = useAnalysis();

  const isRunning = run.phase !== "idle" && run.phase !== "done" && run.phase !== "error";
  const isDone = run.phase === "done";
  
  // Map RunState to our 7 stages
  const activeStage = 
    run.phase === "idle" ? -1 :
    run.phase === "understanding" ? 1 :
    run.phase === "running" && run.steps.length === 0 ? 2 :
    run.phase === "running" && run.steps.some(s => s.status === "active") ? 3 :
    run.phase === "running" && run.steps.every(s => s.status === "done" || s.status === "failed") ? 5 :
    run.phase === "done" ? 6 : -1;

  const handlePlay = () => {
    startRun("How would a Category 4 hurricane in the Gulf of Mexico affect my energy holdings?");
  };

  return (
    <div className="relative mx-auto max-w-6xl py-12">
      <div className="mb-12 text-center">
        <h2 className="display mb-4 text-balance">Watch intelligence happen.</h2>
        <p className="lead mx-auto max-w-2xl text-balance">
          Every query runs through a deterministic pipeline. No black boxes.
        </p>
        
        {run.phase === "idle" && (
          <button 
            onClick={handlePlay}
            className="group mt-8 inline-flex items-center gap-2 rounded-full bg-ink px-6 py-3 text-sm font-medium text-bg transition hover:scale-105"
          >
            <Play className="h-4 w-4 fill-current" />
            Play Live Example
          </button>
        )}
      </div>

      <div className="relative mt-20">
        {/* Connection Line */}
        <div className="absolute left-[27px] top-0 h-full w-px bg-line md:left-0 md:top-[27px] md:h-px md:w-full" />
        
        <div className="flex flex-col gap-8 md:flex-row md:justify-between md:gap-4">
          {STAGES.map((stage, i) => {
            const isActive = i === activeStage;
            const isCompleted = isDone || i < activeStage;
            const isWaiting = !isActive && !isCompleted;

            return (
              <div key={stage} className="relative z-10 flex items-start gap-4 md:flex-col md:items-center">
                {/* Node */}
                <div className={cn(
                  "flex h-14 w-14 shrink-0 items-center justify-center rounded-full border-2 bg-surface transition-all duration-500",
                  isActive ? "border-accent shadow-[0_0_20px_rgba(67,56,202,0.3)] scale-110" : 
                  isCompleted ? "border-ink bg-ink text-bg" : "border-line text-subtle"
                )}>
                  {isCompleted ? <Check className="h-5 w-5" /> : 
                   isActive ? <Loader2 className="h-5 w-5 animate-spin text-accent" /> : 
                   <span className="text-sm font-medium">{i + 1}</span>}
                </div>
                
                {/* Label */}
                <div className="pt-3 md:pt-0 md:text-center">
                  <p className={cn(
                    "text-sm font-medium transition-colors duration-500",
                    isActive ? "text-accent" : isCompleted ? "text-ink" : "text-subtle"
                  )}>
                    {stage}
                  </p>
                  
                  {/* Detailed agent status for Data Gathering stage */}
                  {i === 3 && run.steps.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-2 md:justify-center">
                      {run.steps.slice(0, 4).map(step => {
                        const Icon = ICONS[step.key];
                        return (
                          <div key={step.key} className={cn(
                            "flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px]",
                            step.status === "done" ? "border-line bg-surface text-ink-2" :
                            step.status === "active" ? "border-accent/40 bg-accent/5 text-accent animate-pulse" :
                            "border-line-soft text-subtle opacity-50"
                          )}>
                            <Icon className="h-3 w-3" />
                            {AGENTS[step.key].title}
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {/* Processing Time */}
                  {isCompleted && i === 6 && run.totalMs && (
                    <p className="mt-2 text-xs text-muted">Completed in {duration(run.totalMs)}</p>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
