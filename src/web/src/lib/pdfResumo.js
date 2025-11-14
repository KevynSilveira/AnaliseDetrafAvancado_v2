const PDF_THEME = {
  background: { r: 255, g: 255, b: 255 },
  card: { r: 245, g: 246, b: 251 },
  border: { r: 225, g: 228, b: 236 },
  text: { r: 14, g: 23, b: 42 },
  muted: { r: 107, g: 114, b: 128 },
  accent: { r: 239, g: 68, b: 68 },
};

const carregarJsPdf = async () => {
  if (typeof window === "undefined") return null;
  if (window.jspdf?.jsPDF) return window.jspdf.jsPDF;
  await new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "https://cdn.jsdelivr.net/npm/jspdf@2.5.1/dist/jspdf.umd.min.js";
    script.onload = resolve;
    script.onerror = () => reject(new Error("Não foi possível carregar o gerador de PDF."));
    document.body.appendChild(script);
  });
  return window.jspdf?.jsPDF || null;
};

const BASE_ASSET_PATH =
  typeof import.meta !== "undefined" && import.meta.env?.BASE_URL ? import.meta.env.BASE_URL : "/";
let logoFooterPromise = null;
const carregarLogoFooter = async () => {
  if (typeof window === "undefined") return null;
  if (logoFooterPromise) return logoFooterPromise;
  logoFooterPromise = (async () => {
    try {
      const base = BASE_ASSET_PATH.endsWith("/") ? BASE_ASSET_PATH.slice(0, -1) : BASE_ASSET_PATH;
      const url = `${base}/saperx-footer.png`;
      const resposta = await fetch(url);
      if (!resposta.ok) {
        return null;
      }
      const blob = await resposta.blob();
      return await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(new Error("Falha ao ler logo do rodapé."));
        reader.readAsDataURL(blob);
      });
    } catch (erro) {
      console.warn("Não foi possível carregar o logo do rodapé:", erro);
      return null;
    }
  })();
  return logoFooterPromise;
};

const drawSectionTitle = (doc, title, subtitle, margin, ensureSpace, options = {}) => {
  const { spacingTop = 18, minFollowing = 36, afterTitleGap = 8 } = options;
  const headerHeight = spacingTop + 16 + (subtitle ? 14 : 0) + 12 + afterTitleGap;
  ensureSpace(headerHeight + minFollowing);
  ensureSpace.cursor += spacingTop;
  doc.setFont("helvetica", "bold");
  doc.setFontSize(15);
  doc.setTextColor(PDF_THEME.text.r, PDF_THEME.text.g, PDF_THEME.text.b);
  doc.text(title, margin, ensureSpace.cursor);
  ensureSpace.cursor += 16;
  if (subtitle) {
    doc.setFont("helvetica", "normal");
    doc.setFontSize(10);
    doc.setTextColor(PDF_THEME.muted.r, PDF_THEME.muted.g, PDF_THEME.muted.b);
    doc.text(subtitle, margin, ensureSpace.cursor);
    ensureSpace.cursor += 14;
  }
  doc.setDrawColor(PDF_THEME.border.r, PDF_THEME.border.g, PDF_THEME.border.b);
  doc.setLineWidth(0.8);
  doc.line(margin, ensureSpace.cursor, doc.internal.pageSize.getWidth() - margin, ensureSpace.cursor);
  ensureSpace.cursor += 12 + afterTitleGap;
};

const drawMetricLines = (doc, itens, margin, pageWidth, ensureSpace) => {
  if (!itens?.length) return;
  const valorX = pageWidth - margin;
  ensureSpace.cursor += 6;
  itens.forEach((item) => {
    ensureSpace(20);
    doc.setFont("helvetica", "bold");
    doc.setFontSize(11);
    doc.setTextColor(PDF_THEME.text.r, PDF_THEME.text.g, PDF_THEME.text.b);
    doc.text((item.label || "").toUpperCase(), margin, ensureSpace.cursor);
    doc.setFont("helvetica", "normal");
    doc.setFontSize(10);
    doc.setTextColor(PDF_THEME.text.r, PDF_THEME.text.g, PDF_THEME.text.b);
    doc.text(String(item.value ?? "--"), valorX, ensureSpace.cursor, { align: "right" });
    ensureSpace.cursor += 14;
    if (item.subtitle) {
      doc.setFont("helvetica", "normal");
      doc.setFontSize(9);
      doc.setTextColor(PDF_THEME.muted.r, PDF_THEME.muted.g, PDF_THEME.muted.b);
      doc.text(item.subtitle, margin + 16, ensureSpace.cursor);
      ensureSpace.cursor += 12;
    }
    ensureSpace.cursor += 6;
  });
  ensureSpace.cursor += 10;
};

export const exportarResumoPdf = async (dados) => {
  const jsPDFLib = await carregarJsPdf();
  if (!jsPDFLib) throw new Error("jsPDF indisponível");
  const doc = new jsPDFLib({ unit: "pt", format: "a4" });
  const pageWidth = doc.internal.pageSize.getWidth();
  const pageHeight = doc.internal.pageSize.getHeight();
  const margin = 48;
  let cursorY = 48;
  const ensureSpace = (extra = 0) => {
    ensureSpace.cursor ??= cursorY;
    if (ensureSpace.cursor + extra > pageHeight - 80) {
      doc.addPage();
      ensureSpace.cursor = 64;
    }
  };
  ensureSpace.cursor = cursorY;

  const { importacao, geradoEm, arquivoVisao, resumoMinutos, statusCards, tarifas, divergencias, distribuicaoGh } = dados;
  const logoFooter = await carregarLogoFooter();
  const formatDate = (value) => {
    const target = value instanceof Date ? value : new Date(value || Date.now());
    try {
      return new Intl.DateTimeFormat("pt-BR", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      }).format(target);
    } catch {
      return target.toLocaleString("pt-BR");
    }
  };

  doc.setFillColor(PDF_THEME.background.r, PDF_THEME.background.g, PDF_THEME.background.b);
  doc.rect(0, 0, pageWidth, pageHeight, "F");

  doc.setFont("helvetica", "bold");
  doc.setFontSize(20);
  doc.setTextColor(PDF_THEME.text.r, PDF_THEME.text.g, PDF_THEME.text.b);
  doc.text("Resumo da conferência DETRAF", margin, ensureSpace.cursor);
  doc.setFont("helvetica", "normal");
  doc.setFontSize(10);
  doc.setTextColor(PDF_THEME.muted.r, PDF_THEME.muted.g, PDF_THEME.muted.b);
  const dataTexto = formatDate(geradoEm);
  doc.text(`Gerado em ${dataTexto}`, margin, ensureSpace.cursor + 16);
  ensureSpace.cursor += 40;

  const contextoMetricas = [
    { label: "Cliente", value: importacao?.cliente || "--" },
    { label: "Arquivo", value: importacao?.arquivo || "--" },
    { label: "Período", value: importacao?.janela || "--" },
    {
      label: "EQTs (cred/deved)",
      value: `${importacao?.eqt_credora || "--"} / ${importacao?.eqt_devedora || "--"}`,
    },
  ];

  drawSectionTitle(doc, "Contexto da importação", null, margin, ensureSpace, { spacingTop: 18, minFollowing: 40 });
  drawMetricLines(doc, contextoMetricas, margin, pageWidth, ensureSpace);

  if (arquivoVisao?.length) {
    drawSectionTitle(doc, "Visão do arquivo recebido", null, margin, ensureSpace, { minFollowing: 40 });
    drawMetricLines(doc, arquivoVisao, margin, pageWidth, ensureSpace);
  }

  drawSectionTitle(doc, "Resumo dos valores cobrados", null, margin, ensureSpace, { minFollowing: 40 });
  drawMetricLines(doc, resumoMinutos, margin, pageWidth, ensureSpace);

  drawSectionTitle(doc, "Status da conferência", null, margin, ensureSpace, { minFollowing: 40 });
  drawMetricLines(doc, statusCards, margin, pageWidth, ensureSpace);

  drawSectionTitle(doc, "Tarifas aplicadas", null, margin, ensureSpace, { minFollowing: 40 });
  drawMetricLines(doc, tarifas, margin, pageWidth, ensureSpace);

  drawSectionTitle(doc, "Divergências identificadas", null, margin, ensureSpace, { minFollowing: 40 });
  drawMetricLines(doc, divergencias, margin, pageWidth, ensureSpace);

  drawSectionTitle(doc, "Distribuição de minutos", null, margin, ensureSpace, { minFollowing: 40 });
  drawMetricLines(doc, distribuicaoGh, margin, pageWidth, ensureSpace);

  // Footer with logo
  doc.setFillColor(0, 0, 0);
  doc.rect(0, pageHeight - 60, pageWidth, 60, "F");
  const logoOffset = 30;
  if (logoFooter) {
    const logoWidth = 120;
    const logoHeight = 32;
    doc.addImage(logoFooter, "PNG", logoOffset, pageHeight - 50, logoWidth, logoHeight, undefined, "FAST");
  } else {
    doc.setFont("helvetica", "bold");
    doc.setFontSize(20);
    doc.setTextColor(255, 255, 255);
    doc.text("saper", logoOffset, pageHeight - 24);
    doc.setTextColor(PDF_THEME.accent.r, PDF_THEME.accent.g, PDF_THEME.accent.b);
    doc.text("X", logoOffset + 72, pageHeight - 24);
  }

  doc.save(`${importacao?.arquivo?.replace(/\.[^.]+$/, "") || "resumo-conferencia"}.pdf`);
};
