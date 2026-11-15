import React, { Suspense } from "react";
import { Loader2 } from "lucide-react";
import { PlotDetailGate } from "@/components/plot-detail-gate";

async function PlotDetailResolver({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <PlotDetailGate plotId={id} />;
}

export default function PlotDetailPage({ params }: { params: Promise<{ id: string }> }) {
  return (
    <Suspense
      fallback={
        <div className="h-dvh w-full flex items-center justify-center bg-[#faf9f5] text-[#6b675f] gap-2 text-xs font-mono">
          <Loader2 className="h-4 w-4 animate-spin text-[#20808d]" />
          Loading plot…
        </div>
      }
    >
      <PlotDetailResolver params={params} />
    </Suspense>
  );
}
