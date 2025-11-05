// Gráfico barras
import { BarChart, Bar, XAxis, YAxis, ResponsiveContainer, Tooltip } from "recharts";
export default function ChartBar({ data }) {
  return (
    <div className="card p-4 h-80">
      <div className="text-sm text-gray-300 mb-2">Volume por Descritor</div>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data}>
          <XAxis dataKey="name" tick={{ fill: '#9ca3af' }} />
          <YAxis tick={{ fill: '#9ca3af' }} />
          <Tooltip />
          <Bar dataKey="value" fill="#d90429" radius={[6,6,0,0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
