// Gráfico pizza
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, Legend } from "recharts";
const COLORS = ["#22c55e", "#eab308", "#ef4444"];
export default function ChartPie({ data }) {
  return (
    <div className="card p-4 h-80">
      <div className="text-sm text-gray-300 mb-2">Classificação DETRAF</div>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={data} dataKey="value" nameKey="name" innerRadius={60} outerRadius={90}>
            {data.map((e, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
          </Pie>
          <Tooltip /><Legend />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
