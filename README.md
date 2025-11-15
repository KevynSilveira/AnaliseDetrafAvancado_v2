# Detraf Conferência V2

Plataforma completa para importar, normalizar e conferir arquivos DETRAF contra CDRs. O projeto combina uma API em FastAPI com um painel React/Vite, oferecendo acompanhamento de logs, dashboards, ferramentas de limpeza e gestão de tabelas auxiliares (EOT, números portados e CADUP).

---

## Objetivos
- Automatizar a conferência DETRAF x CDR com registro completo de execuções.
- Centralizar importações (DETRAF/CDR e tabelas auxiliares) com histórico e logs.
- Fornecer painel web para análise (Validação, Relatórios) e manutenção (Limpeza, Importações).
- Garantir observabilidade via arquivos em `var/logs/` e snapshots salvos no banco.

---

## Componentes implementados

| Camada | Destaques |
|--------|-----------|
| **API (`src/api/server.py`)** | Endpoints de importação, histórico, limpeza e dashboards. Gera registros em `controle_importacoes` e `importacoes_auxiliares`, dispara normalizações e mantém logs estruturados. |
| **Normalização (`src/core/normaliza_dados.py`)** | Pipelines DETRAF/CDR com tratamento de siga-me, GH, tarifação e snapshots JSON exibidos na web. |
| **Importadores (`src/core/importadores/`)** | Leitura de DETRAF e dumps CDR, validações de layout e logs em cada etapa. |
| **Logs (`src/core/configuracao_logs.py`)** | Único logger rotativo (`var/logs/api_conferencia.log`) usado em todo o projeto. Eventos específicos para bootstrap, importações, normalizações e tabelas auxiliares. |
| **Frontend (`src/web`)** | Páginas React: • Importações (com abas: Upload, Histórico geral, Tabelas auxiliares) • Validação • Relatórios • Configurações (Limpeza/Manutenção). |
| **Scripts utilitários** | `src/main.py` inicia API + Web, registrando início/fim da instalação de requirements e comandos executados. |

### Recursos das telas
- **Importações**: formulário DETRAF/CDR por cliente, cadastro rápido de cliente, histórico filtrado, abas para histórico geral e controles das tabelas auxiliares.
- **Validação**: filtros avançados (status, siga-me, GH, tarifas, EOT divergente) e detalhes da conferência.
- **Relatórios**: exportações e indicadores consolidados.
- **Configurações**: painéis de logs/TMP/DETRAF/CDR, limpeza guiada e opções para remover registros históricos.

### Logs gerados
- `var/logs/api_conferencia.log`: eventos `launcher_*`, `detraf_importacao_*`, `cdr_importacao_*`, `normalizacao_*`, `auxiliar_importacao_*`, `sql_*` etc.
- `var/logs/sigame_normalizacao.log`: acompanhamento detalhado de siga-me.
- `var/logs/pip_requirements.log`: saída das instalações de dependências.

---

## Instalação e execução

1. **Dependências**
   ```bash
   pip install -r src/api/requirements.txt
   cd src/web && npm install
   ```
2. **Configuração**
   - Copie/ajuste `configs/.env` com credenciais do MySQL (`DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASS`).
   - Defina `VAR_DIR` se quiser alterar o diretório padrão de logs/temporários.
3. **Inicialização**
   ```bash
   python src/main.py
   ```
   - API: `http://<ip>:8000`
   - Frontend: `http://<ip>:5173`

As tabelas são criadas automaticamente em `ensure_tables()` (clientes, importações, normalizados, conferência e a nova `importacoes_auxiliares`).

---

## Fluxo de uso (resumo)

1. **Importar DETRAF/CDR** na aba “Importação DETRAF/CDR”. O histórico abaixo mostra apenas o cliente ativo.
2. **Acompanhar histórico global** na aba “Histórico geral” (todos os clientes e status em uma única tabela).
3. **Importar tabelas auxiliares** na aba “Tabelas auxiliares”; cada upload `.sql` substitui completamente a tabela alvo e gera registro próprio.
4. **Validar resultados** na página Validação, aplicando filtros avançados e conferindo snapshots (inclusive siga-me).
5. **Manter o ambiente** via Configurações → Limpeza (logs, TMP, registros DETRAF/CDR) e monitorar `var/logs/` para incidentes.

Para instruções detalhadas (passo a passo de importação, limpeza, troubleshooting), consulte o [Manual Operacional](docs/manual_tecnico.md).

---

## Desenvolvimento

- API em hot reload:
  ```bash
  uvicorn src.api.server:app --reload
  ```
- Frontend:
  ```bash
  cd src/web && npm run dev -- --host
  ```
- Logs: verificar `var/logs/api_conferencia.log` e `sigame_normalizacao.log` sempre que ocorrer falha.

Contribuições e dúvidas podem ser registradas diretamente no repositório. Manter o manual atualizado garante que operação e suporte tenham o passo a passo alinhado.
