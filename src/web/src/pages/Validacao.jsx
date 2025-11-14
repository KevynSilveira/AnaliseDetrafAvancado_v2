import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api, API_BASE } from "../lib/api";
import { obterClasseMensagem } from "../lib/mensagens";
import { exportarResumoPdf } from "../lib/pdfResumo";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  Cell,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Rectangle,
  Sector,
} from "recharts";

const STATUS_META = {
  CONFERIDO: { label: "Conferidos", color: "text-emerald-400", badge: "border-emerald-400/40 text-emerald-300" },
  DIVERGENTE: { label: "Divergentes", color: "text-amber-400", badge: "border-amber-400/40 text-amber-300" },
  PERDIDO: { label: "Perdidos", color: "text-red-400", badge: "border-red-400/40 text-red-300" },
};

const porPagina = 25;
const DIFERENCA_TOLERANCIA_SEG = 10;

const SERIES_STATUS = [
  { id: "conferidos", label: "Conferidos", color: "#34d399" },
  { id: "divergentes", label: "Divergentes", color: "#fbbf24" },
  { id: "perdidos", label: "Perdidos", color: "#f87171" },
];

const SERIES_TARIFAS = [
  { id: "movel", label: "Chamadas móveis (VU-M)", color: "#34d399" },
  { id: "fixo", label: "Chamadas fixas (TU-RL)", color: "#60a5fa" },
];

const STATUS_TO_SERIE = {
  CONFERIDO: "conferidos",
  DIVERGENTE: "divergentes",
  PERDIDO: "perdidos",
};

const obterClasseCardResumo = (ativo = false) =>
  `text-left rounded-xl border p-4 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 ${
    ativo ? "border-primary/70 bg-primary/10 shadow-lg shadow-primary/10" : "border-neutral-700 bg-neutral-950/60 hover:border-primary/60"
  }`;

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
const formatarMinutosComSufixo = (valor) => {
  const minutos = formatarMinutos(valor);
  return minutos === "--" ? "--" : `${minutos} min`;
};

const formatarHoraDetraf = (valor) => {
  if (valor === null || valor === undefined) return "--";
  const texto = String(valor).trim();
  if (!texto) return "--";
  const digits = texto.replace(/\D/g, "");
  if (!digits) {
    return texto.includes(":") ? texto : "--";
  }
  if (digits.length > 6) {
    const totalSegundos = parseInt(digits, 10);
    if (!Number.isNaN(totalSegundos)) {
      const hh = String(Math.floor(totalSegundos / 3600)).padStart(2, "0");
      const mm = String(Math.floor((totalSegundos % 3600) / 60)).padStart(2, "0");
      const ss = String(totalSegundos % 60).padStart(2, "0");
      return `${hh}:${mm}:${ss}`;
    }
  }
  const normalizado = digits.padStart(6, "0").slice(-6);
  const hh = normalizado.slice(0, 2);
  const mm = normalizado.slice(2, 4);
  const ss = normalizado.slice(4, 6);
  return `${hh}:${mm}:${ss}`;
};

const TONE_VARIANTS = {
  default: {
    container: "border-neutral-700 bg-neutral-950/70 text-gray-100",
    value: "text-white",
  },
  positive: {
    container: "border-emerald-500/40 bg-emerald-500/10 text-emerald-100",
    value: "text-emerald-300",
  },
  negative: {
    container: "border-rose-500/40 bg-rose-500/10 text-rose-100",
    value: "text-rose-300",
  },
  warning: {
    container: "border-amber-400/40 bg-amber-500/10 text-amber-100",
    value: "text-amber-300",
  },
};

const DIVERGENCIA_CORES = {
  Perdidos: "#f43f5e",
  "Status divergente": "#fb923c",
  "EOT divergente": "#facc15",
  "Duração acima da tolerância": "#84cc16",
  "GH divergente": "#a855f7",
  "Múltiplas divergências": "#22d3ee",
};
const createBarShape = (radius) => (props) => <Rectangle {...props} radius={radius} fill={props.fill} />;
const createActiveBarShape = (radius) => (props) => (
  <Rectangle {...props} radius={radius} fill={props.fill} stroke="#f8fafc" strokeOpacity={0.35} strokeWidth={1} />
);

const BAR_SHAPE = createBarShape([8, 8, 0, 0]);
const BAR_SHAPE_ACTIVE = createActiveBarShape([8, 8, 0, 0]);

const renderPieSlice = (props) => <Sector {...props} stroke="none" fill={props.fill} />;
const renderPieSliceActive = (props) => (
  <Sector {...props} stroke="#f8fafc" strokeWidth={1} fill={props.fill} outerRadius={props.outerRadius + 2} />
);

const DataCard = ({ title, value, subtitle, onClick, active = false, tone = "default" }) => {
  const toneConfig = TONE_VARIANTS[tone] || TONE_VARIANTS.default;
  const baseClass =
    "rounded-xl border p-4 text-left transition focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 min-h-[130px]";
  const className = onClick
    ? `${baseClass} ${toneConfig.container} ${active ? "ring-1 ring-primary shadow-lg shadow-primary/10" : "hover:border-primary/60"}`
    : `${baseClass} ${toneConfig.container}`;
  const Component = onClick ? "button" : "div";
  return (
    <Component className={className} onClick={onClick}>
      <p className="text-xs uppercase tracking-wide text-gray-400">{title}</p>
      <p className={`mt-2 text-2xl font-semibold ${toneConfig.value}`}>{value}</p>
      {subtitle && <p className="text-xs text-gray-500 leading-relaxed break-words">{subtitle}</p>}
    </Component>
  );
};

const SectionBlock = ({ title, subtitle, extra, children }) => (
  <section className="rounded-2xl border border-neutral-800 bg-neutral-900 p-5 space-y-4 shadow-inner shadow-black/10">
    <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <h3 className="text-sm font-semibold text-white">{title}</h3>
        {subtitle && <p className="text-xs text-gray-400">{subtitle}</p>}
      </div>
      {extra}
    </div>
    {children}
  </section>
);
const formatarDelta = (valor) => {
  if (valor === null || valor === undefined) return "--";
  const minutos = (Number(valor) / 60).toFixed(1);
  return `${valor}s (${minutos} min)`;
};

const formatarDataCurta = (valor) => {
  if (!valor) return "--";
  const data = new Date(valor);
  if (Number.isNaN(data.getTime())) return valor;
  return data.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
};

const formatarDataCompleta = (valor) => {
  if (!valor) return "--";
  const data = new Date(valor);
  if (Number.isNaN(data.getTime())) return valor;
  return data.toLocaleString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
};

const paraDatetimeLocal = (valor) => {
  if (!valor) return "";
  const data = new Date(valor);
  if (Number.isNaN(data.getTime())) return "";
  const ajustada = new Date(data.getTime() - data.getTimezoneOffset() * 60000);
  return ajustada.toISOString().slice(0, 16);
};

const sanitizarTelefoneFiltro = (valor) => {
  const digits = (valor || "").replace(/\D/g, "");
  if (!digits) return "";
  if (digits.startsWith("0800")) {
    return digits.slice(1);
  }
  return digits;
};

const formatarTelefoneExibicao = (valor) => {
  const digitsBrutos = (valor || "").replace(/\D/g, "");
  if (!digitsBrutos) return "";
  const eh0800 = digitsBrutos.startsWith("0800") || digitsBrutos.startsWith("800");
  if (eh0800) {
    const coerente = (digitsBrutos.startsWith("0800") ? digitsBrutos : `0${digitsBrutos}`).slice(0, 11);
    const bloco1 = coerente.slice(0, 4);
    const bloco2 = coerente.slice(4, 7);
    const bloco3 = coerente.slice(7, 11);
    return [bloco1, bloco2, bloco3].filter(Boolean).join(" ");
  }
  const digits = digitsBrutos.slice(0, 11);
  if (!digits) return "";
  if (digits.length <= 2) return digits;
  const ddd = digits.slice(0, 2);
  const restante = digits.slice(2);
  if (restante.length <= 4) {
    return `(${ddd}) ${restante}`;
  }
  if (restante.length === 5) {
    return `(${ddd}) ${restante.slice(0, 1)} ${restante.slice(1)}`;
  }
  const parteInicial = restante.length === 9 ? `${restante.slice(0, 5)}-${restante.slice(5)}` : `${restante.slice(0, restante.length - 4)}-${restante.slice(-4)}`;
  return `(${ddd}) ${parteInicial}`;
};

export default function Validacao() {
  const [importacoes, setImportacoes] = useState([]);
  const [selecionada, setSelecionada] = useState("");
  const [resumo, setResumo] = useState(null);
const [cdrs, setCdrs] = useState([]);
const [cdrSelecionado, setCdrSelecionado] = useState("");
const [forcarNormalizacao, setForcarNormalizacao] = useState(false);
  const [lista, setLista] = useState([]);
  const [total, setTotal] = useState(0);
  const [pagina, setPagina] = useState(1);
  const [statusFiltro, setStatusFiltro] = useState([]);
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
  const [visaoPainel, setVisaoPainel] = useState("painel");
  const [filtroTarifa, setFiltroTarifa] = useState("");
  const [mostrarApenasCng, setMostrarApenasCng] = useState(false);
  const [filtroSigame, setFiltroSigame] = useState(false);
  const [filtroAssinanteA, setFiltroAssinanteA] = useState("");
  const [filtroAssinanteB, setFiltroAssinanteB] = useState("");
  const [filtroDataInicio, setFiltroDataInicio] = useState("");
  const [filtroDataFim, setFiltroDataFim] = useState("");
  const [datasPersonalizadas, setDatasPersonalizadas] = useState(false);
  const [mostrarAvancados, setMostrarAvancados] = useState(false);
  const [filtroEotDivergente, setFiltroEotDivergente] = useState(false);
  const [filtroCruzaGh, setFiltroCruzaGh] = useState(false);
  const [filtroGhInconsistente, setFiltroGhInconsistente] = useState(false);
  const [graficoSerieAtiva, setGraficoSerieAtiva] = useState("");
  const [graficoFonte, setGraficoFonte] = useState("status");
  const [filtroMultiDivergencias, setFiltroMultiDivergencias] = useState(false);

  const segmentosGhDetalhe = detalheDados?.detraf?.segmentos_gh || [];
  const partesGhOrigem = detalheDados?.detraf?.partes_gh_origem || [];
  const possuiGhNormal = segmentosGhDetalhe.some((seg) => seg.gh === "N");
  const possuiGhReduzido = segmentosGhDetalhe.some((seg) => seg.gh === "R");
  const possuiTrocaGh = segmentosGhDetalhe.some((seg, idx) => idx > 0 && seg.gh !== segmentosGhDetalhe[idx - 1].gh);
  const mostrarDistribuicaoGh =
    segmentosGhDetalhe.length > 1 && possuiGhNormal && possuiGhReduzido && possuiTrocaGh;
  const dashboardResumo = resumo?.dashboard || {};
  const dashboardDetraf = dashboardResumo.detraf || {};
  const chamadasOutros = dashboardDetraf?.chamadas_outros || 0;
  const totalChamadasClassificadas =
    (dashboardDetraf?.chamadas_moveis || 0) +
    (dashboardDetraf?.chamadas_fixas || 0) +
    (dashboardDetraf?.chamadas_cng || 0) +
    chamadasOutros;
  const timelineStatus = resumo?.timeline?.status || [];
  const timelineTarifas = resumo?.timeline?.tarifas || [];
  const graficoSeriesMeta = graficoFonte === "tarifas" ? SERIES_TARIFAS : SERIES_STATUS;
  const timelineFonte = graficoFonte === "tarifas" ? timelineTarifas : timelineStatus;
  const dadosGrafico = useMemo(() => {
    if (!timelineFonte?.length) return [];
    return timelineFonte.map((item) => {
      const referencia = item?.data || item?.dia || item?.referencia || "";
      const ponto = { data: referencia };
      graficoSeriesMeta.forEach((serie) => {
        ponto[serie.id] = Number(item?.[serie.id] ?? 0);
      });
      return ponto;
    });
  }, [timelineFonte, graficoSeriesMeta]);
  const graficoDescricao =
    graficoFonte === "tarifas"
      ? "Linha temporal de chamadas por tarifa aplicada"
      : "Status da conferência (conferidos, divergentes e perdidos por data)";
  const graficoSerieEmDestaque = graficoSeriesMeta.find((serie) => serie.id === graficoSerieAtiva)?.label;
const MAPA_LABEL_MOTIVOS = {
  status: "Status divergente",
  duracao: "Duração divergente",
  eot: "EOT divergente",
  sem_par: "Chamada perdida (sem par)",
  gh: "Grupo horário divergente",
  gh_cruzado: "Cruzou grupo horário",
};
const TIPOS_RESUMO_DIVERGENCIA = new Set(["sem_par", "eot", "duracao", "gh"]);
  const motivosFrequentesOrigem = dashboardResumo?.divergencias_por_tipo || [];
  const totalMotivosFrequentes = motivosFrequentesOrigem.reduce((acc, item) => acc + (item.quantidade || 0), 0);
  const motivosFrequentes = motivosFrequentesOrigem.map((item) => ({
    ...item,
    label: MAPA_LABEL_MOTIVOS[item.tipo?.toLowerCase()] || item.tipo,
  }));
  const totalStatusDivergente = motivosFrequentesOrigem
    .filter((item) => (item.tipo || "").toLowerCase() === "status")
    .reduce((acc, item) => acc + (item.quantidade || 0), 0);
  const arquivoMetricas = dashboardResumo?.arquivo || {};
  const totalRegistrosArquivo = formatarNumero(arquivoMetricas.registros || 0);
  const totalChamadasArquivo = formatarNumero(
    arquivoMetricas.chamadas || dashboardDetraf?.chamadas_totais || 0
  );
  const totalMinutosArquivo = formatarMinutosComSufixo(arquivoMetricas.segundos_totais);
  const statusResumo = resumo?.resumo || [];
  const statusMap = statusResumo.reduce((acc, item) => {
    acc[item.status] = item;
    return acc;
  }, {});
  const totalConferidos = statusMap.CONFERIDO?.total || 0;
  const totalDivergentes = statusMap.DIVERGENTE?.total || 0;
  const totalPerdidos = statusMap.PERDIDO?.total || 0;
  const statusPieData = [
    { name: "Conferidos", value: totalConferidos, color: "#34d399" },
    { name: "Divergentes", value: totalDivergentes, color: "#fbbf24" },
    { name: "Perdidos", value: totalPerdidos, color: "#f87171" },
  ];
  const totalStatusDistribuicao = statusPieData.reduce((acc, item) => acc + item.value, 0);
  const statusBarData = statusPieData.map((item) => ({
    name: item.name,
    value: item.value,
    fill: item.color,
  }));
  const chamadasTarifaTotal = (dashboardDetraf?.chamadas_moveis || 0) + (dashboardDetraf?.chamadas_fixas || 0);
  const segundosTarifaTotal = (dashboardDetraf?.segundos_moveis || 0) + (dashboardDetraf?.segundos_fixas || 0);
  const tarifaResumo = [
    {
      id: "total",
      label: "Total tarifado (VU-M + TU-RL)",
      total: chamadasTarifaTotal,
      minutos: segundosTarifaTotal,
    },
    {
      id: "movel",
      label: "Chamadas móveis (VU-M)",
      total: dashboardDetraf?.chamadas_moveis || 0,
      minutos: dashboardDetraf?.segundos_moveis || 0,
    },
    {
      id: "fixo",
      label: "Chamadas fixas (TU-RL)",
      total: dashboardDetraf?.chamadas_fixas || 0,
      minutos: dashboardDetraf?.segundos_fixas || 0,
    },
  ];
  const acaoResumoTarifa = {
    movel: "tarifa-vum",
    fixo: "tarifa-turl",
  };
  const tarifaBarData = tarifaResumo
    .filter((item) => item.id !== "total")
    .map((item) => ({
      name: item.label,
      value: item.total,
      minutos: item.minutos,
      fill: item.id === "fixo" ? "#60a5fa" : "#34d399",
    }));
  const destinoResumo = [
    {
      id: "dest-movel",
      label: "Saída com destino móvel",
      total: dashboardDetraf?.chamadas_destino_movel || 0,
      minutos: dashboardDetraf?.segundos_destino_movel || 0,
    },
    {
      id: "dest-fixo",
      label: "Saída com destino fixo",
      total: dashboardDetraf?.chamadas_destino_fixo || 0,
      minutos: dashboardDetraf?.segundos_destino_fixo || 0,
    },
    {
      id: "dest-cng",
      label: "Entrada 0800 / CNG",
      total: dashboardDetraf?.chamadas_cng || 0,
      minutos: dashboardDetraf?.segundos_cng || 0,
    },
  ];
  const destinoPieData = destinoResumo.map((item, idx) => ({
    name: item.label,
    value: item.total,
    color: PIE_COLORS[(idx + 3) % PIE_COLORS.length],
  }));
  const totalDestinoDistribuicao = destinoPieData.reduce((acc, item) => acc + item.value, 0);
  const destinoBarData = destinoResumo.map((item, idx) => ({
    name: item.label,
    value: item.total,
    fill: PIE_COLORS[(idx + 3) % PIE_COLORS.length],
  }));
const tooltipBaseStyle = {
  backgroundColor: "#09090b",
  borderColor: "#27272a",
  borderRadius: "0.5rem",
  color: "#f4f4f5",
};
const tooltipCursorStyle = { fill: "rgba(255,255,255,0.04)" };
  const minutosValidos = dashboardResumo?.segundos_validos || 0;
  const minutosInvalidos = dashboardResumo?.segundos_invalidos || 0;
  const segundosNormaisCobrados = resumo?.gh_metricas?.segundos_normais_cobrados || 0;
  const segundosReduzidosCobrados = resumo?.gh_metricas?.segundos_reduzidos_cobrados || 0;
  const segundosNormaisValidados = resumo?.gh_metricas?.segundos_normais_validados || 0;
  const segundosReduzidosValidados = resumo?.gh_metricas?.segundos_reduzidos_validados || 0;
  const segundosTotaisCobrados = segundosNormaisCobrados + segundosReduzidosCobrados;
  const minutosNaoValidados = Math.max(segundosTotaisCobrados - minutosValidos, 0);

  const normalDistribuicao = useMemo(() => {
    if (segundosNormaisCobrados === 0 && segundosNormaisValidados === 0) {
      return { cobrados: 0, validados: 0, naoValidados: 0 };
    }
    const proporcao = segundosNormaisCobrados / (segundosNormaisCobrados + segundosReduzidosCobrados || 1);
    const validadosProporcionais = minutosValidos * proporcao;
    const validados = Math.min(segundosNormaisCobrados, validadosProporcionais);
    const naoValidados = Math.max(segundosNormaisCobrados - validados, 0);
    return {
      cobrados: segundosNormaisCobrados,
      validados,
      naoValidados,
    };
  }, [segundosNormaisCobrados, segundosReduzidosCobrados, minutosValidos]);

  const reduzidoDistribuicao = useMemo(() => {
    if (segundosReduzidosCobrados === 0 && segundosReduzidosValidados === 0) {
      return { cobrados: 0, validados: 0, naoValidados: 0 };
    }
    const proporcao =
      segundosReduzidosCobrados / (segundosNormaisCobrados + segundosReduzidosCobrados || 1);
    const validadosProporcionais = minutosValidos * proporcao;
    const validados = Math.min(segundosReduzidosCobrados, validadosProporcionais);
    const naoValidados = Math.max(segundosReduzidosCobrados - validados, 0);
    return {
      cobrados: segundosReduzidosCobrados,
      validados,
      naoValidados,
    };
  }, [segundosNormaisCobrados, segundosReduzidosCobrados, minutosValidos]);
  const divergenciasDetalhe = [
    {
      label: "Perdidos",
      value: totalPerdidos,
      subtitle: "Sem pareamento ou sem CDR",
      tone: "negative",
    },
    {
      label: "Status divergente",
      value: totalStatusDivergente,
      subtitle: "Status diferente de atendido",
      tone: "warning",
    },
    {
      label: "EOT divergente",
      value: dashboardResumo?.chamadas_eot_divergente || 0,
      tone: "warning",
    },
    {
      label: "Duração acima da tolerância",
      value: dashboardResumo?.chamadas_delta_acima_tolerancia || 0,
      tone: "warning",
    },
    {
      label: "GH divergente",
      value: dashboardResumo?.chamadas_gh_divergente || 0,
      tone: "negative",
    },
    {
      label: "Múltiplas divergências",
      value: dashboardResumo?.chamadas_multiplas_divergencias || 0,
    },
  ];
  const dadosPizzaDivergencias = divergenciasDetalhe
    .filter((item) => item.value > 0)
    .map((item, idx) => ({
      name: item.label,
      value: item.value,
      fill: DIVERGENCIA_CORES[item.label] || PIE_COLORS[idx % PIE_COLORS.length],
    }));
  const pdfResumoDados = useMemo(() => {
    if (!resumo) return null;
    const visaoArquivo = [
      {
        label: "Total de registros",
        value: totalRegistrosArquivo,
        subtitle: "Linhas presentes no DETRAF recebido",
      },
      {
        label: "Total de chamadas",
        value: totalChamadasArquivo,
        subtitle: "Após consolidar assinante A/B",
      },
      {
        label: "Total de minutos cobrados",
        value: totalMinutosArquivo,
        subtitle: "Somatório informado pela operadora",
      },
    ];
    const resumoMinutos = [
      {
        label: "Minutos cobrados",
        value: formatarMinutosComSufixo(segundosTotaisCobrados),
        subtitle: "Informado pela operadora",
        color: "#0f172a",
      },
      {
        label: "Minutos validados",
        value: formatarMinutosComSufixo(minutosValidos),
        subtitle: "Conferência validada",
        color: "#065f46",
      },
      {
        label: "Minutos inválidos",
        value: formatarMinutosComSufixo(minutosInvalidos),
        subtitle: "Pendentes ou divergentes",
        color: "#7f1d1d",
      },
    ];
    const statusCards = [
      { label: "Conferidos", value: formatarNumero(totalConferidos), subtitle: "Batimentos validados", color: "#34d399" },
      { label: "Divergentes", value: formatarNumero(totalDivergentes), subtitle: "Registros com apontamento", color: "#fbbf24" },
      { label: "Perdidos", value: formatarNumero(totalPerdidos), subtitle: "Sem pareamento ou sem CDR", color: "#f87171" },
    ];
    const tarifas = tarifaResumo.map((item) => ({
      label: item.label,
      value: formatarNumero(item.total || 0),
      subtitle: `Minutos: ${formatarMinutosComSufixo(item.minutos)}`,
      color: item.id === "movel" ? "#34d399" : item.id === "fixo" ? "#60a5fa" : "#cbd5f5",
    }));
    const divergencias = divergenciasDetalhe.map((item) => {
      const ehStatus = item.label === "Status divergente";
      return {
        label: ehStatus ? "Status da chamada divergente" : item.label,
        value: formatarNumero(item.value || 0),
        subtitle: ehStatus || item.label === "Perdidos" ? undefined : item.subtitle,
        color: DIVERGENCIA_CORES[item.label] || "#94a3b8",
      };
    });
    const distribuicaoGh = [
      {
        label: "GH normal cobrados",
        value: formatarMinutosComSufixo(segundosNormaisCobrados),
        subtitle: "Período normal",
      },
      {
        label: "GH normal validados",
        value: formatarMinutosComSufixo(segundosNormaisValidados),
        subtitle: "Período normal",
      },
      {
        label: "GH reduzido cobrados",
        value: formatarMinutosComSufixo(segundosReduzidosCobrados),
        subtitle: "Período reduzido",
      },
      {
        label: "GH reduzido validados",
        value: formatarMinutosComSufixo(segundosReduzidosValidados),
        subtitle: "Período reduzido",
      },
      {
        label: "Minutos inválidos",
        value: formatarMinutosComSufixo(minutosInvalidos),
        subtitle: "Fora da validação",
      },
    ].filter((item) => item.value !== "--");

    return {
      importacao: resumo.importacao || {},
      geradoEm: new Date(),
      arquivoVisao: visaoArquivo,
      resumoMinutos,
      statusCards,
      tarifas,
      divergencias,
      distribuicaoGh,
    };
  }, [
    resumo,
    segundosTotaisCobrados,
    minutosValidos,
    minutosInvalidos,
    totalConferidos,
    totalDivergentes,
    totalPerdidos,
    totalRegistrosArquivo,
    totalChamadasArquivo,
    totalMinutosArquivo,
    tarifaResumo,
    divergenciasDetalhe,
    segundosNormaisCobrados,
    segundosNormaisValidados,
    segundosReduzidosCobrados,
    segundosReduzidosValidados,
  ]);
  const baixarResumoPdf = useCallback(async () => {
    if (!pdfResumoDados) {
      setMensagem((msg) => msg || "Carregue uma importação antes de exportar o PDF.");
      return;
    }
    try {
      await exportarResumoPdf(pdfResumoDados);
    } catch (erro) {
      console.error(erro);
      setMensagem((msg) => msg || erro.message || "Não foi possível gerar o PDF do resumo.");
    }
  }, [pdfResumoDados, setMensagem]);
  const acaoDivergenciaResumo = {
    Perdidos: "status-perdidos",
    "EOT divergente": "eot",
    "Duração acima da tolerância": "delta",
    "GH divergente": "gh-divergente",
    "Múltiplas divergências": "multi-divergencias",
  };

  const restaurarPeriodoPadrao = useCallback(() => {
    setDatasPersonalizadas(true);
    setFiltroDataInicio("");
    setFiltroDataFim("");
  }, []);

  const resetarFiltrosTabela = useCallback(
    (reporPeriodo = false) => {
      setStatusFiltro([]);
      setApenasSemCdr(false);
      setFiltroDescritor("");
      setFiltroGh("");
      setFiltroDiferenca(false);
      setFiltroEotDivergente(false);
      setFiltroCruzaGh(false);
      setFiltroGhInconsistente(false);
      setFiltroTarifa("");
      setMostrarApenasCng(false);
      setFiltroSigame(false);
      setFiltroAssinanteA("");
      setFiltroAssinanteB("");
      if (reporPeriodo) {
        restaurarPeriodoPadrao();
      }
      setMostrarAvancados(false);
      setFiltroMultiDivergencias(false);
    },
    [restaurarPeriodoPadrao]
  );

  const aplicarResumo = useCallback(
    (acao) => {
      setVisaoPainel("painel");
      setPagina(1);
      resetarFiltrosTabela(true);

      switch (acao) {
        case "status-validas":
          setStatusFiltro(["CONFERIDO"]);
          break;
        case "status-invalidas":
          setStatusFiltro(["DIVERGENTE", "PERDIDO"]);
          break;
        case "status-perdidos":
          setStatusFiltro(["PERDIDO"]);
          break;
        case "status-divergentes":
          setStatusFiltro(["DIVERGENTE"]);
          break;
        case "status-conferidos":
          setStatusFiltro(["CONFERIDO"]);
          break;
        case "tarifa-vum":
          setFiltroTarifa("VU-M");
          setMostrarAvancados(true);
          break;
        case "tarifa-turl":
          setFiltroTarifa("TU-RL");
          setMostrarAvancados(true);
          break;
        case "tarifa-cng":
          setMostrarApenasCng(true);
          setMostrarAvancados(true);
          break;
        case "cruza-gh":
          setFiltroCruzaGh(true);
          setMostrarAvancados(true);
          break;
        case "eot":
          setFiltroEotDivergente(true);
          setMostrarAvancados(true);
          break;
        case "gh-divergente":
          setFiltroGhInconsistente(true);
          setMostrarAvancados(true);
          break;
        case "delta":
          setFiltroDiferenca(true);
          setMostrarAvancados(true);
          break;
        case "multi-divergencias":
          setFiltroMultiDivergencias(true);
          setMostrarAvancados(true);
          break;
        case "sigame":
          setFiltroSigame(true);
          setMostrarAvancados(true);
          break;
        default:
          break;
      }
    },
    [resetarFiltrosTabela]
  );
  const destacarSerieGrafico = useCallback(
    (fonte = "status", serie = "") => {
      setVisaoPainel("geral");
      const mesmoFonte = graficoFonte === fonte;
      setGraficoFonte(fonte);
      setGraficoSerieAtiva((atual) => {
        if (!serie) return "";
        if (mesmoFonte && atual === serie) {
          return "";
        }
        return serie;
      });
    },
    [graficoFonte]
  );
  const alterarFonteGrafico = useCallback(
    (fonte) => {
      if (graficoFonte === fonte) return;
      setVisaoPainel("geral");
      setGraficoFonte(fonte);
      setGraficoSerieAtiva("");
    },
    [graficoFonte]
  );
  const renderizarTooltipGrafico = useCallback(
    ({ active, payload, label }) => {
      if (!active || !payload?.length) return null;
      return (
        <div className="rounded-lg border border-neutral-800 bg-neutral-900/90 px-3 py-2 text-xs text-gray-200 shadow-lg">
          <p className="text-gray-400">{formatarDataCompleta(label)}</p>
          <ul className="mt-1 space-y-0.5">
            {payload.map((item) => {
              const meta = graficoSeriesMeta.find((serie) => serie.id === item.dataKey) || {};
              return (
                <li key={item.dataKey} className="flex items-center justify-between gap-6">
                  <span className="flex items-center gap-2 text-gray-300">
                    <span className="h-2 w-2 rounded-full" style={{ backgroundColor: meta.color || item.color }}></span>
                    {meta.label || item.name || item.dataKey}
                  </span>
                  <span className="font-semibold text-white">{formatarNumero(item.value)}</span>
                </li>
              );
            })}
          </ul>
        </div>
      );
    },
    [graficoSeriesMeta]
  );

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
    if (!resumo?.importacao || datasPersonalizadas) return;
    const { periodo_inicial, periodo_final } = resumo.importacao;
    setFiltroDataInicio(periodo_inicial ? paraDatetimeLocal(periodo_inicial) : "");
    setFiltroDataFim(periodo_final ? paraDatetimeLocal(periodo_final) : "");
  }, [resumo, datasPersonalizadas]);

  useEffect(() => {
    if (!resumo?.importacao?.id) return;
    setDatasPersonalizadas(false);
  }, [resumo?.importacao?.id]);

  useEffect(() => {
    if (!idClienteAtual) {
      setCdrs([]);
      setCdrSelecionado("");
      return;
    }
    carregarCdrs(idClienteAtual, true);
  }, [idClienteAtual]);
  useEffect(() => {
    if (!resumo?.importacao?.id) return;
    setGraficoSerieAtiva("");
  }, [resumo?.importacao?.id]);

  useEffect(() => {
    setPagina(1);
  }, [
    statusFiltro,
    apenasSemCdr,
    filtroDescritor,
    filtroGh,
    filtroDiferenca,
    filtroEotDivergente,
    filtroCruzaGh,
    filtroGhInconsistente,
    filtroGhInconsistente,
    filtroTarifa,
    mostrarApenasCng,
    filtroAssinanteA,
    filtroAssinanteB,
    filtroDataInicio,
    filtroDataFim,
    filtroMultiDivergencias,
    filtroSigame,
  ]);

  useEffect(() => {
    if (!selecionada) return;
    carregarResultados();
  }, [
    selecionada,
    pagina,
    statusFiltro,
    apenasSemCdr,
    filtroDescritor,
    filtroGh,
    filtroDiferenca,
    filtroEotDivergente,
    filtroCruzaGh,
    filtroTarifa,
    mostrarApenasCng,
    filtroAssinanteA,
    filtroAssinanteB,
    filtroDataInicio,
    filtroDataFim,
    filtroMultiDivergencias,
    filtroSigame,
  ]);

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
      if (apenasSemCdr) params.set("apenas_sem_cdr", "true");
      if (filtroDescritor) params.set("descritor", filtroDescritor);
      if (filtroGh) params.set("gh", filtroGh);
      if (filtroDiferenca) params.set("diferenca_min", String(DIFERENCA_TOLERANCIA_SEG));
      if (filtroEotDivergente) params.set("eot_divergente", "true");
      if (filtroCruzaGh) params.set("cruza_gh", "true");
      if (filtroGhInconsistente) params.set("gh_inconsistente", "true");
      if (filtroTarifa) params.set("tarifa", filtroTarifa);
      if (mostrarApenasCng) params.set("tarifa", "CNG");
      if (filtroMultiDivergencias) params.set("multi_divergencias", "true");
      if (filtroSigame) params.set("sigame", "true");
      if (filtroSigame) params.set("sigame", "true");
      const assinanteASaneado = sanitizarTelefoneFiltro(filtroAssinanteA);
      const assinanteBSaneado = sanitizarTelefoneFiltro(filtroAssinanteB);
      if (assinanteASaneado) params.set("assinante_a", assinanteASaneado);
      if (assinanteBSaneado) params.set("assinante_b", assinanteBSaneado);
      if (filtroDataInicio) params.set("data_inicio", filtroDataInicio);
      if (filtroDataFim) params.set("data_fim", filtroDataFim);

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
      if (apenasSemCdr) params.set("apenas_sem_cdr", "true");
      if (filtroDescritor) params.set("descritor", filtroDescritor);
      if (filtroGh) params.set("gh", filtroGh);
      if (filtroDiferenca) params.set("diferenca_min", String(DIFERENCA_TOLERANCIA_SEG));
      if (filtroEotDivergente) params.set("eot_divergente", "true");
      if (filtroCruzaGh) params.set("cruza_gh", "true");
      if (filtroGhInconsistente) params.set("gh_inconsistente", "true");
      if (filtroTarifa) params.set("tarifa", filtroTarifa);
      if (mostrarApenasCng) params.set("tarifa", "CNG");
      if (filtroMultiDivergencias) params.set("multi_divergencias", "true");
      const assinanteASaneado = sanitizarTelefoneFiltro(filtroAssinanteA);
      const assinanteBSaneado = sanitizarTelefoneFiltro(filtroAssinanteB);
      if (assinanteASaneado) params.set("assinante_a", assinanteASaneado);
      if (assinanteBSaneado) params.set("assinante_b", assinanteBSaneado);
      if (filtroDataInicio) params.set("data_inicio", filtroDataInicio);
      if (filtroDataFim) params.set("data_fim", filtroDataFim);

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
          forcar_normalizacao: Boolean(forcarNormalizacao),
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
    resetarFiltrosTabela(true);
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
      if (detalhesNormalizados?.detraf) {
        const detrafInfo = detalhesNormalizados.detraf;
        if (detrafInfo.segmentos_gh && !Array.isArray(detrafInfo.segmentos_gh)) {
          try {
            detrafInfo.segmentos_gh = JSON.parse(detrafInfo.segmentos_gh);
          } catch {
            detrafInfo.segmentos_gh = [];
          }
        }
        if (detrafInfo.partes_gh_origem && !Array.isArray(detrafInfo.partes_gh_origem)) {
          try {
            detrafInfo.partes_gh_origem = JSON.parse(detrafInfo.partes_gh_origem);
          } catch {
            detrafInfo.partes_gh_origem = [];
          }
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
            <div className="space-y-3">
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
              <label className="flex items-center gap-2 text-sm text-gray-200">
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded border-neutral-600 bg-neutral-900 text-primary focus:ring-primary"
                  checked={forcarNormalizacao}
                  onChange={(e) => setForcarNormalizacao(e.target.checked)}
                />
                Reprocessar normalização antes da conferência
              </label>
              <p className="text-xs text-gray-500">
                Recalcula DETRAF e CDR normalizados mesmo que já existam dados salvos — útil após ajustes de código.
              </p>
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

      <div className="mt-6 flex flex-wrap gap-2">
        {[
          { id: "painel", label: "Painel de conferência" },
          { id: "geral", label: "Resumo geral" },
        ].map((aba) => (
          <button
            key={aba.id}
            className={`rounded-t-xl border px-4 py-2 text-sm font-medium transition ${
              visaoPainel === aba.id
                ? "border-primary bg-neutral-900 text-white"
                : "border-transparent bg-neutral-800/60 text-gray-400 hover:text-white"
            }`}
            onClick={() => setVisaoPainel(aba.id)}
          >
            {aba.label}
          </button>
        ))}
      </div>

      {visaoPainel === "painel" ? (
        <>
      <div className="grid gap-4 md:grid-cols-3">
        <div className="rounded-xl border border-neutral-700 bg-neutral-900 p-4">
          <p className="text-xs uppercase tracking-wide text-gray-400">Processadas</p>
          <p className="mt-2 text-2xl font-semibold text-white">
            {carregandoResumo ? "--" : formatarNumero(resumo?.status?.processadas)}
          </p>
          <p className="text-xs text-gray-500">Registros DETRAF analisados</p>
        </div>
        <button
          type="button"
          onClick={() => aplicarResumo("status-validas")}
          className="text-left rounded-xl border border-neutral-700 bg-neutral-900 p-4 transition hover:border-primary/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
        >
          <p className="text-xs uppercase tracking-wide text-gray-400">Válidas</p>
          <p className="mt-2 text-2xl font-semibold text-emerald-400">
            {carregandoResumo ? "--" : formatarNumero(resumo?.status?.validas)}
          </p>
          <p className="text-xs text-gray-500">Batimentos conferidos</p>
        </button>
        <button
          type="button"
          onClick={() => aplicarResumo("status-invalidas")}
          className="text-left rounded-xl border border-neutral-700 bg-neutral-900 p-4 transition hover:border-primary/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
        >
          <p className="text-xs uppercase tracking-wide text-gray-400">Inválidas</p>
          <p className="mt-2 text-2xl font-semibold text-red-400">
            {carregandoResumo ? "--" : formatarNumero(resumo?.status?.invalidas)}
          </p>
          <p className="text-xs text-gray-500">Divergências + perdidos</p>
          {!carregandoResumo && dashboardResumo?.segundos_invalidos !== undefined && (
            <p className="text-xs text-gray-500">Minutos: {formatarMinutos(dashboardResumo.segundos_invalidos)}</p>
          )}
        </button>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        {(resumo?.resumo || statusChips.map(({ id }) => ({ status: id, total: 0, percentual: 0 }))).map((item) => {
          const meta = STATUS_META[item.status] || {};
          const serieId = STATUS_TO_SERIE[item.status] || "";
          const ativo = serieId && graficoSerieAtiva === serieId;
          return (
            <button
              type="button"
              key={item.status}
              onClick={() => serieId && destacarSerieGrafico("status", serieId)}
              className={obterClasseCardResumo(ativo)}
            >
              <p className={`text-sm font-medium ${meta.color || "text-gray-200"}`}>{meta.label || item.status}</p>
              <div className="mt-2 flex items-baseline gap-2">
                <span className="text-3xl font-semibold text-white">
                  {carregandoResumo && !resumo ? "--" : formatarNumero(item.total)}
                </span>
                <span className="text-sm text-gray-400">
                  ({carregandoResumo && !resumo ? "--" : (item.percentual ?? 0)}%)
                </span>
              </div>
              {serieId && <p className="mt-2 text-xs text-gray-500">Clique para destacar no gráfico.</p>}
            </button>
          );
        })}
      </div>

      <div className="rounded-2xl border border-neutral-800 bg-neutral-900 p-4 space-y-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-wrap gap-2">
            {statusChips.map((item) => (
              <Chip key={item.id} active={statusFiltro.includes(item.id)} onClick={() => toggleStatus(item.id)}>
                {item.label}
              </Chip>
            ))}
          </div>
          <button
            className="self-start rounded-lg border border-neutral-700 px-3 py-1.5 text-xs uppercase tracking-wide text-gray-400 transition hover:border-primary/60 hover:text-white lg:self-auto"
            onClick={() => setMostrarAvancados((prev) => !prev)}
          >
            {mostrarAvancados ? "Ocultar filtros avançados" : "Mostrar filtros avançados"}
          </button>
        </div>

        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
          <div className="flex flex-col gap-1 text-xs text-gray-400">
            <span>Data inicial</span>
            <input
              type="datetime-local"
              value={filtroDataInicio}
              onChange={(e) => {
                setDatasPersonalizadas(true);
                setFiltroDataInicio(e.target.value);
              }}
              className="rounded-lg border border-neutral-700 bg-dark px-3 py-2 text-sm text-gray-200 focus:border-primary"
            />
          </div>
          <div className="flex flex-col gap-1 text-xs text-gray-400">
            <span>Data final</span>
            <input
              type="datetime-local"
              value={filtroDataFim}
              onChange={(e) => {
                setDatasPersonalizadas(true);
                setFiltroDataFim(e.target.value);
              }}
              className="rounded-lg border border-neutral-700 bg-dark px-3 py-2 text-sm text-gray-200 focus:border-primary"
            />
          </div>
          <div className="flex flex-col gap-1 text-xs text-gray-400">
            <span>Assinante A</span>
            <input
              type="text"
              value={filtroAssinanteA}
              onChange={(e) => setFiltroAssinanteA(formatarTelefoneExibicao(e.target.value))}
              placeholder="DDD + número"
              className="rounded-lg border border-neutral-700 bg-dark px-3 py-2 text-sm text-gray-200 focus:border-primary"
            />
          </div>
          <div className="flex flex-col gap-1 text-xs text-gray-400">
            <span>Assinante B</span>
            <input
              type="text"
              value={filtroAssinanteB}
              onChange={(e) => setFiltroAssinanteB(formatarTelefoneExibicao(e.target.value))}
              placeholder="DDD + número"
              className="rounded-lg border border-neutral-700 bg-dark px-3 py-2 text-sm text-gray-200 focus:border-primary"
            />
          </div>
        </div>

        <div className="flex flex-wrap justify-end gap-2">
          <button className="btn-secondary" onClick={limparFiltros}>
            Limpar filtros
          </button>
        </div>

        {mostrarAvancados && (
          <div className="space-y-4 border-t border-neutral-800 pt-4">
            <div className="flex flex-wrap gap-2">
              <Chip active={apenasSemCdr} onClick={() => setApenasSemCdr((prev) => !prev)}>
                Sem CDR
              </Chip>
              <Chip active={filtroDiferenca} onClick={() => setFiltroDiferenca((prev) => !prev)}>
                {`Diferença de duração > ${DIFERENCA_TOLERANCIA_SEG}s`}
              </Chip>
              <Chip active={filtroEotDivergente} onClick={() => setFiltroEotDivergente((prev) => !prev)}>
                EOT divergente
              </Chip>
              <Chip active={filtroCruzaGh} onClick={() => setFiltroCruzaGh((prev) => !prev)}>
                Cruza GH
              </Chip>
              <Chip active={filtroGhInconsistente} onClick={() => setFiltroGhInconsistente((prev) => !prev)}>
                GH divergente
              </Chip>
              <Chip active={mostrarApenasCng} onClick={() => setMostrarApenasCng((prev) => !prev)}>
                Somente CNG/0800
              </Chip>
              <Chip active={filtroSigame} onClick={() => setFiltroSigame((prev) => !prev)}>
                Chamadas com siga-me
              </Chip>
              <Chip active={filtroMultiDivergencias} onClick={() => setFiltroMultiDivergencias((prev) => !prev)}>
                Múltiplas divergências
              </Chip>
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

            <div className="flex flex-wrap gap-2">
              {[
                { id: "", label: "Todas as tarifas" },
                { id: "VU-M", label: "Móvel (VU-M)" },
                { id: "TU-RL", label: "Fixo (TU-RL)" },
              ].map((opcao) => (
                <Chip
                  key={`tarifa-${opcao.id || "all"}`}
                  active={filtroTarifa === opcao.id}
                  onClick={() => setFiltroTarifa((atual) => (atual === opcao.id ? "" : opcao.id))}
                >
                  {opcao.label}
                </Chip>
              ))}
            </div>
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
                  <td className="px-4 py-3 align-top">
                    <div className="flex flex-col gap-1">
                      <span>{item.assinante_b || "--"}</span>
                    </div>
                  </td>
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
                    {item.divergencias?.length ? (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {item.divergencias.map((tipo, idx) => (
                          <span
                            key={`${item.id}-div-${idx}-${tipo}`}
                            className="rounded-full border border-amber-400/40 bg-amber-500/10 px-2 py-0.5 text-xs uppercase tracking-wide text-amber-200"
                          >
                            {tipo}
                          </span>
                        ))}
                      </div>
                    ) : null}
                    {item.tem_multiplas_divergencias && (
                      <p className="mt-1 text-xs text-amber-300">{item.qtd_divergencias} divergências registradas</p>
                    )}
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
        </>
      ) : (
        <div className="space-y-10">
          <div className="flex justify-end">
            <button className="btn-secondary" onClick={baixarResumoPdf} disabled={!pdfResumoDados}>
              Baixar resumo (PDF)
            </button>
          </div>
          <SectionBlock
            title="Visão do arquivo"
            subtitle="Totais diretamente do DETRAF recebido da operadora."
            extra={
              resumo?.importacao?.arquivo ? (
                <p className="text-xs text-gray-500">Arquivo: {resumo.importacao.arquivo}</p>
              ) : null
            }
          >
            <div className="grid gap-4 md:grid-cols-3">
              <DataCard
                title="Total de registros"
                value={carregandoResumo ? "--" : totalRegistrosArquivo}
                subtitle="Linhas presentes no arquivo"
              />
              <DataCard
                title="Total de chamadas"
                value={carregandoResumo ? "--" : totalChamadasArquivo}
                subtitle="Assinante A + Assinante B consolidados"
              />
              <DataCard
                title="Total de minutos cobrados"
                value={carregandoResumo ? "--" : totalMinutosArquivo}
                subtitle="Informado na remuneração DETRAF"
              />
            </div>
          </SectionBlock>

          <SectionBlock
            title="Conferência por status"
            subtitle="Distribuição do batimento em conferidos, divergentes e perdidos."
          >
            <div className="grid gap-3 sm:grid-cols-3">
              {["CONFERIDO", "DIVERGENTE", "PERDIDO"].map((status) => {
                const meta = STATUS_META[status] || {};
                const serieId = STATUS_TO_SERIE[status] || "";
                const totalStatus = statusMap[status]?.total || 0;
                return (
                  <DataCard
                    key={status}
                    title={meta.label || status}
                    value={carregandoResumo ? "--" : formatarNumero(totalStatus)}
                    subtitle="Clique para destacar no gráfico"
                    onClick={() => serieId && destacarSerieGrafico("status", serieId)}
                    active={graficoFonte === "status" && graficoSerieAtiva === serieId}
                    tone={
                      status === "CONFERIDO" ? "positive" : status === "DIVERGENTE" ? "warning" : "negative"
                    }
                  />
                );
              })}
            </div>
            <div className="h-64 w-full rounded-xl border border-neutral-800/70 bg-neutral-950/60 p-3">
              {totalStatusDistribuicao ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={statusBarData}
                    margin={{ top: 10, right: 20, left: 0, bottom: 0 }}
                    barSize={32}
                    barCategoryGap="20%"
                  >
                    <CartesianGrid stroke="#27272a" strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fill: "#d4d4d8", fontSize: 12 }} />
                    <YAxis
                      axisLine={false}
                      tickLine={false}
                      tick={{ fill: "#a1a1aa", fontSize: 11 }}
                      allowDecimals={false}
                    />
                    <Tooltip
                      contentStyle={tooltipBaseStyle}
                      formatter={(value) => [formatarNumero(value), "Chamadas"]}
                      labelStyle={{ color: "#f4f4f5" }}
                      itemStyle={{ color: "#f4f4f5" }}
                      cursor={tooltipCursorStyle}
                    />
                    <Bar dataKey="value" shape={BAR_SHAPE} activeBar={BAR_SHAPE_ACTIVE}>
                      {statusBarData.map((item) => (
                        <Cell key={`bar-${item.name}`} fill={item.fill} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="flex h-full items-center justify-center text-xs text-gray-500">
                  Aguardando resultados da conferência.
                </div>
              )}
            </div>
          </SectionBlock>

          <SectionBlock
            title="Linha temporal"
            subtitle={`${graficoDescricao}${graficoSerieEmDestaque ? ` • Destaque: ${graficoSerieEmDestaque}` : ""}`}
            extra={
              <div className="flex flex-wrap gap-2">
                <Chip active={graficoFonte === "status"} onClick={() => alterarFonteGrafico("status")}>
                  Status
                </Chip>
                <Chip active={graficoFonte === "tarifas"} onClick={() => alterarFonteGrafico("tarifas")}>
                  Tarifas
                </Chip>
              </div>
            }
          >
            <div className="h-[320px] w-full">
              {dadosGrafico.length ? (
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={dadosGrafico} margin={{ top: 20, right: 10, left: 0, bottom: 0 }}>
                    <CartesianGrid stroke="#27272a" strokeDasharray="3 3" />
                    <XAxis dataKey="data" stroke="#52525b" tickFormatter={formatarDataCurta} />
                    <YAxis stroke="#52525b" tickFormatter={(value) => formatarNumero(value)} allowDecimals={false} />
                    <Tooltip content={renderizarTooltipGrafico} />
                    <Legend wrapperStyle={{ color: "#a1a1aa" }} />
                    {graficoSeriesMeta.map((serie) => (
                      <Line
                        key={serie.id}
                        type="monotone"
                        dataKey={serie.id}
                        name={serie.label}
                        stroke={serie.color}
                        strokeWidth={2.4}
                        dot={false}
                        activeDot={{ r: 4 }}
                        isAnimationActive={false}
                      />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              ) : (
                <div className="flex h-full items-center justify-center text-sm text-gray-500">
                  Sem dados suficientes para montar a linha temporal.
                </div>
              )}
            </div>
          </SectionBlock>

          <SectionBlock
            title="Tarifas aplicadas"
            subtitle="Distribuição de chamadas tarifadas pela operadora (VU-M e TU-RL)."
          >
            <div className="grid gap-3 md:grid-cols-3">
              {tarifaResumo.map((item) => (
                <DataCard
                  key={item.id}
                  title={item.label}
                  value={carregandoResumo ? "--" : formatarNumero(item.total)}
                  subtitle={`Minutos: ${carregandoResumo ? "--" : formatarMinutosComSufixo(item.minutos)}`}
                  onClick={() => item.id !== "total" && destacarSerieGrafico("tarifas", item.id)}
                  active={graficoFonte === "tarifas" && graficoSerieAtiva === item.id}
                />
              ))}
            </div>
            <div className="grid gap-3 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
              <div className="rounded-xl border border-neutral-800/70 bg-neutral-950/60 p-4">
                <p className="text-xs uppercase tracking-wide text-gray-400">Resumo gráfico</p>
                <div className="mt-3 h-64">
                  {tarifaBarData.length ? (
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={tarifaBarData} barSize={32} margin={{ top: 10, right: 16, left: -6, bottom: 0 }}>
                        <CartesianGrid stroke="#27272a" strokeDasharray="3 3" vertical={false} />
                        <XAxis dataKey="name" tick={{ fill: "#d4d4d8", fontSize: 12 }} axisLine={false} tickLine={false} />
                        <YAxis
                          tick={{ fill: "#a1a1aa", fontSize: 11 }}
                          axisLine={false}
                          tickLine={false}
                          allowDecimals={false}
                        />
                        <Tooltip
                          contentStyle={tooltipBaseStyle}
                          formatter={(value) => [formatarNumero(value), "Chamadas"]}
                          labelStyle={{ color: "#f4f4f5" }}
                          itemStyle={{ color: "#f4f4f5" }}
                          cursor={tooltipCursorStyle}
                        />
                        <Bar dataKey="value" shape={BAR_SHAPE} activeBar={BAR_SHAPE_ACTIVE}>
                          {tarifaBarData.map((item) => (
                            <Cell key={`tarifa-bar-${item.name}`} fill={item.fill} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  ) : (
                    <div className="flex h-full items-center justify-center text-xs text-gray-500">
                      Sem classificação por tarifa ainda.
                    </div>
                  )}
                </div>
              </div>
              <div className="space-y-3 rounded-xl border border-neutral-800/70 bg-neutral-950/60 p-4">
                <p className="text-xs uppercase tracking-wide text-gray-400">Atalhos rápidos</p>
                {["movel", "fixo"].map((id) => {
                  const item = tarifaResumo.find((registro) => registro.id === id);
                  if (!item) return null;
                  return (
                    <button
                      type="button"
                      key={`btn-${id}`}
                      onClick={() => aplicarResumo(acaoResumoTarifa[id])}
                      className="flex w-full items-center justify-between rounded-lg border border-neutral-800/60 px-3 py-2 text-left text-sm text-gray-200 transition hover:border-primary/60"
                    >
                      <span>{item.label}</span>
                      <span className="text-primary text-xs">Ver no painel</span>
                    </button>
                  );
                })}
                <p className="text-xs text-gray-500">
                  {carregandoResumo
                    ? "Carregando classificação por tarifa..."
                    : `Classificadas: ${formatarNumero(totalChamadasClassificadas)} de ${formatarNumero(
                        dashboardDetraf?.chamadas_totais || 0
                      )} chamadas DETRAF${
                        chamadasOutros ? ` • ${formatarNumero(chamadasOutros)} sem tarifa definida` : ""
                      }.`}
                </p>
              </div>
            </div>
          </SectionBlock>

          <SectionBlock title="Destinos (assinante B)" subtitle="Como as chamadas saíram da rede (móvel, fixo, 0800).">
            <div className="grid gap-3 md:grid-cols-3">
              {destinoResumo.map((item) => (
                <DataCard
                  key={item.id}
                  title={item.label}
                  value={carregandoResumo ? "--" : formatarNumero(item.total)}
                  subtitle={`Minutos: ${carregandoResumo ? "--" : formatarMinutosComSufixo(item.minutos)}`}
                />
              ))}
            </div>
            <div className="rounded-xl border border-neutral-800/70 bg-neutral-950/60 p-4">
              <div className="h-64">
                {totalDestinoDistribuicao ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={destinoBarData} barSize={30} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                      <CartesianGrid stroke="#27272a" strokeDasharray="3 3" vertical={false} />
                      <XAxis dataKey="name" tick={{ fill: "#d4d4d8", fontSize: 12 }} axisLine={false} tickLine={false} />
                      <YAxis
                        tick={{ fill: "#a1a1aa", fontSize: 11 }}
                        axisLine={false}
                        tickLine={false}
                        allowDecimals={false}
                      />
                      <Tooltip
                        contentStyle={tooltipBaseStyle}
                        formatter={(value) => [formatarNumero(value), "Chamadas"]}
                        labelStyle={{ color: "#f4f4f5" }}
                        itemStyle={{ color: "#f4f4f5" }}
                        cursor={tooltipCursorStyle}
                      />
                      <Bar dataKey="value" shape={BAR_SHAPE} activeBar={BAR_SHAPE_ACTIVE}>
                        {destinoBarData.map((item) => (
                          <Cell key={`dest-${item.name}`} fill={item.fill} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="flex h-full items-center justify-center text-xs text-gray-500">
                    Sem dados suficientes para montar o gráfico.
                  </div>
                )}
              </div>
            </div>
          </SectionBlock>

          <SectionBlock
            title="Minutos validados x cobrados"
            subtitle="Compare o que foi tarifado pela operadora com o que foi validado pela conferência."
          >
            <div className="grid gap-3 md:grid-cols-3">
              <DataCard
                title="Minutos cobrados"
                value={carregandoResumo ? "--" : formatarMinutosComSufixo(segundosTotaisCobrados)}
                subtitle="Somatório DETRAF (GH normal + reduzido)"
              />
              <DataCard
                title="Minutos validados"
                value={carregandoResumo ? "--" : formatarMinutosComSufixo(minutosValidos)}
                subtitle="Conferidos com sucesso"
                tone="positive"
              />
              <DataCard
                title="Minutos inválidos"
                value={carregandoResumo ? "--" : formatarMinutosComSufixo(minutosInvalidos)}
                subtitle="Pendentes, perdidos ou divergentes"
                tone="negative"
              />
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <div className="rounded-xl border border-neutral-800/70 bg-neutral-950/60 p-4 space-y-3">
                <p className="text-xs uppercase tracking-wide text-gray-400">Distribuição GH normal</p>
                <div className="grid gap-3 sm:grid-cols-3">
                  <div>
                    <p className="text-[11px] uppercase tracking-wide text-gray-500">Cobrados</p>
                    <p className="text-lg font-semibold text-gray-100">
                      {carregandoResumo ? "--" : formatarMinutosComSufixo(normalDistribuicao.cobrados)}
                    </p>
                  </div>
                  <div>
                    <p className="text-[11px] uppercase tracking-wide text-gray-500">Validados</p>
                    <p className="text-lg font-semibold text-emerald-300">
                      {carregandoResumo ? "--" : formatarMinutosComSufixo(normalDistribuicao.validados)}
                    </p>
                  </div>
                  <div>
                    <p className="text-[11px] uppercase tracking-wide text-gray-500">Não validados</p>
                    <p className="text-lg font-semibold text-rose-300">
                      {carregandoResumo ? "--" : formatarMinutosComSufixo(normalDistribuicao.naoValidados)}
                    </p>
                  </div>
                </div>
              </div>
              <div className="rounded-xl border border-neutral-800/70 bg-neutral-950/60 p-4 space-y-3">
                <p className="text-xs uppercase tracking-wide text-gray-400">Distribuição GH reduzido</p>
                <div className="grid gap-3 sm:grid-cols-3">
                  <div>
                    <p className="text-[11px] uppercase tracking-wide text-gray-500">Cobrados</p>
                    <p className="text-lg font-semibold text-gray-100">
                      {carregandoResumo ? "--" : formatarMinutosComSufixo(reduzidoDistribuicao.cobrados)}
                    </p>
                  </div>
                  <div>
                    <p className="text-[11px] uppercase tracking-wide text-gray-500">Validados</p>
                    <p className="text-lg font-semibold text-emerald-300">
                      {carregandoResumo ? "--" : formatarMinutosComSufixo(reduzidoDistribuicao.validados)}
                    </p>
                  </div>
                  <div>
                    <p className="text-[11px] uppercase tracking-wide text-gray-500">Não validados</p>
                    <p className="text-lg font-semibold text-rose-300">
                      {carregandoResumo ? "--" : formatarMinutosComSufixo(reduzidoDistribuicao.naoValidados)}
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </SectionBlock>

          <SectionBlock
            title="Divergências e perdidos"
            subtitle="Valores reais do batimento. Clique em um indicador para abrir o painel filtrado."
          >
            <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
              <div className="space-y-1 text-sm text-gray-300">
                {divergenciasDetalhe.map((item) => (
                  <button
                    key={item.label}
                    className="flex w-full items-center justify-between rounded-lg border border-neutral-700/60 bg-neutral-900/60 px-3 py-2 text-left transition hover:border-primary/60"
                    onClick={() => aplicarResumo(acaoDivergenciaResumo[item.label])}
                  >
                    <div className="flex flex-col">
                      <div className="flex items-center gap-2">
                        <span
                          className="h-2 w-2 rounded-full"
                          style={{ backgroundColor: DIVERGENCIA_CORES[item.label] || "#a1a1aa" }}
                        ></span>
                        <p className="text-[11px] uppercase tracking-wide text-gray-300">{item.label}</p>
                      </div>
                      {item.subtitle && <p className="text-[11px] text-gray-500 leading-tight">{item.subtitle}</p>}
                    </div>
                    <span
                      className="text-xl font-semibold"
                      style={{ color: DIVERGENCIA_CORES[item.label] || "#f4f4f5" }}
                    >
                      {carregandoResumo ? "--" : formatarNumero(item.value)}
                    </span>
                  </button>
                ))}
              </div>
              <div className="rounded-2xl border border-neutral-800/60 bg-neutral-950/50 p-4 flex flex-col gap-3">
                <div className="flex items-center justify-between text-xs uppercase tracking-wide text-gray-400">
                  <span>Distribuição das divergências</span>
                  <span>
                    Motivos registrados: {" "}
                    <span className="font-semibold text-white">{formatarNumero(totalMotivosFrequentes)}</span>
                  </span>
                </div>
                <div className="flex flex-1 items-center justify-center">
                  {dadosPizzaDivergencias.length ? (
                    <ResponsiveContainer width="100%" height={220}>
                      <PieChart>
                        <Pie
                          data={dadosPizzaDivergencias}
                          dataKey="value"
                          nameKey="name"
                          cx="45%"
                          cy="50%"
                          outerRadius={75}
                          innerRadius={40}
                          paddingAngle={3}
                          labelLine={false}
                          activeShape={renderPieSliceActive}
                          inactiveShape={renderPieSlice}
                        >
                          {dadosPizzaDivergencias.map((entry) => (
                            <Cell key={`div-pizza-${entry.name}`} fill={entry.fill} />
                          ))}
                        </Pie>
                        <Tooltip
                          contentStyle={tooltipBaseStyle}
                          formatter={(value, name) => [`${formatarNumero(value)} chamadas`, name]}
                          labelStyle={{ color: "#f4f4f5" }}
                          itemStyle={{ color: "#f4f4f5" }}
                          cursor={tooltipCursorStyle}
                        />
                      </PieChart>
                    </ResponsiveContainer>
                  ) : (
                    <div className="flex h-56 items-center justify-center text-xs text-gray-500">
                      Sem divergências registradas.
                    </div>
                  )}
                </div>
              </div>
            </div>
          </SectionBlock>

        </div>
      )}

      {mensagem && (
        <div className={`rounded-xl border p-3 text-sm ${obterClasseMensagem(mensagem)}`}>
          {mensagem}
        </div>
      )}

      {detalheAberto && (
        <div className="fixed inset-0 z-50 bg-black/70">
          <div className="flex min-h-full items-start justify-center overflow-y-auto p-4 sm:p-8">
            <div className="w-full max-w-6xl overflow-hidden rounded-2xl border border-neutral-700 bg-neutral-950 shadow-2xl">
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
                        <div className="text-sm font-semibold text-gray-100">
                          Motivos identificados{" "}
                          {detalheDados.detalhes_divergencia?.length ? `(${detalheDados.detalhes_divergencia.length})` : ""}
                        </div>
                        {detalheDados.detalhes_divergencia?.length ? (
                          <>
                            {detalheDados.detalhes_divergencia.length > 1 && (
                              <p className="text-xs text-amber-300">
                                Esta chamada possui mais de um apontamento.
                              </p>
                            )}
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
                          </>
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
                            <table className="min-w-full text-xs text-gray-300 whitespace-nowrap">
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

                      {partesGhOrigem.length > 1 && (
                        <div className="mt-6 space-y-3 rounded-xl border border-neutral-800 bg-neutral-900/30 p-4">
                          <div className="text-sm font-semibold text-gray-100">Registros originais no DETRAF</div>
                          <p className="text-xs text-gray-500">
                            A operadora criou {partesGhOrigem.length} linhas no arquivo DETRAF (normal x reduzido). Abaixo exibimos as linhas originais para auditoria com os mesmos campos do arquivo.
                          </p>
                          <div className="overflow-x-auto">
                            <table className="min-w-full text-xs text-gray-300 whitespace-nowrap">
                              <thead>
                                <tr className="text-left uppercase tracking-wide text-gray-400">
                                  <th className="px-2 py-1">Sequencial</th>
                                  <th className="px-2 py-1">Data</th>
                                  <th className="px-2 py-1">Hora</th>
                                  <th className="px-2 py-1">Assinante A</th>
                                  <th className="px-2 py-1">Assinante B</th>
                                  <th className="px-2 py-1">GH original</th>
                                  <th className="px-2 py-1">Duração real (min)</th>
                                  <th className="px-2 py-1">Duração calculada (min)</th>
                                  <th className="px-2 py-1">EQT (cred/deved)</th>
                                  <th className="px-2 py-1">POI</th>
                                </tr>
                              </thead>
                              <tbody>
                                {partesGhOrigem.map((parte, idx) => (
                                  <tr key={`${parte.id || parte.sequencial || idx}`} className="border-t border-neutral-800">
                                    <td className="px-2 py-1">{parte.sequencial || parte.id || `Parte ${idx + 1}`}</td>
                                    <td className="px-2 py-1">{parte.data_chamada || "--"}</td>
                                    <td className="px-2 py-1">{formatarHoraDetraf(parte.hora_atendimento)}</td>
                                    <td className="px-2 py-1">{parte.assinante_a || "--"}</td>
                                    <td className="px-2 py-1">{parte.assinante_b || "--"}</td>
                                    <td className="px-2 py-1">{parte.gh || "--"}</td>
                                    <td className="px-2 py-1">{formatarMinutos(parte.duracao_real_segundos)}</td>
                                    <td className="px-2 py-1">{formatarMinutos(parte.duracao_calculada_seg)}</td>
                                    <td className="px-2 py-1">
                                      {(parte.eqt_credora || parte.eqt_devedora) ? (
                                        <>
                                          {parte.eqt_credora || "--"} / {parte.eqt_devedora || "--"}
                                        </>
                                      ) : (
                                        "-- / --"
                                      )}
                                    </td>
                                    <td className="px-2 py-1">{parte.poi || "--"}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
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
const PIE_COLORS = ["#34d399", "#fbbf24", "#f87171", "#60a5fa", "#c084fc", "#f472b6"];
