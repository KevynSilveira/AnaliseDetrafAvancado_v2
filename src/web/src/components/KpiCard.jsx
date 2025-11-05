// Cartão de KPI
export default function KpiCard({ label, value, subtitle }) {
  return (
    <div className="card p-5">
      <div className="text-sm text-gray-400">{label}</div>
      <div className="mt-1 text-3xl font-bold">{value}</div>
      {subtitle && <div className="mt-1 text-xs text-gray-400">{subtitle}</div>}
    </div>
  );
}
