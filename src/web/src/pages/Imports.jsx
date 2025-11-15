import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { obterClasseMensagem } from "../lib/mensagens";

const mensagensStatus = {
  PROCESSANDO: "Processando",
  CONCLUIDO: "Concluído",
  ERRO: "Erro",
  REMOVIDO: "Deletado",
};

const extrairProgresso = (mensagem) => {
  if (!mensagem) return null;
  const match = mensagem.match(/(\d{1,3})%/);
  if (!match) return null;
  const valor = Number(match[1]);
  if (Number.isNaN(valor)) return null;
  return Math.max(0, Math.min(100, valor));
};

const TABELAS_AUXILIARES = [
  { id: "eot", titulo: "Tabela EOT", descricao: "Referências utilizadas no cálculo de EOT." },
  { id: "numeros_portados", titulo: "Números Portados", descricao: "Base utilizada para auditorias de portabilidade." },
  { id: "cadup", titulo: "CADUP", descricao: "Dump CADUP empregado nos cruzamentos." },
];

const criarEstadoAuxiliares = () => {
  const estado = {};
  TABELAS_AUXILIARES.forEach((item) => {
    estado[item.id] = { processando: false, mensagem: "", erro: "", resumo: null };
  });
  return estado;
};

const criarChavesInputAuxiliares = () => {
  const chaves = {};
  TABELAS_AUXILIARES.forEach((item) => {
    chaves[item.id] = `${item.id}-${Date.now()}`;
  });
  return chaves;
};

export default function Imports() {
  const [clientes, setClientes] = useState([]);
  const [historico, setHistorico] = useState([]);
  const [idCliente, setIdCliente] = useState("");
  const [tipoArquivo, setTipoArquivo] = useState("CDR");
  const [arquivo, setArquivo] = useState(null);
  const [erroArquivo, setErroArquivo] = useState("");
  const [carregandoUpload, setCarregandoUpload] = useState(false);
  const [formClienteAberto, setFormClienteAberto] = useState(false);
  const [nomeNovoCliente, setNomeNovoCliente] = useState("");
  const [mensagemPainel, setMensagemPainel] = useState("");
  const [historicoAuxiliares, setHistoricoAuxiliares] = useState([]);
  const [arquivosAuxiliares, setArquivosAuxiliares] = useState({});
  const [statusAuxiliares, setStatusAuxiliares] = useState(() => criarEstadoAuxiliares());
  const [inputAuxiliares, setInputAuxiliares] = useState(() => criarChavesInputAuxiliares());
  const [abaAtiva, setAbaAtiva] = useState("importacao");

  const extensaoEsperada = useMemo(() => (tipoArquivo === "CDR" ? ".sql" : ".txt"), [tipoArquivo]);

  const carregarClientes = async (selecionarId = null) => {
    try {
      const lista = await api.get("/api/clientes");
      setClientes(lista || []);
      if (lista && lista.length) {
        if (selecionarId) {
          setIdCliente(String(selecionarId));
        } else if (!idCliente) {
          setIdCliente(String(lista[0].id_cliente));
        } else {
          const aindaExiste = lista.some((item) => String(item.id_cliente) === String(idCliente));
          if (!aindaExiste) {
            setIdCliente(String(lista[0].id_cliente));
          }
        }
      }
    } catch (err) {
      setMensagemPainel("Não foi possível carregar os clientes.");
    }
  };

  const carregarHistorico = useCallback(async () => {
    try {
      const dados = await api.get("/api/imports");
      setHistorico(dados || []);
    } catch (err) {
      setMensagemPainel("Não foi possível carregar o histórico de importações.");
    }
  }, []);

  const carregarHistoricoAuxiliares = useCallback(async () => {
    try {
      const dados = await api.get("/api/importacoes/auxiliares");
      setHistoricoAuxiliares(dados || []);
    } catch (err) {
      // ignora erro silenciosamente
    }
  }, []);

  useEffect(() => {
    carregarClientes();
  }, []);

  useEffect(() => {
    carregarHistorico();
    carregarHistoricoAuxiliares();
  }, [carregarHistorico, carregarHistoricoAuxiliares]);

  useEffect(() => {
    if (!arquivo) return;
    validarArquivo(arquivo);
  }, [tipoArquivo]);

  useEffect(() => {
    const temProcessando = historico.some((item) => item.status === "PROCESSANDO");
    if (!temProcessando) return;
    const idIntervalo = setInterval(() => {
      carregarHistorico();
    }, 5000);
    return () => clearInterval(idIntervalo);
  }, [historico, carregarHistorico]);

  useEffect(() => {
    setStatusAuxiliares((atual) => {
      const proximo = { ...atual };
      TABELAS_AUXILIARES.forEach((tabela) => {
        if (proximo[tabela.id]?.processando) return;
        const ultimo = historicoAuxiliares.find((registro) => registro.tabela_alvo === tabela.id);
        if (ultimo) {
          proximo[tabela.id] = {
            processando: ultimo.status === "PROCESSANDO",
            mensagem: ultimo.status === "CONCLUIDO" ? "Última importação concluída." : "",
            erro: ultimo.status === "ERRO" ? ultimo.mensagem || "Falha ao importar." : "",
            resumo: ultimo,
          };
        }
      });
      return proximo;
    });
  }, [historicoAuxiliares]);

  const validarArquivo = (arquivoSelecionado) => {
    if (!arquivoSelecionado) {
      setErroArquivo("Selecione um arquivo para continuar.");
      return false;
    }
    const nome = arquivoSelecionado.name.toLowerCase();
    if (!nome.endsWith(extensaoEsperada)) {
      setErroArquivo(`Para ${tipoArquivo} selecione um arquivo ${extensaoEsperada}.`);
      return false;
    }
    setErroArquivo("");
    return true;
  };

  const atualizarStatusAuxiliar = (id, dados) => {
    setStatusAuxiliares((atual) => {
      const base = atual[id] || { processando: false, mensagem: "", erro: "", resumo: null };
      return { ...atual, [id]: { ...base, ...dados } };
    });
  };

  const selecionarArquivoAuxiliar = (id, arquivoSelecionado) => {
    setArquivosAuxiliares((atual) => ({ ...atual, [id]: arquivoSelecionado || null }));
    atualizarStatusAuxiliar(id, { erro: "", mensagem: "" });
  };

  const renovarInputAuxiliar = (id) => {
    setInputAuxiliares((atual) => ({ ...atual, [id]: `${id}-${Date.now()}` }));
  };

  const importarTabelaAuxiliar = async (id) => {
    const arquivoSelecionado = arquivosAuxiliares[id];
    if (!arquivoSelecionado) {
      atualizarStatusAuxiliar(id, { erro: "Selecione um arquivo .sql para enviar." });
      return;
    }
    atualizarStatusAuxiliar(id, { processando: true, erro: "", mensagem: "" });
    try {
      const resposta = await api.upload(`/api/importacoes/auxiliares/${id}`, arquivoSelecionado, {}, { timeout: 0 });
      atualizarStatusAuxiliar(id, {
        processando: false,
        mensagem: resposta?.mensagem || "Importação concluída com sucesso.",
        resumo: resposta || null,
      });
      setArquivosAuxiliares((atual) => ({ ...atual, [id]: null }));
      renovarInputAuxiliar(id);
      carregarHistoricoAuxiliares();
    } catch (erro) {
      atualizarStatusAuxiliar(id, {
        processando: false,
        erro: erro.message || "Falha ao importar tabela.",
        resumo: null,
      });
    }
  };

  const tratarUpload = async () => {
    if (!idCliente) {
      setMensagemPainel("Selecione um cliente antes de importar.");
      return;
    }
    if (!validarArquivo(arquivo)) return;

    try {
      setCarregandoUpload(true);
      setMensagemPainel("");
      const resposta = await api.upload("/api/imports", arquivo, {
        id_cliente: idCliente,
        tipo_arquivo: tipoArquivo,
      });
      setMensagemPainel(resposta?.mensagem || "Importação iniciada.");
      setArquivo(null);
      carregarHistorico();
    } catch (err) {
      setMensagemPainel(err.message || "Falha ao enviar o arquivo.");
    } finally {
      setCarregandoUpload(false);
    }
  };

  const cadastrarCliente = async () => {
    const nome = nomeNovoCliente.trim();
    if (!nome) {
      setMensagemPainel("Informe um nome para o cliente.");
      return;
    }
    try {
      const resposta = await api.post("/api/clientes", { nome_cliente: nome });
      setMensagemPainel(resposta?.mensagem || "Cliente cadastrado com sucesso.");
      setNomeNovoCliente("");
      setFormClienteAberto(false);
      const idCriado = resposta?.id_cliente;
      await carregarClientes(idCriado);
    } catch (err) {
      setMensagemPainel(err.message || "Falha ao cadastrar cliente.");
    }
  };

  const formatarData = (valor) => {
    if (!valor) return "-";
    try {
      return new Date(valor).toLocaleString("pt-BR");
    } catch (err) {
      return valor;
    }
  };

  const tabs = [
    { id: "importacao", label: "Importação DETRAF/CDR" },
    { id: "historico", label: "Histórico geral" },
    { id: "auxiliares", label: "Tabelas auxiliares" },
  ];

  const historicoCliente = useMemo(() => {
    if (!idCliente) return historico;
    return historico.filter((item) => String(item.id_cliente) === String(idCliente));
  }, [historico, idCliente]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap gap-3">
        {/* Abas de navegação: definem qual bloco é exibido abaixo */}
        {tabs.map((tab) => (
          <button
            key={tab.id}
            className={`rounded-full px-4 py-1 text-sm font-semibold transition ${
              abaAtiva === tab.id ? "bg-primary text-white" : "bg-neutral-800 text-gray-300 hover:bg-neutral-700"
            }`}
            onClick={() => setAbaAtiva(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {abaAtiva === "importacao" && (
        <div className="space-y-6">
          {/* Formulário principal de upload DETRAF/CDR */}
          <div className="card p-6 space-y-6">
            <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
              <div>
                <div className="text-lg font-semibold text-primary">Importação DETRAF / CDR</div>
                <p className="text-sm text-gray-400">Informe o cliente, o tipo do arquivo e envie o dump adequado.</p>
              </div>
              <button
                className="text-sm text-primary hover:text-primary/80"
                onClick={() => setFormClienteAberto((estado) => !estado)}
              >
                {formClienteAberto ? "Fechar cadastro de cliente" : "Cadastrar novo cliente"}
              </button>
            </div>

            {formClienteAberto && (
              <div className="rounded-lg border border-neutral-700 bg-neutral-900 p-4 space-y-3">
                <h3 className="text-sm font-medium text-gray-200">Novo cliente</h3>
                <div className="flex flex-col gap-3 md:flex-row">
                  <input
                    type="text"
                    value={nomeNovoCliente}
                    onChange={(e) => setNomeNovoCliente(e.target.value)}
                    placeholder="Nome do cliente"
                    className="w-full rounded-lg border border-neutral-700 bg-dark p-2 text-gray-200 focus:outline-none focus:ring-2 focus:ring-primary/40"
                  />
                  <button className="btn md:w-48" onClick={cadastrarCliente}>
                    Salvar cliente
                  </button>
                </div>
              </div>
            )}

            <div className="grid gap-4 md:grid-cols-3">
              <div className="md:col-span-1">
                <label className="mb-2 block text-sm font-medium text-gray-300">Cliente</label>
                <select
                  value={idCliente}
                  onChange={(e) => setIdCliente(e.target.value)}
                  className="w-full rounded-lg border border-neutral-700 bg-dark p-2 text-gray-200 focus:outline-none focus:ring-2 focus:ring-primary/40"
                >
                  <option value="">Selecione um cliente</option>
                  {clientes.map((cliente) => (
                    <option key={cliente.id_cliente} value={cliente.id_cliente}>
                      {cliente.nome_cliente}
                    </option>
                  ))}
                </select>
              </div>

              <div className="md:col-span-1">
                <label className="mb-2 block text-sm font-medium text-gray-300">Tipo de importação</label>
                <div className="flex gap-3">
                  {["CDR", "DETRAF"].map((tipo) => (
                    <label
                      key={tipo}
                      className={`flex-1 cursor-pointer rounded-lg border p-3 text-center text-sm font-semibold transition ${
                        tipoArquivo === tipo
                          ? "border-primary bg-primary/20 text-white"
                          : "border-neutral-700 bg-dark text-gray-300 hover:border-primary/60"
                      }`}
                    >
                      <input
                        type="radio"
                        name="tipo_arquivo"
                        className="sr-only"
                        value={tipo}
                        checked={tipoArquivo === tipo}
                        onChange={() => setTipoArquivo(tipo)}
                      />
                      {tipo}
                    </label>
                  ))}
                </div>
                <p className="mt-2 text-xs text-gray-400">
                  {tipoArquivo === "CDR"
                    ? "Aceita apenas arquivos .sql com o dump completo da base CDR."
                    : "Aceita apenas arquivos .txt no layout oficial DETRAF."}
                </p>
              </div>

              <div className="md:col-span-1">
                <label className="mb-2 block text-sm font-medium text-gray-300">Arquivo</label>
                <input
                  type="file"
                  accept={extensaoEsperada}
                  onChange={(e) => {
                    const arquivoSelecionado = e.target.files?.[0] || null;
                    setArquivo(arquivoSelecionado);
                    if (arquivoSelecionado) validarArquivo(arquivoSelecionado);
                  }}
                  className="w-full cursor-pointer rounded-lg border border-dashed border-neutral-600 bg-dark p-2 text-sm text-gray-300 focus:outline-none focus:ring-2 focus:ring-primary/40"
                />
                {erroArquivo && <p className="mt-2 text-xs text-red-400">{erroArquivo}</p>}
                <p className="mt-2 text-xs text-gray-500">Carregue o arquivo {extensaoEsperada} preparado para este cliente.</p>
              </div>
            </div>

            <div className="flex justify-end">
              <button className="btn px-6" onClick={tratarUpload} disabled={carregandoUpload}>
                {carregandoUpload ? "Enviando..." : "Importar arquivo"}
              </button>
            </div>

            {mensagemPainel && (
              <div className={`rounded-lg border p-3 text-sm ${obterClasseMensagem(mensagemPainel)}`}>
                {mensagemPainel}
              </div>
            )}
          </div>

          <div className="card p-6">
            <div className="mb-3 flex items-center justify-between">
              {/* Histórico limitado ao cliente selecionado */}
              <div>
                <div className="text-lg font-semibold text-primary">Histórico do cliente selecionado</div>
                <p className="text-xs text-gray-400">Mostra apenas importações do cliente escolhido acima.</p>
              </div>
              <button className="text-sm text-gray-300 hover:text-primary" onClick={carregarHistorico}>
                Recarregar
              </button>
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead className="bg-neutral-800 text-gray-200">
                  <tr>
                    <th className="p-2 text-left">Tipo</th>
                    <th className="p-2 text-left">Arquivo</th>
                    <th className="p-2 text-left">Período</th>
                    <th className="p-2 text-left">Registros</th>
                    <th className="p-2 text-left">Status</th>
                    <th className="p-2 text-left">Data</th>
                  </tr>
                </thead>
                <tbody>
                  {!historicoCliente.length && (
                    <tr>
                      <td colSpan="6" className="p-4 text-center text-gray-400">
                        Nenhuma importação registrada para o cliente selecionado.
                      </td>
                    </tr>
                  )}
                  {historicoCliente.map((item) => (
                    <tr key={item.id} className="border-t border-neutral-800">
                      <td className="p-2 text-gray-200">{item.tipo_arquivo}</td>
                      <td className="p-2 text-gray-300">{item.nome_arquivo}</td>
                      <td className="p-2 text-gray-300">
                        {item.periodo_inicial || item.periodo_final
                          ? `${item.periodo_inicial || "-"} até ${item.periodo_final || "-"}`
                          : "-"}
                      </td>
                      <td className="p-2 text-gray-300">{item.linhas_processadas || 0}</td>
                      <td className="p-2 text-gray-200">{mensagensStatus[item.status] || item.status}</td>
                      <td className="p-2 text-gray-300">{formatarData(item.data_importacao)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {abaAtiva === "historico" && (
        <div className="card p-6">
          <div className="mb-3 flex items-center justify-between">
            {/* Histórico completo (não filtrado) */}
            <div>
              <div className="text-lg font-semibold text-primary">Histórico geral de importações</div>
              <p className="text-xs text-gray-400">Todas as importações recentes, independente do cliente.</p>
            </div>
            <button className="text-sm text-gray-300 hover:text-primary" onClick={carregarHistorico}>
              Recarregar
            </button>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="bg-neutral-800 text-gray-200">
                <tr>
                  <th className="p-2 text-left">Cliente</th>
                  <th className="p-2 text-left">Tipo</th>
                  <th className="p-2 text-left">Arquivo</th>
                  <th className="p-2 text-left">Período</th>
                  <th className="p-2 text-left">Progresso</th>
                  <th className="p-2 text-left">EOT credora</th>
                  <th className="p-2 text-left">EOT devedora</th>
                  <th className="p-2 text-left">Registros</th>
                  <th className="p-2 text-left">Data importação</th>
                  <th className="p-2 text-left">Status</th>
                  <th className="p-2 text-left">Detalhes</th>
                </tr>
              </thead>
              <tbody>
                {!historico.length && (
                  <tr>
                    <td colSpan="11" className="p-4 text-center text-gray-400">
                      Nenhuma importação registrada até o momento.
                    </td>
                  </tr>
                )}
                {historico.map((item) => (
                  <tr key={item.id} className="border-t border-neutral-800">
                    <td className="p-2 text-gray-200">{item.nome_cliente || "-"}</td>
                    <td className="p-2 text-gray-200">{item.tipo_arquivo}</td>
                    <td className="p-2 text-gray-300">{item.nome_arquivo}</td>
                    <td className="p-2 text-gray-300">
                      {item.periodo_inicial || item.periodo_final
                        ? `${item.periodo_inicial || "-"} até ${item.periodo_final || "-"}`
                        : "-"}
                    </td>
                    <td className="p-2 text-gray-300">
                      {item.status === "PROCESSANDO" && extrairProgresso(item.mensagem) !== null ? (
                        <div className="w-full max-w-[140px]">
                          <div className="h-2 w-full rounded-full bg-neutral-800">
                            <div
                              className="h-2 rounded-full bg-primary transition-all"
                              style={{ width: `${extrairProgresso(item.mensagem)}%` }}
                            ></div>
                          </div>
                          <span className="mt-1 block text-xs text-gray-400">{extrairProgresso(item.mensagem)}%</span>
                        </div>
                      ) : (
                        "-"
                      )}
                    </td>
                    <td className="p-2 text-gray-300">{item.eqt_credora || "-"}</td>
                    <td className="p-2 text-gray-300">{item.eqt_devedora || "-"}</td>
                    <td className="p-2 text-gray-300">{item.linhas_processadas || 0}</td>
                    <td className="p-2 text-gray-300">{formatarData(item.data_importacao)}</td>
                    <td className={`p-2 font-semibold ${item.status === "REMOVIDO" ? "text-red-400" : "text-gray-200"}`}>
                      {mensagensStatus[item.status] || item.status}
                    </td>
                    <td className="p-2 text-gray-400">{item.mensagem || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {abaAtiva === "auxiliares" && (
        <div className="space-y-6">
          {/* Cards de upload por tabela auxiliar */}
          <div className="card p-6 space-y-5">
            <header>
              <h2 className="text-lg font-semibold text-primary">Importação de tabelas auxiliares</h2>
              <p className="text-xs text-gray-400 mt-1">
                Envie os dumps (.sql) das tabelas auxiliares; o conteúdo existente será substituído.
              </p>
            </header>
            <div className="grid gap-4 md:grid-cols-3">
              {TABELAS_AUXILIARES.map((item) => {
                const status = statusAuxiliares[item.id] || {};
                const arquivoAux = arquivosAuxiliares[item.id];
                return (
                  <div key={item.id} className="rounded-lg border border-neutral-700 bg-neutral-900 p-4 space-y-3">
                    <div>
                      <h3 className="font-semibold text-gray-100">{item.titulo}</h3>
                      <p className="text-xs text-gray-400 mt-1">{item.descricao}</p>
                    </div>
                    <input
                      key={inputAuxiliares[item.id]}
                      type="file"
                      accept=".sql"
                      className="w-full text-xs text-gray-300"
                      onChange={(evento) => selecionarArquivoAuxiliar(item.id, evento.target.files?.[0] || null)}
                    />
                    {arquivoAux && (
                      <div className="text-[10px] text-gray-500 break-all">
                        Arquivo selecionado: {arquivoAux.name}
                      </div>
                    )}
                    <button
                      type="button"
                      className="btn w-full text-center"
                      disabled={status.processando}
                      onClick={() => importarTabelaAuxiliar(item.id)}
                    >
                      {status.processando ? "Importando..." : `Importar ${item.titulo}`}
                    </button>
                    {status.mensagem && <div className="text-[11px] text-green-400">{status.mensagem}</div>}
                    {status.erro && <div className="text-[11px] text-red-400">{status.erro}</div>}
                    {typeof status?.resumo?.total_registros === "number" && (
                      <div className="text-[11px] text-gray-400">
                        Registros carregados: {status.resumo.total_registros.toLocaleString("pt-BR")}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          <div className="card p-6">
            <div className="mb-3 flex items-center justify-between">
              {/* Histórico das tabelas auxiliares */}
              <div>
                <div className="text-lg font-semibold text-primary">Histórico de tabelas auxiliares</div>
                <p className="text-xs text-gray-400">Registros recentes das importações de EOT, Números Portados e CADUP.</p>
              </div>
              <button className="text-sm text-gray-300 hover:text-primary" onClick={carregarHistoricoAuxiliares}>
                Recarregar
              </button>
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead className="bg-neutral-800 text-gray-200">
                  <tr>
                    <th className="p-2 text-left">Tabela</th>
                    <th className="p-2 text-left">Arquivo</th>
                    <th className="p-2 text-left">Registros</th>
                    <th className="p-2 text-left">Tamanho</th>
                    <th className="p-2 text-left">Status</th>
                    <th className="p-2 text-left">Mensagem</th>
                    <th className="p-2 text-left">Data</th>
                  </tr>
                </thead>
                <tbody>
                  {!historicoAuxiliares.length && (
                    <tr>
                      <td colSpan="7" className="p-4 text-center text-gray-400">
                        Nenhuma importação auxiliar registrada até o momento.
                      </td>
                    </tr>
                  )}
                  {historicoAuxiliares.map((item) => (
                    <tr key={item.id} className="border-t border-neutral-800">
                      <td className="p-2 text-gray-200">{item.tabela_alvo?.toUpperCase()}</td>
                      <td className="p-2 text-gray-300">{item.nome_arquivo}</td>
                      <td className="p-2 text-gray-300">{item.total_registros ?? "-"}</td>
                      <td className="p-2 text-gray-300">
                        {typeof item.tamanho_bytes === "number" ? `${(item.tamanho_bytes / 1024).toFixed(2)} KB` : "-"}
                      </td>
                      <td className="p-2 text-gray-200">{mensagensStatus[item.status] || item.status}</td>
                      <td className="p-2 text-gray-400">{item.mensagem || "-"}</td>
                      <td className="p-2 text-gray-300">
                        {item.criado_em ? new Date(item.criado_em).toLocaleString("pt-BR") : "-"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
