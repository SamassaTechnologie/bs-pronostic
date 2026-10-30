export default function Loading() {
  return (
    <div aria-busy="true" aria-label="Chargement" className="animate-pulse space-y-3 pt-1">
      <div className="h-7 w-2/3 rounded-lg bg-line/70" />
      <div className="h-4 w-1/2 rounded bg-line/60" />
      <div className="grid grid-cols-2 gap-2.5 pt-2">
        {[0, 1, 2, 3].map((i) => <div key={i} className="h-20 rounded-xl bg-white" />)}
      </div>
      {[0, 1, 2].map((i) => <div key={i} className="h-40 rounded-xl bg-white" />)}
    </div>
  );
}
