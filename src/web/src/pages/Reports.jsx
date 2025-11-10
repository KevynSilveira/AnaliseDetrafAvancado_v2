import React, { useEffect, useMemo, useState } from "react";
import { api, API_BASE } from "../lib/api";

const formatarData = (valor) => {
  if (!valor) return "-";
  try {
    return new Date(valor).toLocaleString("pt-BR");
  } catch (_erro) {
    return valor;
  }
};

const extrairNomeArquivo = (header) => {
  if (!header) return null;
  const match = /filename\s*=\s*"?([^";]+)"?/i.exec(header);
  return match ? match[1] : null;
};

export default function Reports() {
  const [importacoes, setImportacoes] = useState([]);
  const [selecionada, setSelecionada] = useState("");
  const [mensagem, setMensagem] = useState("");
  const [processando, setProcessando] = useState(false);

  useEffect(() => {
    carregarImportacoes();
  }, []);

  const importarSelecionada = useMemo(
    () => importacoes.find((item) => String(item.id) === String(selecionada)),
    [importacoes, selecionada]
  );

  const carregarImportacoes = async () => {
    try {
      const resposta = await api.get("/api/imports");
      const apenasDetraf = (resposta || []).filter((item) => item.tipo_arquivo === "DETRAF");
      setImportacoes(apenasDetraf);
      if (apenasDetraf.length && !selecionada) {
        setSelecionada(String(apenasDetraf[0].id));
      }
      if (!apenasDetraf.length) {
        setMensagem("Nenhuma importação DETRAF disponível.");
      } else {
        setMensagem("");
      }
    } catch (erro) {
      setMensagem(erro.message || "Não foi possível carregar as importações.");
    }
  };

  const baixarCsv = async () => {
    if (!selecionada) {
      setMensagem("Selecione uma importação antes de exportar.");
      return;
    }
    try {
      setProcessando(true);
      setMensagem("");
      const resposta = await fetch(
        `${API_BASE}/api/reports/detraf_csv?id_importacao=${selecionada}`
      );
      if (!resposta.ok) {
        const texto = await resposta.text();
        throw new Error(texto || `HTTP ${resposta.status}`);
      }
      const blob = await resposta.blob();
      const url = window.URL.createObjectURL(blob);
      const nome =
        extrairNomeArquivo(resposta.headers.get("content-disposition")) ||
        `batimento_${selecionada}.csv`;
      const link = document.createElement("a");
      link.href = url;
      link.download = nome;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
      setMensagem("CSV gerado com sucesso.");
    } catch (erro) {
      setMensagem(erro.message || "Falha ao gerar o CSV.");
    } finally {
      setProcessando(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="card p-6 space-y-5">
        <div>
          <div className="text-lg font-semibold text-primary">Exportar DETRAF</div>
          <p className="text-xs text-gray-400">
            Escolha uma importação concluída para gerar o arquivo de batimento em CSV.
          </p>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <label className="mb-2 block text-sm font-medium text-gray-300">
              Importação
            </label>
            <select
              className="w-full rounded-lg border border-neutral-700 bg-dark p-2 text-gray-200 focus:outline-none focus:ring-2 focus:ring-primary/40"
              value={selecionada}
              onChange={(e) => setSelecionada(e.target.value)}
            >
              {!importacoes.length && <option value="">Nenhum arquivo disponível</option>}
              {importacoes.map((item) => (
                <option key={item.id} value={item.id}>
                  {`${item.nome_cliente || "Cliente"} • ${item.nome_arquivo}`} ({
                    formatarData(item.data_importacao)
                  })
                </option>
              ))}
            </select>
          </div>

          {importarSelecionada && (
            <div className="rounded-lg border border-neutral-700 bg-neutral-900 p-4 text-xs text-gray-300 space-y-1">
              <div>
                <span className="font-semibold text-gray-200">Período:</span> {" "}
                {importarSelecionada.periodo_inicial || "-"} até {" "}
                {importarSelecionada.periodo_final || "-"}
              </div>
              <div>
                <span className="font-semibold text-gray-200">EOT credora:</span> {" "}
                {importarSelecionada.eqt_credora || "-"}
              </div>
              <div>
                <span className="font-semibold text-gray-200">EOT devedora:</span> {" "}
                {importarSelecionada.eqt_devedora || "-"}
              </div>
              <div>
                <span className="font-semibold text-gray-200">Registros:</span> {" "}
                {importarSelecionada.linhas_processadas || 0}
              </div>
            </div>
          )}
        </div>

        <div className="flex items-center gap-3">
          <button className="btn" onClick={baixarCsv} disabled={processando || !importacoes.length}>
            {processando ? "Gerando..." : "Exportar CSV"}
          </button>
          <button className="text-sm text-gray-300 hover:text-primary" onClick={carregarImportacoes}>
            Recarregar lista
          </button>
        </div>

        {mensagem && (
          <div className="rounded-lg border border-primary/40 bg-primary/10 p-3 text-sm text-primary">
            {mensagem}
          </div>
        )}
      </div>
    </div>
  );
}
