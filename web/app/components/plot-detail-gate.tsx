"use client";

import React from "react";
import { Loader2 } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { AuthScreen } from "@/components/auth-screen";
import { PlotWorkspace } from "@/components/plot-workspace";

export function PlotDetailGate({ plotId }: { plotId: string }) {
  const { user, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="h-screen w-screen flex items-center justify-center bg-[#faf9f5] text-[#6b675f] gap-2 text-xs font-mono">
        <Loader2 className="h-4 w-4 animate-spin text-[#20808d]" />
        Restoring session…
      </div>
    );
  }

  if (!user) {
    return <AuthScreen />;
  }

  return <PlotWorkspace plotId={plotId} />;
}
