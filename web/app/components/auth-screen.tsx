"use client";

import React, { useState } from "react";
import { Sprout, Eye, Pencil, ArrowRight, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { useAuth } from "@/lib/auth-context";
import { WEB_API_URL } from "@/lib/api";

export function AuthScreen() {
  const { login, register, loginDemo } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"farm_admin" | "viewer">("farm_admin");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password) {
      toast.error("Email and password are required.");
      return;
    }
    if (mode === "register" && !name.trim()) {
      toast.error("Please enter your name.");
      return;
    }
    setSubmitting(true);
    try {
      if (mode === "login") {
        await login(email.trim(), password);
        toast.success("Signed in");
      } else {
        await register(email.trim(), name.trim(), password, role);
        toast.success("Account created");
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Authentication failed");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDemo = async (kind: "farmer" | "viewer") => {
    setSubmitting(true);
    try {
      await loginDemo(kind);
      toast.success(kind === "farmer" ? "Signed in as Marco Rossi" : "Signed in as Elena Bianchi");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Demo login failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen grid grid-cols-1 lg:grid-cols-12 bg-[#faf9f5] text-[#1f1915]">
      {/* Left editorial brief */}
      <div className="lg:col-span-7 flex flex-col justify-between p-8 lg:p-14 border-b lg:border-b-0 lg:border-r border-[#e7e5e0] bg-[#fdfbfa]">
        <div className="flex items-center gap-3">
          <div className="h-9 w-9 rounded-lg bg-[#20808d] text-white flex items-center justify-center">
            <Sprout className="h-5 w-5" />
          </div>
          <div>
            <p className="font-serif text-base font-semibold tracking-tight">
              Turin Crop Rotation Planner
            </p>
            <p className="text-[11px] font-mono text-[#6b675f]">
              NASA SPACE APPS CHALLENGE 2026
            </p>
          </div>
        </div>

        <div className="my-12 lg:my-0 max-w-xl space-y-5">
          <Badge variant="outline" className="font-mono text-[11px]">
            FAO-56 · RUSLE · NASA POWER / SMAP · AdE CATASTO
          </Badge>
          <h1 className="font-serif text-3xl lg:text-4xl font-semibold tracking-tight leading-[1.15]">
            Deterministic 3-year crop rotations, grounded in satellite &amp; field telemetry.
          </h1>
          <p className="text-sm text-[#6b675f] leading-relaxed">
            Select real cadastral parcels or draw field boundaries around Turin and across Europe,
            inspect 24-period seasonal water and erosion balances, and pair live ESP32 soil probes
            against NASA Earth observations.
          </p>

          <div className="border-y border-[#e7e5e0] py-3 flex flex-wrap gap-x-6 gap-y-2 text-xs font-mono text-[#6b675f]">
            <span>24 × 15-day periods</span>
            <span>Catasto WFS / WMS</span>
            <span>Live ESP32 Ground Truth</span>
          </div>
        </div>

        <div className="text-[11px] font-mono text-[#6b675f] flex items-center justify-between">
          <span>API: {WEB_API_URL}</span>
          <span>Deterministic math first · AI for translation</span>
        </div>
      </div>

      {/* Right auth panel */}
      <div className="lg:col-span-5 flex items-center justify-center p-8 lg:p-12">
        <div className="w-full max-w-sm space-y-6">
          <div className="flex rounded-lg border border-[#e7e5e0] bg-[#f5f4ef] p-1">
            <button
              type="button"
              onClick={() => setMode("login")}
              className={`flex-1 py-1.5 text-xs font-medium rounded-md transition ${
                mode === "login"
                  ? "bg-white text-[#1f1915] shadow-xs"
                  : "text-[#6b675f] hover:text-[#1f1915]"
              }`}
            >
              Sign In
            </button>
            <button
              type="button"
              onClick={() => setMode("register")}
              className={`flex-1 py-1.5 text-xs font-medium rounded-md transition ${
                mode === "register"
                  ? "bg-white text-[#1f1915] shadow-xs"
                  : "text-[#6b675f] hover:text-[#1f1915]"
              }`}
            >
              Create Account
            </button>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            {mode === "register" && (
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-[#1f1915]">Full Name</label>
                <Input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Marco Rossi"
                  disabled={submitting}
                />
              </div>
            )}

            <div className="space-y-1.5">
              <label className="text-xs font-medium text-[#1f1915]">Email</label>
              <Input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="marco@turinfarm.it"
                disabled={submitting}
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-medium text-[#1f1915]">Password</label>
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                disabled={submitting}
              />
            </div>

            {mode === "register" && (
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-[#1f1915]">Role</label>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => setRole("farm_admin")}
                    className={`flex items-center justify-center gap-1.5 py-2 px-3 rounded-md border text-xs font-medium transition ${
                      role === "farm_admin"
                        ? "border-[#20808d] bg-[#20808d]/10 text-[#20808d]"
                        : "border-[#e7e5e0] bg-white text-[#6b675f]"
                    }`}
                  >
                    <Pencil className="h-3.5 w-3.5" />
                    Farm Editor
                  </button>
                  <button
                    type="button"
                    onClick={() => setRole("viewer")}
                    className={`flex items-center justify-center gap-1.5 py-2 px-3 rounded-md border text-xs font-medium transition ${
                      role === "viewer"
                        ? "border-[#20808d] bg-[#20808d]/10 text-[#20808d]"
                        : "border-[#e7e5e0] bg-white text-[#6b675f]"
                    }`}
                  >
                    <Eye className="h-3.5 w-3.5" />
                    Viewer
                  </button>
                </div>
              </div>
            )}

            <Button type="submit" className="w-full gap-1.5" disabled={submitting}>
              {submitting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <>
                  {mode === "login" ? "Sign In" : "Create Account"}
                  <ArrowRight className="h-4 w-4" />
                </>
              )}
            </Button>
          </form>

          <div className="relative">
            <div className="absolute inset-0 flex items-center">
              <span className="w-full border-t border-[#e7e5e0]" />
            </div>
            <div className="relative flex justify-center text-[11px] uppercase font-mono">
              <span className="bg-[#faf9f5] px-2 text-[#6b675f]">Quick Demo Access</span>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-2">
            <Button
              type="button"
              variant="outline"
              className="justify-between text-xs h-9"
              disabled={submitting}
              onClick={() => handleDemo("farmer")}
            >
              <span className="flex items-center gap-2">
                <Pencil className="h-3.5 w-3.5 text-[#20808d]" />
                Marco Rossi (Farm Admin · Editor)
              </span>
              <span className="font-mono text-[10px] text-[#6b675f]">demo</span>
            </Button>
            <Button
              type="button"
              variant="outline"
              className="justify-between text-xs h-9"
              disabled={submitting}
              onClick={() => handleDemo("viewer")}
            >
              <span className="flex items-center gap-2">
                <Eye className="h-3.5 w-3.5 text-[#6b675f]" />
                Elena Bianchi (Agronomist · Viewer)
              </span>
              <span className="font-mono text-[10px] text-[#6b675f]">demo</span>
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
