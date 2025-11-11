import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api, API_BASE } from "../lib/api";

const STATUS_META = {
  CONFERIDO: { label: "Conferidos", color: "text-emerald-400", badge: "border-emerald-400/40 text-emerald-300" },
  DIVERGENTE: { label: "Divergentes", color: "text-amber-400", badge: "border-amber-400/40 text-amber-300" },
  PERDIDO: { label: "Perdidos", color: "text-red-400", badge: "border-red-400/40 text-red-300" },
};

const porPagina = 25;

const IconEye = ({ className }) => (
  <svg
    className={className}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7z" />
    <circle cx="12" cy="12" r="3" />
  </svg>
);

const Chip = ({ active, onClick, children }) => (
  <button
    onClick={onClick}
    className={`rounded-full border px-3 py-1 text-sm transition ${
      active ? "border-primary bg-primary/10 text-primary" : "border-neutral-700 text-gray-300 hover:border-primary/50"
    }`}
  >
    {children}
  </button>
);

const StatusBadge = ({ status }) => {
  const meta = STATUS_META[status] || { badge: "border-neutral-600 text-gray-300" };
  return <span className={`rounded-full border px-3 py-1 text-xs font-medium ${meta.badge}`}>{status ?? "-"}</span>;
};

const formatarNumero = (valor) => Number(valor || 0).toLocaleString("pt-BR");
const formatarMinutos = (segundos) => {
  if (segundos === null || segundos === undefined) return "--";
  const minutos = segundos / 60;
  return minutos % 1 === 0 ? `${minutos}` : minutos.toFixed(1);
};
const formatarDelta = (valor) => {
  if (valor === null || valor === undefined) return "--";
  const minutos = (Number(valor) / 60).toFixed(1);
  return `${valor}s (${minutos} min)`;
};

export default function Validacao() {
  const [importacoes, setImportacoes] = useState([]);
  const [selecionada, setSelecionada] = useState("");
  const [resumo, setResumo] = useState(null);
  const [cdrs, setCdrs] = useState([]);
  const [cdrSelecionado, setCdrSelecionado] = useState("");
  const [lista, setLista] = useState([]);
  const [total, setTotal] = useState(0);
  const [pagina, setPagina] = useState(1);
  const [statusFiltro, setStatusFiltro] = useState([]);
  const [busca, setBusca] = useState("");
  const [apenasSemCdr, setApenasSemCdr] = useState(false);
  const [filtroDescritor, setFiltroDescritor] = useState("");
  const [filtroGh, setFiltroGh] = useState("");
  const [filtroDiferenca, setFiltroDiferenca] = useState(false);
  const [mensagem, setMensagem] = useState("");
  const [carregandoResumo, setCarregandoResumo] = useState(false);
  const [carregandoTabela, setCarregandoTabela] = useState(false);
  const [carregandoCdrs, setCarregandoCdrs] = useState(false);
  const [executando, setExecutando] = useState(false);
  const [detalheAberto, setDetalheAberto] = useState(false);
  const [detalheDados, setDetalheDados] = useState(null);
  const [carregandoDetalhe, setCarregandoDetalhe] = useState(false);
  const [erroDetalhe, setErroDetalhe] = useState("");
  const [mostrarPainelImport, setMostrarPainelImport] = useState(true);
  const [statusProcesso, setStatusProcesso] = useState("");
  const [execucaoId, setExecucaoId] = useState("");
  const [statusExecucao, setStatusExecucao] = useState(null);

  const segmentosGhDetalhe = detalheDados?.detraf?.segmentos_gh || [];
  const possuiGhNormal = segmentosGhDetalhe.some((seg) => seg.gh === "N");
  const possuiGhReduzido = segmentosGhDetalhe.some((seg) => seg.gh === "R");
  const possuiTrocaGh = segmentosGhDetalhe.some((seg, idx) => idx > 0 && seg.gh !== segmentosGhDetalhe[idx - 1].gh);
  const mostrarDistribuicaoGh =
    segmentosGhDetalhe.length > 1 && possuiGhNormal && possuiGhReduzido && possuiTrocaGh;

  const totalPaginas = Math.max(1, Math.ceil(total / porPagina));
  const faixaInicio = total ? (pagina - 1) * porPagina + 1 : 0;
  const faixaFim = total ? faixaInicio + lista.length - 1 : 0;

  const statusChips = useMemo(
    () => [
      { id: "CONFERIDO", label: "Conferidos" },
      { id: "DIVERGENTE", label: "Divergentes" },
      { id: "PERDIDO", label: "Perdidos" },
    ],
    []
  );

  const carregarImportacoes = useCallback(
    async (preservarSelecao = true) => {
      try {
        const resposta = await api.get("/api/conferencia/importacoes");
        const lista = resposta || [];
        setImportacoes(lista);
        if (!lista.length) {
          setSelecionada("");
          return;
        }
        if (!preservarSelecao || !selecionada) {
          setSelecionada(String(lista[0].id));
          return;
        }
        const aindaExiste = lista.some((item) => String(item.id) === String(selecionada));
        if (!aindaExiste) {
          setSelecionada(String(lista[0].id));
        }
      } catch (erro) {
        setMensagem((msg) => msg || erro.message || "Não foi possível carregar as importações.");
      }
    },
    [selecionada]
  );

  const importacaoSelecionada = useMemo(
    () => importacoes.find((item) => String(item.id) === String(selecionada)),
    [importacoes, selecionada]
  );

  const idClienteAtual = importacaoSelecionada?.id_cliente || resumo?.importacao?.id_cliente;

  useEffect(() => {
    carregarImportacoes(false);
  }, [carregarImportacoes]);

  useEffect(() => {
    const intervalo = setInterval(() => {
      carregarImportacoes(true);
    }, 45000);
    return () => clearInterval(intervalo);
  }, [carregarImportacoes]);

  useEffect(() => {
    if (!selecionada) return;
    carregarResumo(selecionada);
  }, [selecionada]);

  useEffect(() => {
    if (!idClienteAtual) {
      setCdrs([]);
      setCdrSelecionado("");
      return;
    }
    carregarCdrs(idClienteAtual, true);
  }, [idClienteAtual]);

  useEffect(() => {
    setPagina(1);
  }, [statusFiltro, apenasSemCdr, filtroDescritor, filtroGh, filtroDiferenca, busca]);

  useEffect(() => {
    if (!selecionada) return;
    carregarResultados();
  }, [selecionada, pagina, statusFiltro, apenasSemCdr, filtroDescritor, filtroGh, filtroDiferenca, busca]);

  useEffect(() => {
    if (!execucaoId) return;
    let ativo = true;
    let intervaloId;

    const acompanhar = async () => {
      try {
        const dados = await api.get(`/api/conferencia/execucoes/${execucaoId}`);
        if (!ativo) return;
        setStatusExecucao(dados || null);
        if (dados?.status_execucao === "CONCLUIDO") {
          setExecutando(false);
          setExecucaoId("");
          await Promise.all([carregarResumo(selecionada), carregarResultados()]);
          setMensagem("Conferência finalizada com sucesso.");
          if (intervaloId) clearInterval(intervaloId);
          ativo = false;
        } else if (dados?.status_execucao === "ERRO") {
          setExecutando(false);
          setExecucaoId("");
          setMensagem(dados?.mensagem || "Conferência encerrada com erro.");
          if (intervaloId) clearInterval(intervaloId);
          ativo = false;
        }
      } catch (erro) {
        if (!ativo) return;
        setMensagem(erro.message || "Falha ao acompanhar a conferência.");
      }
    };

    acompanhar();
    intervaloId = setInterval(acompanhar, 2000);
    return () => {
      ativo = false;
      if (intervaloId) clearInterval(intervaloId);
    };
  }, [execucaoId, selecionada]);

  const carregarCdrs = async (idCliente, preservarAtual = false) => {
    try {
      setCarregandoCdrs(true);
      const resposta = await api.get(`/api/conferencia/cdrs?id_cliente=${idCliente}`);
      const listaDisponivel = resposta || [];
      setCdrs(listaDisponivel);
      if (preservarAtual && cdrSelecionado && listaDisponivel.some((item) => String(item.id) === String(cdrSelecionado))) {
        return;
      }
      setCdrSelecionado(listaDisponivel.length ? String(listaDisponivel[0].id) : "");
    } catch (erro) {
      setMensagem(erro.message || "Falha ao carregar os CDRs disponíveis.");
      setCdrs([]);
      setCdrSelecionado("");
    } finally {
      setCarregandoCdrs(false);
    }
  };

  const carregarResumo = async (id) => {
    try {
      setMensagem("");
      setCarregandoResumo(true);
      const dados = await api.get(`/api/conferencia/resumo?id_importacao=${id}`);
      setResumo(dados);
    } catch (erro) {
      setMensagem(erro.message || "Falha ao buscar o resumo de conferência.");
    } finally {
      setCarregandoResumo(false);
    }
  };

  const carregarResultados = async () => {
    if (!selecionada) return;
    try {
      setMensagem("");
      setCarregandoTabela(true);
      const params = new URLSearchParams({
        id_importacao: selecionada,
        pagina: String(pagina),
        limite: String(porPagina),
      });
      statusFiltro.forEach((status) => params.append("status", status));
      if (busca.trim()) params.set("busca", busca.trim());
      if (apenasSemCdr) params.set("apenas_sem_cdr", "true");
      if (filtroDescritor) params.set("descritor", filtroDescritor);
      if (filtroGh) params.set("gh", filtroGh);
      if (filtroDiferenca) params.set("diferenca_min", "10");

      const resposta = await api.get(`/api/conferencia/resultados?${params.toString()}`);
      setLista(resposta?.resultados || []);
      setTotal(Number(resposta?.total || 0));
    } catch (erro) {
      setMensagem(erro.message || "Não foi possível carregar os resultados.");
    } finally {
      setCarregandoTabela(false);
    }
  };

  const handleDownload = async () => {
    if (!selecionada) return;
    try {
      setMensagem("");
      const params = new URLSearchParams({ id_importacao: selecionada });
      statusFiltro.forEach((status) => params.append("status", status));
      if (busca.trim()) params.set("busca", busca.trim());
      if (apenasSemCdr) params.set("apenas_sem_cdr", "true");
      if (filtroDescritor) params.set("descritor", filtroDescritor);
      if (filtroGh) params.set("gh", filtroGh);
      if (filtroDiferenca) params.set("diferenca_min", "10");

      const resposta = await fetch(`${API_BASE}/api/conferencia/export?${params.toString()}`);
      if (!resposta.ok) {
        throw new Error(await resposta.text());
      }
      const blob = await resposta.blob();
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `conferencia_${selecionada}.csv`;
      link.click();
      window.URL.revokeObjectURL(url);
    } catch (erro) {
      setMensagem(erro.message || "Não foi possível exportar o CSV.");
    }
  };

  const executarConferencia = async () => {
    if (!selecionada || !cdrSelecionado) {
      setMensagem("Selecione o DETRAF e o CDR para executar a conferência.");
      return;
    }
    try {
      setMensagem("");
      setExecutando(true);
      setStatusProcesso("Preparando conferência...");
      setStatusExecucao(null);
      setExecucaoId("");
      const resposta = await api.post(
        "/api/conferencia/processar",
        {
          id_importacao_detraf: Number(selecionada),
          id_importacao_cdr: Number(cdrSelecionado),
        },
        { timeout: 30000 }
      );
      const idExec = resposta?.id_execucao;
      if (!idExec) {
        throw new Error("Serviço não retornou o identificador da execução.");
      }
      setExecucaoId(String(idExec));
      setMensagem("Conferência iniciada. Acompanhe o progresso abaixo.");
      setMostrarPainelImport(false);
    } catch (erro) {
      setMensagem(erro.message || "Falha ao executar a conferência.");
      setStatusProcesso("Falha ao processar.");
      setExecutando(false);
      setExecucaoId("");
    } finally {
      setTimeout(() => setStatusProcesso(""), 4000);
    }
  };

  const toggleStatus = (valor) => {
    setStatusFiltro((atual) =>
      atual.includes(valor) ? atual.filter((item) => item !== valor) : [...atual, valor]
    );
  };

  const toggleDescritor = (valor) => {
    setFiltroDescritor((atual) => (atual === valor ? "" : valor));
  };

  const toggleGh = (valor) => {
    setFiltroGh((atual) => (atual === valor ? "" : valor));
  };

  const limparFiltros = () => {
    setStatusFiltro([]);
    setApenasSemCdr(false);
    setFiltroDescritor("");
    setFiltroGh("");
    setFiltroDiferenca(false);
    setBusca("");
  };

  const abrirDetalhes = async (idResultado) => {
    setDetalheAberto(true);
    setCarregandoDetalhe(true);
    setErroDetalhe("");
    setDetalheDados(null);
    try {
      const resposta = await api.get(`/api/conferencia/resultados/${idResultado}`, { timeout: 60000 });
      const detalhesNormalizados = resposta || null;
      if (detalhesNormalizados && !Array.isArray(detalhesNormalizados.detalhes_divergencia)) {
        detalhesNormalizados.detalhes_divergencia = [];
      }
      if (detalhesNormalizados?.detraf?.segmentos_gh && !Array.isArray(detalhesNormalizados.detraf.segmentos_gh)) {
        try {
          detalhesNormalizados.detraf.segmentos_gh = JSON.parse(detalhesNormalizados.detraf.segmentos_gh);
        } catch {
          detalhesNormalizados.detraf.segmentos_gh = [];
        }
      }
      setDetalheDados(detalhesNormalizados);
    } catch (erro) {
      setErroDetalhe(erro.message || "Falha ao carregar os detalhes da chamada.");
    } finally {
      setCarregandoDetalhe(false);
    }
  };

  const fecharDetalhes = () => {
    setDetalheAberto(false);
    setCarregandoDetalhe(false);
    setDetalheDados(null);
    setErroDetalhe("");
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-white">Validação DETRAF – Conferência</h1>
          <p className="text-sm text-gray-400">Compare DETRAF x CDR, identifique divergências e exporte os alinhamentos.</p>
          {!mostrarPainelImport && resumo?.importacao && (
            <p className="mt-1 text-xs text-gray-500">
              Importação em uso: {resumo.importacao.arquivo || resumo.importacao?.arquivo} •{" "}
              {resumo.importacao.janela || `${resumo.importacao.periodo_inicial || "--"} – ${
                resumo.importacao.periodo_final || "--"
              }`}
            </p>
          )}
        </div>
        <div className="flex flex-col gap-2 md:flex-row md:items-center">
          <button
            className="btn-secondary"
            onClick={() => setMostrarPainelImport((prev) => !prev)}
          >
            {mostrarPainelImport ? "Ocultar seleção de importação" : "Selecionar outra importação"}
          </button>
        </div>
      </div>

      {mostrarPainelImport && (
        <div className="rounded-2xl border border-neutral-800 bg-neutral-900 p-4 space-y-6">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <label className="text-xs uppercase tracking-wide text-gray-400">Selecione o DETRAF</label>
              <div className="flex flex-col gap-2 md:flex-row md:items-center">
                <select
                  value={selecionada}
                  onChange={(e) => {
                    setSelecionada(e.target.value);
                    setPagina(1);
                  }}
                  className="flex-1 rounded-lg border border-neutral-700 bg-dark px-4 py-2 text-sm"
                >
                  {!importacoes.length && <option value="">Nenhuma importação disponível</option>}
                  {importacoes.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.cliente} • {item.arquivo}
                    </option>
                  ))}
                </select>
              </div>
              <p className="text-xs text-gray-500">Lista atualizada automaticamente a cada 45s.</p>
            </div>
            <div className="space-y-2">
              <label className="text-xs uppercase tracking-wide text-gray-400">Selecione o CDR</label>
              <div className="flex flex-col gap-2 md:flex-row md:items-center">
                <select
                  value={cdrSelecionado}
                  onChange={(e) => setCdrSelecionado(e.target.value)}
                  className="flex-1 rounded-lg border border-neutral-700 bg-dark px-4 py-2 text-sm disabled:opacity-60"
                  disabled={carregandoCdrs || !cdrs.length}
                >
                  {!cdrs.length && <option value="">Nenhum CDR disponível</option>}
                  {cdrs.map((cdr) => (
                    <option key={cdr.id} value={cdr.id}>
                      {cdr.nome_arquivo || `CDR ${cdr.id}`} ({cdr.periodo_inicial || "--"} – {cdr.periodo_final || "--"})
                    </option>
                  ))}
                </select>
                <button
                  className="btn-secondary"
                  onClick={() => idClienteAtual && carregarCdrs(idClienteAtual, true)}
                  disabled={carregandoCdrs || !idClienteAtual}
                >
                  {carregandoCdrs ? "Carregando..." : "Atualizar CDRs"}
                </button>
              </div>
              <p className="text-xs text-gray-500">A conferência sempre limpa as tabelas normalizadas antes de reprocessar.</p>
            </div>
          </div>
          <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
            <p className="text-xs text-gray-500">
              Dispare o batimento quando ambos os arquivos selecionados estiverem corretos.
            </p>
            <button className="btn" onClick={executarConferencia} disabled={executando || !selecionada || !cdrSelecionado}>
              {executando ? "Processando..." : "Rodar conferência"}
            </button>
          </div>
        </div>
      )}

      {(executando || execucaoId) && (
        <div className="rounded-2xl border border-neutral-800 bg-neutral-900 p-4 space-y-3">
          <div className="flex flex-col gap-1 text-sm text-gray-300 md:flex-row md:items-center md:justify-between">
            <span>{statusExecucao?.etapa_atual || "Processando conferência..."}</span>
            <span className="text-xs text-gray-500">
              {statusExecucao?.mensagem || statusProcesso || "Aguardando etapas"}
            </span>
          </div>
          <div className="relative h-2 w-full overflow-hidden rounded bg-neutral-800">
            <div
              className="absolute inset-y-0 rounded bg-primary transition-all"
              style={{ width: `${statusExecucao?.progresso_percentual ?? 5}%` }}
            ></div>
          </div>
          <div className="text-xs text-gray-400">
            {statusExecucao?.processados ?? 0} de {statusExecucao?.total_registros ?? "--"} registros processados
          </div>
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-3">
        <div className="rounded-xl border border-neutral-700 bg-neutral-900 p-4">
          <p className="text-xs uppercase tracking-wide text-gray-400">Processadas</p>
          <p className="mt-2 text-2xl font-semibold text-white">
            {carregandoResumo ? "--" : formatarNumero(resumo?.status?.processadas)}
          </p>
          <p className="text-xs text-gray-500">Registros DETRAF analisados</p>
        </div>
        <div className="rounded-xl border border-neutral-700 bg-neutral-900 p-4">
          <p className="text-xs uppercase tracking-wide text-gray-400">Válidas</p>
          <p className="mt-2 text-2xl font-semibold text-emerald-400">
            {carregandoResumo ? "--" : formatarNumero(resumo?.status?.validas)}
          </p>
          <p className="text-xs text-gray-500">Batimentos conferidos</p>
        </div>
        <div className="rounded-xl border border-neutral-700 bg-neutral-900 p-4">
          <p className="text-xs uppercase tracking-wide text-gray-400">Inválidas</p>
          <p className="mt-2 text-2xl font-semibold text-red-400">
            {carregandoResumo ? "--" : formatarNumero(resumo?.status?.invalidas)}
          </p>
          <p className="text-xs text-gray-500">Divergências + perdidos</p>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        {(resumo?.resumo || statusChips.map(({ id }) => ({ status: id, total: 0, percentual: 0 }))).map((item) => {
          const meta = STATUS_META[item.status] || {};
          return (
            <div key={item.status} className="rounded-xl border border-neutral-700 bg-neutral-900 p-4">
              <p className={`text-sm font-medium ${meta.color || "text-gray-200"}`}>{meta.label || item.status}</p>
              <div className="mt-2 flex items-baseline gap-2">
                <span className="text-3xl font-semibold text-white">
                  {carregandoResumo && !resumo ? "--" : formatarNumero(item.total)}
                </span>
                <span className="text-sm text-gray-400">
                  ({carregandoResumo && !resumo ? "--" : (item.percentual ?? 0)}%)
                </span>
              </div>
            </div>
          );
        })}
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-xl border border-neutral-700 bg-neutral-900 p-4">
          <p className="text-xs uppercase tracking-wide text-gray-400">Minutos reduzidos cobrados</p>
          <p className="mt-2 text-2xl font-semibold text-white">
            {carregandoResumo ? "--" : formatarMinutos(resumo?.gh_metricas?.segundos_reduzidos_cobrados)}
          </p>
          <p className="text-xs text-gray-500">Total informado pela operadora</p>
        </div>
        <div className="rounded-xl border border-neutral-700 bg-neutral-900 p-4">
          <p className="text-xs uppercase tracking-wide text-gray-400">Minutos reduzidos validados</p>
          <p className="mt-2 text-2xl font-semibold text-emerald-400">
            {carregandoResumo ? "--" : formatarMinutos(resumo?.gh_metricas?.segundos_reduzidos_validados)}
          </p>
          <p className="text-xs text-gray-500">Total identificado pela conferência</p>
        </div>
      </div>

      <div className="rounded-2xl border border-neutral-800 bg-neutral-900 p-4 space-y-4">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="flex flex-wrap gap-2">
            {statusChips.map((item) => (
              <Chip key={item.id} active={statusFiltro.includes(item.id)} onClick={() => toggleStatus(item.id)}>
                {item.label}
              </Chip>
            ))}
            <Chip active={apenasSemCdr} onClick={() => setApenasSemCdr((prev) => !prev)}>
              Sem CDR
            </Chip>
            <Chip active={filtroDiferenca} onClick={() => setFiltroDiferenca((prev) => !prev)}>
              Diferença &gt; 10s
            </Chip>
          </div>
          <div className="flex flex-col gap-2 md:flex-row md:items-center">
            <input
              type="text"
              placeholder="Buscar assinante"
              value={busca}
              onChange={(e) => setBusca(e.target.value)}
              className="rounded-lg border border-neutral-700 bg-dark px-4 py-2 text-sm text-gray-200 focus:border-primary"
            />
            <button className="text-sm text-gray-400 hover:text-primary" onClick={limparFiltros}>
              Limpar filtros
            </button>
          </div>
        </div>

        {(resumo?.filtros?.descritor?.length || resumo?.filtros?.gh?.length) && (
          <div className="flex flex-wrap gap-2">
            {(resumo?.filtros?.descritor || []).map((item) => (
              <Chip key={`desc-${item.valor}`} active={filtroDescritor === item.valor} onClick={() => toggleDescritor(item.valor)}>
                Descritor = {item.valor} ({formatarNumero(item.quantidade)})
              </Chip>
            ))}
            {(resumo?.filtros?.gh || []).map((item) => (
              <Chip key={`gh-${item.valor}`} active={filtroGh === item.valor} onClick={() => toggleGh(item.valor)}>
                GH = {item.valor} ({formatarNumero(item.quantidade)})
              </Chip>
            ))}
          </div>
        )}
      </div>

      <div className="rounded-2xl border border-neutral-800 bg-neutral-900">
        <div className="flex flex-col gap-3 border-b border-neutral-800 px-4 py-3 md:flex-row md:items-center md:justify-between">
          <div>
            <p className="text-sm font-semibold text-white">Resultados</p>
            <p className="text-xs text-gray-400">
              {carregandoTabela
                ? "Carregando registros..."
                : total
                ? `Mostrando ${faixaInicio}–${faixaFim} de ${formatarNumero(total)}`
                : "Nenhum resultado encontrado"}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button className="btn-secondary" onClick={handleDownload} disabled={!total}>
              Download CSV
            </button>
            <button className="btn" onClick={carregarResultados}>
              Atualizar
            </button>
          </div>
        </div>

        <div className="overflow-x-auto">
          {execucaoId ? (
            <div className="px-4 py-10 text-center text-sm text-gray-400">
              Processando conferência... os resultados serão exibidos assim que finalizarmos.
            </div>
          ) : (
          <table className="min-w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-gray-400">
                <th className="px-4 py-3">Data</th>
                <th className="px-4 py-3">Hora</th>
                <th className="px-4 py-3">Assinante A</th>
                <th className="px-4 py-3">Assinante B</th>
                <th className="px-4 py-3">Descritor</th>
                <th className="px-4 py-3">Duração (DETRAF/CDR)</th>
                <th className="px-4 py-3">EOT</th>
                <th className="px-4 py-3">Classificação</th>
                <th className="px-4 py-3">Observação</th>
                <th className="px-4 py-3 text-center">
                  <span className="sr-only">Detalhes</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {carregandoTabela && (
                <tr>
                  <td colSpan={9} className="px-4 py-6 text-center text-gray-400">
                    Carregando resultados...
                  </td>
                </tr>
              )}
              {!carregandoTabela && !lista.length && (
                <tr>
                  <td colSpan={9} className="px-4 py-6 text-center text-gray-500">
                    Nenhum registro encontrado com os filtros aplicados.
                  </td>
                </tr>
              )}
              {lista.map((item) => (
                <tr key={item.id} className="border-t border-neutral-800 text-gray-200">
                  <td className="px-4 py-3 align-top">{item.data}</td>
                  <td className="px-4 py-3 align-top text-gray-400">{item.hora}</td>
                  <td className="px-4 py-3 align-top">{item.assinante_a || "--"}</td>
                  <td className="px-4 py-3 align-top">{item.assinante_b || "--"}</td>
                  <td className="px-4 py-3 align-top">{item.descritor || "--"}</td>
                  <td className="px-4 py-3 align-top">
                    <div className="flex flex-col text-xs text-gray-300">
                      <span>DETRAF: {item.duracao_detraf}</span>
                      <span>CDR: {item.duracao_cdr}</span>
                    </div>
                  </td>
                  <td className="px-4 py-3 align-top text-xs text-gray-300">
                    <div>EOT arquivo: {item.eot_detraf || "--"}</div>
                    <div>EOT CDR: {item.eot_cdr || (item.tem_cdr ? "--" : "n/d")}</div>
                  </td>
                  <td className="px-4 py-3 align-top">
                    <StatusBadge status={item.status} />
                  </td>
                  <td className="px-4 py-3 align-top text-sm text-gray-300">
                    {item.observacao || item.descricao_divergencia || "--"}
                  </td>
                  <td className="px-4 py-3 align-top text-center">
                    <button
                      className="mx-auto flex h-8 w-8 items-center justify-center rounded-full border border-neutral-700 text-primary hover:bg-primary/10"
                      onClick={() => abrirDetalhes(item.id)}
                      aria-label="Ver detalhes da chamada"
                    >
                      <IconEye className="h-4 w-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          )}
        </div>

        <div className="flex flex-col gap-3 border-t border-neutral-800 px-4 py-4 md:flex-row md:items-center md:justify-between">
          <p className="text-xs text-gray-400">
            Página {pagina} de {totalPaginas}
          </p>
          <div className="flex items-center gap-2">
            <button
              className="btn-secondary"
              onClick={() => setPagina((p) => Math.max(1, p - 1))}
              disabled={pagina === 1}
            >
              Anterior
            </button>
            <button
              className="btn-secondary"
              onClick={() => setPagina((p) => Math.min(totalPaginas, p + 1))}
              disabled={pagina >= totalPaginas}
            >
              Próximo
            </button>
          </div>
        </div>
      </div>

      {mensagem && (
        <div className="rounded-xl border border-primary/50 bg-primary/10 p-3 text-sm text-primary">
          {mensagem}
        </div>
      )}

      {detalheAberto && (
        <div className="fixed inset-0 z-50 bg-black/70">
          <div className="flex min-h-full items-start justify-center overflow-y-auto p-4 sm:p-8">
            <div className="w-full max-w-5xl overflow-hidden rounded-2xl border border-neutral-700 bg-neutral-950 shadow-2xl">
              <div className="flex max-h-[calc(100vh-2rem)] flex-col sm:max-h-[calc(100vh-4rem)]">
                <div className="flex flex-col gap-3 border-b border-neutral-800 px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
                  <div>
                    <h3 className="text-lg font-semibold text-white">Detalhes da chamada</h3>
                    {detalheDados && (
                      <p className="text-xs text-gray-400">
                        Resultado #{detalheDados.id} • Status: {detalheDados.status}
                      </p>
                    )}
                  </div>
                  <button
                    className="self-start text-sm text-gray-400 transition hover:text-white sm:self-auto"
                    onClick={fecharDetalhes}
                  >
                    Fechar ✕
                  </button>
                </div>

                <div className="flex-1 overflow-y-auto px-4 py-4 sm:px-6">
                  {carregandoDetalhe && (
                    <div className="py-8 text-center text-sm text-gray-300">Carregando detalhes...</div>
                  )}

                  {!carregandoDetalhe && erroDetalhe && (
                    <div className="py-6 text-center text-sm text-red-400">{erroDetalhe}</div>
                  )}

                  {!carregandoDetalhe && !erroDetalhe && detalheDados && (
                    <>
                      <div className="grid gap-6 md:grid-cols-2">
                        <div className="space-y-3 rounded-xl border border-neutral-800 bg-neutral-900 p-4">
                          <h4 className="text-sm font-semibold text-primary">DETRAF</h4>
                          <dl className="space-y-1 text-xs text-gray-300">
                            <div className="details-pair">
                              <dt>Sequencial</dt>
                              <dd>{detalheDados.detraf?.sequencial || "--"}</dd>
                            </div>
                            <div className="details-pair">
                              <dt>Data/Hora</dt>
                              <dd>
                                {detalheDados.detraf?.data_chamada || "--"} {detalheDados.detraf?.hora_atendimento || "--"}
                              </dd>
                            </div>
                            <div className="details-pair">
                              <dt>Assinante A</dt>
                              <dd>{detalheDados.detraf?.assinante_a || "--"}</dd>
                            </div>
                            <div className="details-pair">
                              <dt>Assinante B</dt>
                              <dd>{detalheDados.detraf?.assinante_b || "--"}</dd>
                            </div>
                            <div className="details-pair">
                              <dt>Descritor</dt>
                              <dd>{detalheDados.detraf?.descritor_cdr || "--"}</dd>
                            </div>
                            <div className="details-pair">
                              <dt>Duração real (s)</dt>
                              <dd>{detalheDados.detraf?.duracao_real_segundos ?? "--"}</dd>
                            </div>
                            <div className="details-pair">
                              <dt>Duração calculada</dt>
                              <dd>{detalheDados.detraf?.duracao_calculada ?? "--"}</dd>
                            </div>
                            <div className="details-pair">
                              <dt>GH</dt>
                              <dd>{detalheDados.detraf?.gh || "--"}</dd>
                            </div>
                            <div className="details-pair">
                              <dt>EQT (cred/deved)</dt>
                              <dd>
                                {detalheDados.detraf?.eqt_credora || "--"} / {detalheDados.detraf?.eqt_devedora || "--"}
                              </dd>
                            </div>
                            <div className="details-pair">
                              <dt>POI</dt>
                              <dd>{detalheDados.detraf?.poi || "--"}</dd>
                            </div>
                          </dl>
                        </div>

                        <div className="space-y-3 rounded-xl border border-neutral-800 bg-neutral-900 p-4">
                          <h4 className="text-sm font-semibold text-primary">CDR</h4>
                          {detalheDados.cdr && Object.keys(detalheDados.cdr).length ? (
                            <dl className="space-y-1 text-xs text-gray-300">
                              <div className="details-pair">
                                <dt>ID CDR</dt>
                                <dd>{detalheDados.cdr.registro_id || detalheDados.cdr.id || "--"}</dd>
                              </div>
                              <div className="details-pair">
                                <dt>Data / Hora</dt>
                                <dd>{detalheDados.cdr.calldate || "--"}</dd>
                              </div>
                              <div className="details-pair">
                                <dt>Assinante A (src)</dt>
                                <dd>{detalheDados.cdr.src || "--"}</dd>
                              </div>
                              <div className="details-pair">
                                <dt>Assinante B (dst)</dt>
                                <dd>{detalheDados.cdr.dst || "--"}</dd>
                              </div>
                              <div className="details-pair">
                                <dt>Canal</dt>
                                <dd>{detalheDados.cdr.channel || "--"}</dd>
                              </div>
                              <div className="details-pair">
                                <dt>Canal destino</dt>
                                <dd>{detalheDados.cdr.dstchannel || "--"}</dd>
                              </div>
                              <div className="details-pair">
                                <dt>Última aplicação</dt>
                                <dd>{detalheDados.cdr.lastdata || "--"}</dd>
                              </div>
                              <div className="details-pair">
                                <dt>EOT (A/B)</dt>
                                <dd>
                                  {detalheDados.cdr.eot_a || detalheDados.cdr.EOT_A || "--"} / {detalheDados.cdr.eot_b || detalheDados.cdr.EOT_B || "--"}
                                </dd>
                              </div>
                              <div className="details-pair">
                                <dt>Duração total</dt>
                                <dd>{detalheDados.cdr.duration_total ?? detalheDados.cdr.duration ?? "--"}</dd>
                              </div>
                              <div className="details-pair">
                                <dt>Tempo tarifado (bilsec)</dt>
                                <dd>{detalheDados.cdr.billsec ?? detalheDados.cdr.bilsec ?? "--"}</dd>
                              </div>
                              <div className="details-pair">
                                <dt>Sigame</dt>
                                <dd>{detalheDados.cdr.sigame || "--"}</dd>
                              </div>
                              <div className="details-pair">
                                <dt>Sentido</dt>
                                <dd>{detalheDados.cdr.sentido || "--"}</dd>
                              </div>
                              <div className="details-pair">
                                <dt>RURI</dt>
                                <dd>{detalheDados.cdr.ruri || "--"}</dd>
                              </div>
                              <div className="details-pair">
                                <dt>URI</dt>
                                <dd>{detalheDados.cdr.uri || "--"}</dd>
                              </div>
                              <div className="details-pair">
                                <dt>Número discado</dt>
                                <dd>{detalheDados.cdr.dialed_number || "--"}</dd>
                              </div>
                              <div className="details-pair">
                                <dt>Status da chamada</dt>
                                <dd>
                                  {(() => {
                                    switch ((detalheDados.cdr.disposition || "").toUpperCase()) {
                                      case "ANSWERED":
                                        return "Atendida";
                                      case "BUSY":
                                        return "Ocupado";
                                      case "FAILED":
                                        return "Falha";
                                      case "NO ANSWER":
                                        return "Sem resposta";
                                      default:
                                        return detalheDados.cdr.disposition || "--";
                                    }
                                  })()}
                                </dd>
                              </div>
                            </dl>
                          ) : (
                            <p className="text-xs text-gray-400">Nenhum registro CDR associado.</p>
                          )}
                        </div>
                      </div>

                      <div className="mt-6 grid gap-4 rounded-xl border border-neutral-800 bg-neutral-900 p-4 text-sm text-gray-300 md:grid-cols-2">
                        <div>
                          <span className="font-semibold text-gray-200">Delta duração:</span>{" "}
                          {formatarDelta(detalheDados.delta_duracao_seg)}
                        </div>
                        <div>
                          <span className="font-semibold text-gray-200">Delta horário:</span>{" "}
                          {formatarDelta(detalheDados.delta_hora_seg)}
                        </div>
                      </div>

                      <div className="mt-6 space-y-3 rounded-xl border border-neutral-800 bg-neutral-900/60 p-4">
                        <div className="text-sm font-semibold text-gray-100">Motivos identificados</div>
                        {detalheDados.detalhes_divergencia?.length ? (
                          <ul className="space-y-2 text-sm text-gray-200">
                            {detalheDados.detalhes_divergencia.map((motivo, indice) => (
                              <li
                                key={`${motivo.tipo || "info"}-${indice}`}
                                className="rounded-lg border border-neutral-800 bg-neutral-950/80 p-3"
                              >
                                <div className="text-xs uppercase tracking-wide text-primary/80">
                                  {motivo.tipo || "informativo"}
                                </div>
                                <p className="text-sm text-gray-200">{motivo.mensagem}</p>
                              </li>
                            ))}
                          </ul>
                        ) : (
                          <p className="text-sm text-gray-400">Nenhuma divergência adicional registrada para esta chamada.</p>
                        )}
                      </div>

                      <div className="mt-4 rounded-xl border border-neutral-800 bg-neutral-900/40 p-4 text-sm text-gray-300">
                        <span className="font-semibold text-gray-200">Observação principal:</span>{" "}
                        {detalheDados.observacao || detalheDados.descricao_divergencia || "--"}
                      </div>

                      {mostrarDistribuicaoGh && (
                        <div className="mt-6 space-y-3 rounded-xl border border-neutral-800 bg-neutral-900/30 p-4">
                          <div className="text-sm font-semibold text-gray-100">Distribuição por grupo horário</div>
                          <div className="grid gap-3 text-sm text-gray-300 md:grid-cols-3">
                            <div>
                              <span className="font-semibold text-gray-200">Tarifa:</span>{" "}
                              {detalheDados.detraf?.tarifa_aplicada || "--"}
                            </div>
                            <div>
                              <span className="font-semibold text-gray-200">Min. normal:</span>{" "}
                              {formatarMinutos(detalheDados.detraf?.segundos_gh_normal)}
                            </div>
                            <div>
                              <span className="font-semibold text-gray-200">Min. reduzido:</span>{" "}
                              {formatarMinutos(detalheDados.detraf?.segundos_gh_reduzido)}
                            </div>
                          </div>
                          {detalheDados.detraf?.segmentos_gh?.length ? (
                            <div className="overflow-x-auto">
                              <table className="min-w-full text-xs text-gray-300">
                                <thead>
                                  <tr className="text-left uppercase tracking-wide text-gray-400">
                                    <th className="px-2 py-1">GH</th>
                                    <th className="px-2 py-1">Início</th>
                                    <th className="px-2 py-1">Fim</th>
                                    <th className="px-2 py-1">Minutos</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {detalheDados.detraf.segmentos_gh.map((seg, idx) => (
                                    <tr key={`${seg.inicio}-${idx}`} className="border-t border-neutral-800">
                                      <td className="px-2 py-1">{seg.gh}</td>
                                      <td className="px-2 py-1">{new Date(seg.inicio).toLocaleString()}</td>
                                      <td className="px-2 py-1">{new Date(seg.fim).toLocaleString()}</td>
                                      <td className="px-2 py-1">{formatarMinutos(seg.segundos)}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          ) : (
                            <p className="text-xs text-gray-400">Não há segmentos calculados para esta chamada.</p>
                          )}
                        </div>
                      )}
                    </>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
