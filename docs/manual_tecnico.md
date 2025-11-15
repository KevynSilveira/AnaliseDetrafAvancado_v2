# Manual Operacional - Detraf Conferência V2

Este manual descreve o uso das principais telas, endpoints e rotinas de manutenção do sistema. Utilize-o como guia de operação e suporte.

---

## 1. Pré-requisitos
- Banco MySQL configurado e acessível (credenciais no `configs/.env`).
- Python 3.10+ com dependências instaladas (`pip install -r src/api/requirements.txt`).
- Node + npm para o frontend (`npm install` em `src/web`).
- Diretório `var/` com permissão de escrita (logs, temporários, dumps).

## 2. Inicialização do ambiente
1. **API + Frontend**: `python src/main.py`
   - Logs de bootstrap ficam em `var/logs/api_conferencia.log` e `var/logs/pip_requirements.log`.
2. **Modo desenvolvimento** (opcional):
   - API: `uvicorn src.api.server:app --reload`
   - Web: `cd src/web && npm run dev -- --host`

## 3. Tela “Importações”

### 3.1 Abas
- **Importação DETRAF/CDR**: formulário de upload por cliente e histórico filtrado.
- **Histórico geral**: tabela com todas as importações recentes, independente de cliente.
- **Tabelas auxiliares**: upload dos dumps de EOT, números portados e CADUP + histórico próprio.

### 3.2 Passo a passo (DETRAF/CDR)
1. Selecionar cliente (ou cadastrar um novo no botão “Cadastrar cliente”).
2. Definir tipo (`CDR` ou `DETRAF`).
3. Escolher arquivo (`.sql` para CDR, `.txt` para DETRAF). O sistema valida a extensão.
4. Clicar em “Importar arquivo”. O histórico do cliente mostra o status (PROCESSANDO/CONCLUÍDO/ERRO).
5. Se necessário, acompanhar logs em `var/logs/api_conferencia.log` (eventos `detraf_importacao_*` ou `cdr_importacao_*`).

### 3.3 Tabelas auxiliares
1. Na aba “Tabelas auxiliares”, escolher o arquivo `.sql` correspondente à tabela (EOT, números portados ou CADUP).
2. Clicar em “Importar …”. A tabela atual no banco é dropada e substituída.
3. O histórico registra tamanho, total de registros e mensagens. Eventos aparecem como `auxiliar_importacao_*` no log.

## 4. Tela “Validação”
- Aplica filtros por status, siga-me, GH, tarifas, divergências etc.
- Cada linha traz detalhes (assinantes A/B, snapshots, divergências encontradas) e, quando houver siga-me, mostra destino normalizado.
- Exportações e ações adicionais ficam no cabeçalho da tabela.

## 5. Tela “Relatórios”
- Disponibiliza gráficos, KPIs e downloads agregados conforme importações concluídas.

## 6. Tela “Configurações” (Limpeza e manutenção)
1. Painéis superiores mostram contadores (logs, temporários, registros DETRAF/CDR).
2. Seção de seleção: escolher clientes/importações e alvos (LOGS, TMP, DETRAF, CDR).
3. Informar parâmetros (ex.: dias de logs, quantidade mínima a manter).
4. Clicar em “Executar limpeza”. Resultados e mensagens aparecem logo abaixo.
5. Logs relacionados: eventos `limpeza_*` no `api_conferencia.log`.

## 7. Logs e troubleshooting
- **`api_conferencia.log`**: checar sempre que houver falha. Principais eventos: `launcher_*`, `detraf_importacao_*`, `cdr_importacao_*`, `normalizacao_detraf_*`, `normalizacao_cdr_*`, `auxiliar_importacao_*`, `sql_*`.
- **`sigame_normalizacao.log`**: auditoria das decisões de siga-me durante normalização.
- **`pip_requirements.log`**: histórico da instalação automática de dependências quando o `src/main.py` detecta mudanças em `requirements.txt`.
- **SQL com placeholders**: erros como “Not all parameters were used” indicam `%s` extras dentro do conteúdo; revisar o registro citado no log antes de repetir a importação.

## 8. Estrutura de banco
Principais tabelas criadas automaticamente:
- `clientes`, `controle_importacoes`, `detraf_operadora_batimento`, `detraf_normalizado`, `cdr_normalizado`, `conferencia_resultados`.
- `importacoes_auxiliares`: guarda histórico dos dumps de EOT, números portados e CADUP.

## 9. Boas práticas
- Validar layouts antes de importar para evitar processos longos com erro.
- Monitorar as abas de histórico após cada upload; em caso de erro, verificar `api_conferencia.log` e repetir o envio.
- Executar a limpeza periódica (Configurações) para evitar crescimento excessivo das tabelas e logs.
- Manter um backup dos dumps auxiliares – ao importar um novo arquivo, o conteúdo anterior é perdido.

## 10. Contato e atualização
- Dúvidas operacionais: conferir este manual e os logs.
- Ajustes/correções: abrir issue no repositório ou contatar o time responsável.
- Sempre que novas features forem adicionadas, atualizar este manual e o README.
