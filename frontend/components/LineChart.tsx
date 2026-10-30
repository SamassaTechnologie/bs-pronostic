/** Petit graphique SVG sans dépendance (léger pour mobile). */
export function LineChart({ points, format, zero = false, label }: { points: { x: string; y: number }[]; format: (v: number) => string; zero?: boolean; label: string }) {
  if (points.length < 2) return <p className="text-sm text-steel">Pas encore assez de pronostics réglés pour tracer l&apos;évolution.</p>;
  const W = 340, H = 150, P = 28;
  const ys = points.map((p) => p.y);
  let min = Math.min(...ys), max = Math.max(...ys);
  if (zero) { min = Math.min(min, 0); max = Math.max(max, 0); }
  if (max === min) { max += 1; min -= 1; }
  const x = (i: number) => P + (i * (W - P - 6)) / (points.length - 1);
  const y = (v: number) => 8 + ((max - v) * (H - 30)) / (max - min);
  const d = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.y).toFixed(1)}`).join(" ");
  const last = points[points.length - 1];
  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`${label} : dernière valeur ${format(last.y)}`}>
        {[max, (max + min) / 2, min].map((v) => (
          <g key={v}>
            <line x1={P} x2={W - 6} y1={y(v)} y2={y(v)} stroke="#d6dee9" strokeWidth="1" />
            <text x={P - 4} y={y(v) + 3} textAnchor="end" fontSize="9" fill="#4a5b75">{format(v)}</text>
          </g>
        ))}
        {zero && <line x1={P} x2={W - 6} y1={y(0)} y2={y(0)} stroke="#0b1d3a" strokeWidth="1" strokeDasharray="3 3" />}
        <path d={d} fill="none" stroke="#12a150" strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" />
        <circle cx={x(points.length - 1)} cy={y(last.y)} r="3.5" fill="#12a150" />
        <text x={P} y={H - 4} fontSize="9" fill="#4a5b75">{points[0].x}</text>
        <text x={W - 6} y={H - 4} fontSize="9" fill="#4a5b75" textAnchor="end">{last.x}</text>
      </svg>
      <figcaption className="sr-only">{label}</figcaption>
    </figure>
  );
}
