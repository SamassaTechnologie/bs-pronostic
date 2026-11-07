import type { ReactNode } from "react";

/** Catégorie pliable du tableau de bord (sans JavaScript : élément <details> natif, accessible au clavier). */
export function Category({ id, title, subtitle, icon, badge, tone = "bg-night text-white", open = true, children }: {
  id: string; title: string; subtitle?: string; icon: string; badge?: ReactNode; tone?: string; open?: boolean; children: ReactNode;
}) {
  return (
    <details id={id} open={open} className="group mt-4 overflow-hidden rounded-2xl border border-line bg-white shadow-[0_1px_0_rgba(15,23,42,0.04)]">
      <summary className="flex cursor-pointer list-none items-center gap-3 px-4 py-3.5 [&::-webkit-details-marker]:hidden">
        <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${tone}`}>
          <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d={icon} /></svg>
        </span>
        <span className="min-w-0 flex-1">
          <span className="block font-display text-[16px] font-bold leading-tight text-night">{title}</span>
          {subtitle && <span className="block truncate text-[12px] text-steel">{subtitle}</span>}
        </span>
        {badge}
        <svg viewBox="0 0 24 24" className="h-5 w-5 shrink-0 text-steel transition-transform group-open:rotate-180" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden><path d="M6 9l6 6 6-6" /></svg>
      </summary>
      <div className="border-t border-line bg-mist/40 px-3 pb-3 pt-3">{children}</div>
    </details>
  );
}

/** Sous-catégorie pliable à l'intérieur d'une catégorie. */
export function SubCategory({ title, hint, count, open = false, action, children }: {
  title: ReactNode; hint?: string; count?: number | string; open?: boolean; action?: ReactNode; children: ReactNode;
}) {
  return (
    <details open={open} className="group/sub mt-2 overflow-hidden rounded-xl border border-line bg-white first:mt-0">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3.5 py-2.5 [&::-webkit-details-marker]:hidden">
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[14px] font-bold text-night">{title}</span>
          {hint && <span className="block truncate text-[11.5px] text-steel">{hint}</span>}
        </span>
        {count !== undefined && <span className="shrink-0 rounded-md bg-mist px-1.5 py-0.5 text-[11px] font-bold text-steel">{count}</span>}
        <svg viewBox="0 0 24 24" className="h-4 w-4 shrink-0 text-steel transition-transform group-open/sub:rotate-180" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden><path d="M6 9l6 6 6-6" /></svg>
      </summary>
      <div className="border-t border-line px-3 pb-3 pt-2.5">
        {children}
        {action && <div className="mt-2 text-right">{action}</div>}
      </div>
    </details>
  );
}
