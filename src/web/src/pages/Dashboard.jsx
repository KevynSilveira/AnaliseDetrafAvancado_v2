// Dashboard consome API
import React, { useEffect, useState } from "react";
import KpiCard from "../components/KpiCard";
import ChartPie from "../components/ChartPie";
import ChartBar from "../components/ChartBar";
import { api } from "../lib/api";

export default function Dashboard() {
  const [kpis, setKpis] = useState(null);
  const [pie, setPie] = useState([]);
  const [bars, setBars] = useState([]);
  const [err, setErr] = useState(null);

  useEffect(() => {
    Promise.all([
      api.get("/api/kpis"),
      api.get("/api/classificacao"),
      api.get("/api/volumes")
    ]).then(([k, p, b]) => {
      setKpis(k);
      setPie(p);
      setBars(b);
    }).catch(e => setErr(e.message));
  }, []);

  if (err) return <div className="text-red-400">Erro: {err}</div>;
  if (!kpis) return <div className="text-gray-300">Carregando...</div>;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <KpiCard label="Registros analisados" value={kpis.total?.toLocaleString('pt-BR') || 0} />
        <KpiCard label="% Conferido" value={(kpis.percent_conferido ?? 0) + '%'} />
        <KpiCard label="% Divergente" value={(kpis.percent_divergente ?? 0) + '%'} />
        <KpiCard label="% Perdido" value={(kpis.percent_perdido ?? 0) + '%'} />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <ChartPie data={pie} />
        <ChartBar data={bars} />
      </div>
    </div>
  );
}
