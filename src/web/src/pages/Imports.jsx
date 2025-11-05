// Importações com API, sem hardcode
import React, { useEffect, useState } from "react";
import { api } from "../lib/api";

export default function Imports() {
  const [file, setFile] = useState(null);
  const [items, setItems] = useState([]);

  const load = async () => {
    const data = await api.get("/api/imports");
    setItems(data);
  };

  useEffect(() => { load(); }, []);

  const handleUpload = async () => {
    if (!file) return;
    const res = await api.upload("/api/imports", file, {});
    const id = res.id;

    const timer = setInterval(async () => {
      const s = await api.get(`/api/imports/${id}`);
      setItems(prev => {
        const copy = [...prev];
        const ix = copy.findIndex(i => i.id === id);
        if (ix >= 0) copy[ix] = s;
        else copy.unshift(s);
        return copy;
      });
      if (s && (s.status === "concluido" || s.status === "erro")) clearInterval(timer);
    }, 1000);
  };

  return (
    <div className="space-y-6">
      <div className="card p-6">
        <div className="text-lg font-semibold mb-3 text-primary">Importar Arquivo DETRAF / CDR</div>
        <div className="flex flex-col md:flex-row gap-3">
          <input type="file" accept=".txt,.csv"
                 onChange={e => setFile(e.target.files[0])}
                 className="border border-neutral-700 bg-dark text-gray-300 p-2 rounded-lg w-full" />
          <button className="btn" onClick={handleUpload}>Importar</button>
        </div>
      </div>

      <div className="card p-6">
        <div className="text-lg font-semibold mb-3 text-primary">Histórico de Importações</div>
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="bg-neutral-800 text-gray-200">
              <tr>
                <th className="p-2 text-left">Arquivo</th>
                <th className="p-2 text-left">Data</th>
                <th className="p-2 text-left">Status</th>
                <th className="p-2 text-left">Progresso</th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 && (
                <tr><td colSpan="4" className="p-4 text-center text-gray-400">Nenhuma importação ainda.</td></tr>
              )}
              {items.map(row => (
                <tr key={row.id} className="border-t border-neutral-800">
                  <td className="p-2">{row.arquivo}</td>
                  <td className="p-2">{row.data_hora}</td>
                  <td className="p-2">{row.status}</td>
                  <td className="p-2">
                    <div className="w-full bg-neutral-800 rounded-full h-3">
                      <div className={row.progresso < 100 ? "h-3 bg-primary rounded-full" : "h-3 bg-green-600 rounded-full"} style={{width: `${row.progresso}%`}}></div>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
