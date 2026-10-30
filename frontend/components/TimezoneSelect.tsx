"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { TIMEZONES } from "@/lib/format";

export function TimezoneSelect({ current }: { current: string }) {
  const router = useRouter();
  const [tz, setTz] = useState(current);
  const [saved, setSaved] = useState(false);
  const options = TIMEZONES.some((t) => t.value === current) ? TIMEZONES : [{ value: current, label: current }, ...TIMEZONES];
  return (
    <div>
      <label htmlFor="tz" className="text-xs text-steel">Fuseau horaire d&apos;affichage</label>
      <select
        id="tz"
        value={tz}
        onChange={(e) => {
          setTz(e.target.value);
          document.cookie = `sam_tz=${encodeURIComponent(e.target.value)}; path=/; max-age=31536000; samesite=lax`;
          setSaved(true);
          router.refresh();
        }}
        className="mt-1 w-full rounded-lg border border-line bg-white px-3 py-2.5 text-sm"
      >
        {options.map((t) => (
          <option key={t.value} value={t.value}>{t.label}</option>
        ))}
      </select>
      {saved && <p className="mt-1 text-xs text-pitch-deep">Fuseau enregistré sur cet appareil.</p>}
    </div>
  );
}
