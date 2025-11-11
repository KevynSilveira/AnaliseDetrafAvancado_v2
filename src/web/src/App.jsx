// App com navegação
import React from "react";
import { Routes, Route, NavLink } from "react-router-dom";
import Validacao from "./pages/Validacao";
import Imports from "./pages/Imports";
import Reports from "./pages/Reports";
import Configuracoes from "./pages/Configuracoes";

export default function App() {
  return (
    <div className="min-h-screen">
      <nav className="sticky top-0 z-50 bg-mid/80 backdrop-blur border-b border-neutral-800">
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-2xl font-bold text-primary">DETRAF</span>
            <span className="text-sm text-gray-300">Conferência V2</span>
          </div>
          <div className="flex gap-4">
            <NavLink to="/" end className={({isActive}) => isActive ? "text-white" : "link"}>Validação</NavLink>
            <NavLink to="/importacoes" className={({isActive}) => isActive ? "text-white" : "link"}>Importações</NavLink>
            <NavLink to="/relatorios" className={({isActive}) => isActive ? "text-white" : "link"}>Relatórios</NavLink>
            <NavLink to="/configuracoes" className={({isActive}) => isActive ? "text-white" : "link"}>Configurações</NavLink>
          </div>
        </div>
      </nav>

      <main className="max-w-6xl mx-auto p-4 md:p-8">
        <Routes>
          <Route path="/" element={<Validacao />} />
          <Route path="/importacoes" element={<Imports />} />
          <Route path="/relatorios" element={<Reports />} />
          <Route path="/configuracoes" element={<Configuracoes />} />
        </Routes>
      </main>
    </div>
  );
}
