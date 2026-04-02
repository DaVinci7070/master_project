"use client";

import { usePathname } from "next/navigation";
import { EmergencyStop, SystemReset } from "@/components/dashboard";
import { AutoApplyToggle } from "@/components/settings/auto-apply-toggle";

const routeTitles: Record<string, string> = {
  "/": "Dashboard",
  "/execution": "Execution",
  "/topology": "Topology",
  "/agents": "Agents",
  "/skills": "Skills",
  "/prompts": "Prompts",
};

export function Header() {
  const pathname = usePathname();
  const title = routeTitles[pathname] || "Lumari";

  return (
    <header className="flex h-14 items-center justify-between border-b bg-card px-4 md:px-6">
      <div className="flex items-center gap-4">
        {/* Spacer for mobile menu button */}
        <div className="w-10 md:hidden" />
        <h1 className="text-lg font-semibold">{title}</h1>
      </div>

      <div className="flex items-center gap-4">
        <AutoApplyToggle />
        <SystemReset />
        <EmergencyStop />
      </div>
    </header>
  );
}
