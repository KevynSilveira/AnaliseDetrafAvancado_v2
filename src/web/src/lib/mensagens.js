const mapearTipo = (texto = "") => {
  const mensagem = texto.trim().toLowerCase();
  if (!mensagem) return "info";
  if (/(sucesso|conclu|finaliza|executad|gerad|iniciad)/.test(mensagem)) {
    return "success";
  }
  if (/(falha|erro|não foi possível|nao foi possivel|falhou)/.test(mensagem)) {
    return "error";
  }
  if (/(selecione|aguarde|processando|alerta)/.test(mensagem)) {
    return "warn";
  }
  return "info";
};

const CLASSES = {
  success: "border-emerald-500/40 bg-emerald-500/10 text-emerald-200",
  error: "border-red-500/40 bg-red-500/10 text-red-200",
  warn: "border-amber-400/40 bg-amber-500/10 text-amber-200",
  info: "border-primary/30 bg-neutral-900 text-gray-200",
};

export const obterClasseMensagem = (texto) => {
  const tipo = mapearTipo(texto);
  return CLASSES[tipo] || CLASSES.info;
};

export const obterTipoMensagem = (texto) => mapearTipo(texto);
