"use client";

import { useEffect, useState } from "react";
import { Sprout, Satellite, Layers, ArrowRight, CheckCircle2, AlertCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { WEB_API_URL, webApi } from "@/lib/api";

export default function HomePage() {
  const [apiStatus, setApiStatus] = useState<"checking" | "online" | "offline">("checking");

  useEffect(() => {
    webApi
      .health()
      .then(() => setApiStatus("online"))
      .catch(() => setApiStatus("offline"));
  }, []);

  return (
    <div className="min-h-screen flex flex-col bg-[#faf9f5] text-[#1f1915]">
      {/* Warm editorial top bar */}
      <header className="border-b border-[#e7e5e0] bg-[#fdfbfa]/90 backdrop-blur px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="h-8 w-8 rounded-lg bg-[#20808d] text-white flex items-center justify-center shadow-sm">
            <Sprout className="h-4 w-4" />
          </div>
          <div>
            <h1 className="font-serif text-base font-semibold tracking-tight text-[#1f1915]">
              Turin Crop Rotation Planner
            </h1>
            <p className="text-[11px] text-[#6b675f]">NASA Space Apps Challenge 2026</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {apiStatus === "checking" && <Badge variant="secondary">Checking web-api…</Badge>}
          {apiStatus === "online" && (
            <Badge variant="success" className="gap-1">
              <CheckCircle2 className="h-3 w-3" />
              web-api online
            </Badge>
          )}
          {apiStatus === "offline" && (
            <Badge variant="warning" className="gap-1">
              <AlertCircle className="h-3 w-3" />
              web-api unreachable
            </Badge>
          )}
          <a href="http://127.0.0.1:8080" target="_blank" rel="noreferrer">
            <Button variant="outline" size="sm">
              Legacy NiceGUI App
            </Button>
          </a>
        </div>
      </header>

      <main className="flex-1 max-w-5xl w-full mx-auto px-6 py-10 space-y-6">
        <div className="space-y-2">
          <Badge variant="outline" className="font-mono text-[11px]">
            Next.js 16 · shadcn/ui · Tailwind v4
          </Badge>
          <h2 className="font-serif text-3xl font-semibold tracking-tight text-[#1f1915]">
            Resilient 3-year crop rotations, grounded in NASA Earth observations.
          </h2>
          <p className="text-sm text-[#6b675f] max-w-2xl">
            Bootstrapped with the warm editorial design system and connected to{" "}
            <code className="font-mono text-xs bg-[#f5f4ef] px-1.5 py-0.5 rounded border border-[#e7e5e0]">
              {WEB_API_URL}
            </code>
            .
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm">web-api</CardTitle>
                <Layers className="h-4 w-4 text-[#20808d]" />
              </div>
              <CardDescription>FastAPI + PocketBase proxy</CardDescription>
            </CardHeader>
            <CardContent className="text-xs text-[#6b675f] space-y-2">
              <p>Handles auth, farms, grouped Catasto plots, and soil override flags.</p>
              <a
                href={`${WEB_API_URL.replace(/\/api$/, "")}/docs`}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-[#20808d] font-medium hover:underline"
              >
                OpenAPI Docs <ArrowRight className="h-3 w-3" />
              </a>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm">data-api</CardTitle>
                <Satellite className="h-4 w-4 text-[#20808d]" />
              </div>
              <CardDescription>9 NASA & ISRIC sources (:8070)</CardDescription>
            </CardHeader>
            <CardContent className="text-xs text-[#6b675f]">
              Populates fresh plot telemetry snapshots without overwriting farmer-verified lab overrides.
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm">projection_api</CardTitle>
                <Sprout className="h-4 w-4 text-[#4f9d69]" />
              </div>
              <CardDescription>Analytics & rotation projections</CardDescription>
            </CardHeader>
            <CardContent className="text-xs text-[#6b675f]">
              Receives merged satellite + override payloads for deterministic agronomic projections.
            </CardContent>
          </Card>
        </div>
      </main>
    </div>
  );
}
