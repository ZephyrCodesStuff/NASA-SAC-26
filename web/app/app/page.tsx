"use client";

import dynamic from "next/dynamic";
import { Loader2 } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { AuthScreen } from "@/components/auth-screen";

const MapWorkbench = dynamic(
  () => import("@/components/map-workbench").then((m) => m.MapWorkbench),
  {
    ssr: false,
    loading: () => (
      <div className="h-dvh w-full flex items-center justify-center bg-[#faf9f5] text-[#6b675f] gap-2 text-xs font-mono">
        <Loader2 className="h-4 w-4 animate-spin text-[#20808d]" />
        Loading map workbench…
      </div>
    ),
  }
);

export default function HomePage() {
  const { user, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="h-dvh w-full flex items-center justify-center bg-[#faf9f5] text-[#6b675f] gap-2 text-xs font-mono">
        <Loader2 className="h-4 w-4 animate-spin text-[#20808d]" />
        Restoring session…
      </div>
    );
  }

  if (!user) {
    return <AuthScreen />;
  }

  return <MapWorkbench />;
}
