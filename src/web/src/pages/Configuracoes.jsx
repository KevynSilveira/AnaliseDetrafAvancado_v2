import React, { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";

const formatarBytes = (valor) => {
  if (!Number.isFinite(valor) || valor <= 0) return "0 B";
  const unidades = ["B", "KB", "MB", "GB", "TB"];
  let tamanho = valor;
  let indice = 0;
  while (tamanho >= 1024 && indice < unidades.length - 1) {
    tamanho /= 1024;
    indice += 1;
  }
  return `${tamanho.toFixed(indice === 0 ? 0 : 2)} ${unidades[indice]}`;
};

const formatarDescricaoImportacao = (item) => {
  const cliente = item.nome_cliente || "Cliente";
  const tipo = item.tipo_arquivo || "-";
  const arquivo = item.nome_arquivo || "arquivo";
  return `${cliente} • ${tipo} • ${arquivo}`;
};

export default function Configuracoes() {
  const [clientes, setClientes] = useState([]);
  const [importacoes, setImportacoes] = useState([]);
  const [resumo, setResumo] = useState(null);

  const [selecionarClientes, setSelecionarClientes] = useState([]);
  const [selecionarImportacoes, setSelecionarImportacoes] = useState([]);
  const [logsDias, setLogsDias] = useState("");
  const [logsManter, setLogsManter] = useState("");
  const [removerControle, setRemoverControle] = useState(false);
  const [targets, setTargets] = useState({ LOGS: true, TMP: true, DETRAF: true, CDR: false });
  const [mensagem, setMensagem] = useState("");
  const [resultadoResumo, setResultadoResumo] = useState([]);
  const [processando, setProcessando] = useState(false);

  const importacoesAtivas = useMemo(
    () => (importacoes || []).filter((item) => item.status !== "REMOVIDO"),
    [importacoes]
  );

  const mapaImportacoesPorId = useMemo(() => {
    const mapa = new Map();
    importacoesAtivas.forEach((item) => {
      mapa.set(String(item.id), item);
    });
    return mapa;
  }, [importacoesAtivas]);

  const idsSelecionados = useMemo(
    () =>
      selecionarImportacoes
        .map((valor) => Number(valor))
        .filter((numero) => Number.isFinite(numero)),
    [selecionarImportacoes]
  );

  const idsSelecionadosPorTipo = useMemo(() => {
    const agrupado = { DETRAF: [], CDR: [] };
    selecionarImportacoes.forEach((texto) => {
      const registro = mapaImportacoesPorId.get(texto);
      if (!registro) return;
      const numero = Number(texto);
      if (!Number.isFinite(numero)) return;
      const tipo = (registro.tipo_arquivo || "").toUpperCase();
      if (tipo === "DETRAF" || tipo === "CDR") {
        agrupado[tipo].push(numero);
      }
    });
    return agrupado;
  }, [selecionarImportacoes, mapaImportacoesPorId]);

  const importacoesFiltradas = useMemo(() => {
    if (!selecionarClientes.length) return importacoesAtivas;
    const clientesSelecionados = new Set(selecionarClientes.map(String));
    return importacoesAtivas.filter((item) =>
      !item.id_cliente || clientesSelecionados.has(String(item.id_cliente))
    );
  }, [importacoesAtivas, selecionarClientes]);

  useEffect(() => {
    carregarClientes();
    carregarImportacoes();
    carregarResumo();
  }, []);

  const clientesComImportacao = useMemo(() => {
    const ids = new Set(
      importacoesAtivas
        .map((item) => (item.id_cliente !== null && item.id_cliente !== undefined ? String(item.id_cliente) : null))
        .filter(Boolean)
    );
    if (!ids.size) return [];
    return clientes.filter((cliente) => ids.has(String(cliente.id_cliente)));
  }, [clientes, importacoesAtivas]);

  useEffect(() => {
    setSelecionarClientes((atual) =>
      atual.filter((id) => clientesComImportacao.some((cliente) => String(cliente.id_cliente) === id))
    );
  }, [clientesComImportacao]);

  useEffect(() => {
    setSelecionarImportacoes((atual) =>
      atual.filter((id) => importacoesFiltradas.some((item) => String(item.id) === id))
    );
  }, [importacoesFiltradas]);

  const carregarClientes = async () => {
    try {
      const resposta = await api.get("/api/clientes");
      setClientes(resposta || []);
    } catch (erro) {
      setMensagem(erro.message || "Falha ao carregar clientes.");
    }
  };

  const carregarImportacoes = async () => {
    try {
      const resposta = await api.get("/api/imports");
      setImportacoes(resposta || []);
    } catch (erro) {
      setMensagem(erro.message || "Falha ao carregar importações.");
    }
  };

  const carregarResumo = async () => {
    try {
      const dados = await api.get("/api/limpeza/resumo");
      setResumo(dados || {});
    } catch (erro) {
      setMensagem(erro.message || "Falha ao carregar resumo de uso.");
    }
  };

  const alternarTarget = (alvo) => {
    setTargets((atual) => ({
      ...atual,
      [alvo]: !atual[alvo],
    }));
  };

  const alternarClienteSelecionado = (id) => {
    setSelecionarClientes((atual) => {
      const texto = String(id);
      return atual.includes(texto) ? atual.filter((valor) => valor !== texto) : [...atual, texto];
    });
  };

  const alternarImportacaoSelecionada = (id) => {
    setSelecionarImportacoes((atual) => {
      const texto = String(id);
      return atual.includes(texto) ? atual.filter((valor) => valor !== texto) : [...atual, texto];
    });
  };

  const selecionados = Object.entries(targets)
    .filter(([, ativo]) => ativo)
    .map(([chave]) => chave);

  const executarLimpeza = async () => {
    if (!selecionados.length) {
      setMensagem("Selecione ao menos uma área para limpar.");
      return;
    }

    const requerImportacoes = selecionados.some((alvo) => ["TMP", "DETRAF", "CDR"].includes(alvo));
    if (requerImportacoes && idsSelecionados.length === 0) {
      setMensagem("Selecione ao menos uma importação para remover TMP/DETRAF/CDR.");
      return;
    }

    const opcoesTmp = {};
    if (idsSelecionados.length) {
      opcoesTmp.ids = idsSelecionados;
    }
    const opcoesDetraf = {};
    if (idsSelecionadosPorTipo.DETRAF.length) {
      opcoesDetraf.ids = idsSelecionadosPorTipo.DETRAF;
    }
    const opcoesCdr = {};
    if (idsSelecionadosPorTipo.CDR.length) {
      opcoesCdr.ids = idsSelecionadosPorTipo.CDR;
    }

    const payload = {
      clientes: selecionarClientes.map((valor) => Number(valor)),
      alvos: selecionados,
      remover_controle: removerControle,
      ids_importacoes: idsSelecionados,
      opcoes: {
        LOGS: {
          dias: logsDias ? Number(logsDias) : null,
          manter: logsManter ? Number(logsManter) : null,
        },
        TMP: opcoesTmp,
        DETRAF: opcoesDetraf,
        CDR: opcoesCdr,
      },
    };

    try {
      setProcessando(true);
      setMensagem("");
      const resposta = await api.post("/api/limpeza/manual", payload);
      setMensagem(resposta?.mensagem || "Limpeza concluída.");
      setResultadoResumo(resposta?.resultados || []);
      setSelecionarImportacoes([]);
      await Promise.all([carregarResumo(), carregarImportacoes()]);
    } catch (erro) {
      setMensagem(erro.message || "Falha ao executar a limpeza.");
      setResultadoResumo([]);
    } finally {
      setProcessando(false);
    }
  };

  const limparFormulario = () => {
    setSelecionarClientes([]);
    setSelecionarImportacoes([]);
    setLogsDias("");
    setLogsManter("");
    setRemoverControle(false);
    setTargets({ LOGS: true, TMP: true, DETRAF: true, CDR: false });
    setMensagem("");
  };

  return (
    <div className="space-y-6">
      <div className="card p-6 space-y-6">
        <header>
          <h2 className="text-lg font-semibold text-primary">Limpeza e manutenção</h2>
          <p className="text-xs text-gray-400 mt-1">
            Visualize o consumo atual e realize a limpeza do ambiente selecionando somente o que precisa.
          </p>
        </header>

        <div className="grid gap-4 md:grid-cols-4">
          <div className="rounded-lg border border-neutral-700 bg-neutral-900 p-4">
            <div className="text-xs text-gray-400">Logs armazenados</div>
            <div className="mt-1 text-2xl font-semibold text-primary">
              {resumo?.logs?.quantidade ?? 0}
            </div>
            <div className="text-xs text-gray-400">{formatarBytes(resumo?.logs?.tamanho_total ?? 0)}</div>
          </div>
          <div className="rounded-lg border border-neutral-700 bg-neutral-900 p-4">
            <div className="text-xs text-gray-400">Arquivos temporários</div>
            <div className="mt-1 text-2xl font-semibold text-primary">
              {resumo?.temporarios?.pendentes ?? 0}
            </div>
            <div className="text-xs text-gray-400">{formatarBytes(resumo?.temporarios?.tamanho_total ?? 0)}</div>
          </div>
          <div className="rounded-lg border border-neutral-700 bg-neutral-900 p-4">
            <div className="text-xs text-gray-400">Registros DETRAF</div>
            <div className="mt-1 text-2xl font-semibold text-primary">
              {resumo?.detraf?.total_registros ?? 0}
            </div>
          </div>
          <div className="rounded-lg border border-neutral-700 bg-neutral-900 p-4">
            <div className="text-xs text-gray-400">Tabelas CDR</div>
            <div className="mt-1 text-2xl font-semibold text-primary">
              {resumo?.cdr?.total_tabelas ?? 0}
            </div>
          </div>
        </div>

        <div className="rounded-lg border border-neutral-700 bg-neutral-900 p-5 space-y-5">
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label className="text-xs font-medium text-gray-300">Clientes</label>
              <div className="mt-2 max-h-40 space-y-2 overflow-y-auto rounded-lg border border-neutral-700 bg-dark p-3">
                {!clientesComImportacao.length && (
                  <div className="text-xs text-gray-500">Nenhum cliente com importação ativa.</div>
                )}
                {clientesComImportacao.map((cliente) => {
                  const id = String(cliente.id_cliente);
                  return (
                    <label
                      key={id}
                      className="flex items-center justify-between gap-2 rounded-md bg-neutral-800/70 px-3 py-2 text-sm text-gray-200 hover:bg-neutral-700/60"
                    >
                      <span>{cliente.nome_cliente}</span>
                      <input
                        type="checkbox"
                        checked={selecionarClientes.includes(id)}
                        onChange={() => alternarClienteSelecionado(id)}
                        className="accent-primary"
                      />
                    </label>
                  );
                })}
              </div>
            </div>
            <div>
              <label className="text-xs font-medium text-gray-300">Importações específicas</label>
              <div className="mt-2 max-h-40 space-y-2 overflow-y-auto rounded-lg border border-neutral-700 bg-dark p-3">
                {importacoesFiltradas.length === 0 && (
                  <div className="text-xs text-gray-500">Nenhuma importação encontrada.</div>
                )}
                {importacoesFiltradas.map((item) => {
                  const id = String(item.id);
                  return (
                    <label
                      key={id}
                      className="flex items-start gap-2 rounded-md bg-neutral-800/70 px-3 py-2 text-xs text-gray-200 hover:bg-neutral-700/60"
                    >
                      <input
                        type="checkbox"
                        checked={selecionarImportacoes.includes(id)}
                        onChange={() => alternarImportacaoSelecionada(id)}
                        className="accent-primary mt-0.5"
                      />
                      <div>
                        <div className="font-semibold text-gray-100">{item.nome_cliente || "Cliente"}</div>
                        <div>{formatarDescricaoImportacao(item)}</div>
                        <div className="text-[10px] text-gray-500">
                          {item.data_importacao ? new Date(item.data_importacao).toLocaleString("pt-BR") : "Data não informada"}
                        </div>
                      </div>
                    </label>
                  );
                })}
              </div>
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-4">
            {["LOGS", "TMP", "DETRAF", "CDR"].map((alvo) => (
              <button
                type="button"
                key={alvo}
                onClick={() => alternarTarget(alvo)}
                className={`rounded-lg border px-3 py-2 text-xs font-semibold transition ${
                  targets[alvo]
                    ? "border-primary bg-primary/20 text-white"
                    : "border-neutral-700 bg-dark text-gray-300 hover:border-primary/50"
                }`}
              >
                {alvo}
              </button>
            ))}
          </div>

          {targets.LOGS && (
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <label className="text-xs text-gray-400">Excluir logs com mais de (dias)</label>
                <input
                  type="number"
                  min="0"
                  className="mt-1 w-full rounded-lg border border-neutral-700 bg-dark p-2 text-gray-200 focus:outline-none focus:ring-2 focus:ring-primary/40"
                  value={logsDias}
                  onChange={(e) => setLogsDias(e.target.value)}
                  placeholder="Ex: 7"
                />
              </div>
              <div>
                <label className="text-xs text-gray-400">Manter pelo menos (últimos arquivos)</label>
                <input
                  type="number"
                  min="0"
                  className="mt-1 w-full rounded-lg border border-neutral-700 bg-dark p-2 text-gray-200 focus:outline-none focus:ring-2 focus:ring-primary/40"
                  value={logsManter}
                  onChange={(e) => setLogsManter(e.target.value)}
                  placeholder="Ex: 5"
                />
              </div>
            </div>
          )}

          <label className="flex items-center gap-2 text-sm text-gray-300">
            <input
              type="checkbox"
              checked={removerControle}
              onChange={(e) => setRemoverControle(e.target.checked)}
            />
              Remover registros do histórico de importações ao limpar DETRAF/CDR
          </label>

          <div className="flex flex-wrap gap-3">
            <button className="btn" onClick={executarLimpeza} disabled={processando}>
              {processando ? "Processando..." : "Executar limpeza"}
            </button>
            <button className="btn-secondary" onClick={limparFormulario} type="button">
              Limpar seleção
            </button>
            <button className="text-sm text-gray-300 hover:text-primary" onClick={carregarResumo} type="button">
              Atualizar resumo
            </button>
          </div>

          {(mensagem || resultadoResumo.length) && (
            <div className="rounded-lg border border-primary/40 bg-primary/10 p-3 text-sm text-primary space-y-2">
              {mensagem && <div>{mensagem}</div>}
              {resultadoResumo.length > 0 && (
                <div className="text-gray-100">
                  {resultadoResumo.map((item) => (
                    <div key={item.tipo} className="text-xs">
                      <span className="font-semibold">{item.tipo}:</span>{" "}
                      {Object.entries(item.detalhes || {})
                        .map(([campo, valor]) => `${campo}=${valor}`)
                        .join(", ") || "sem alterações"}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
