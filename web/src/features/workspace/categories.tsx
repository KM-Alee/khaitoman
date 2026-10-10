import type { ReactNode } from "react";
import { Clock3, Droplets, Tractor, Waves, Wrench } from "lucide-react";
import type { ActionCategory } from "@/lib/api/types";

/** The five action categories (PRD §6.2) with plain names. */
export const CATEGORY_META: Record<ActionCategory, { label: string; plural: string; precise: string; icon: ReactNode }> = {
  timing: { label: "Better water timing", plural: "timing changes", precise: "Timing with existing assets", icon: <Clock3 size={14} aria-hidden /> },
  leveling: { label: "Land levelling", plural: "fields levelled", precise: "Leveling service", icon: <Tractor size={14} aria-hidden /> },
  pond: { label: "New farm pond", plural: "new ponds", precise: "New pond", icon: <Waves size={14} aria-hidden /> },
  shared_repair: { label: "Canal repair", plural: "canal repairs", precise: "Shared repair", icon: <Wrench size={14} aria-hidden /> },
  pump_supplement: { label: "Extra pumping", plural: "pump supplements", precise: "Existing-pump supplement", icon: <Droplets size={14} aria-hidden /> },
};
