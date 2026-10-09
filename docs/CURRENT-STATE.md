# CURRENT-STATE — checkpoint de PAUSA do WP Smart Switch

## Decisão e escopo

- Registrado em **2026-10-09**, fuso America/Sao_Paulo.
- **Estado: PAUSADO.** Finalizar PepDay (referido como Happy Day no histórico) e WP Rotina antes de retomar o software da loja, que tem escopo maior.
- Repositório: [wpontieri-boop/wpimports-backend](https://github.com/wpontieri-boop/wpimports-backend).
- Este checkpoint preserva contexto para a retomada. Não representa validação de produção nem conclusão das pendências.
- Fonte do histórico: solicitação explícita do proprietário nesta tarefa, em continuidade à conversa “SOF WP Imports”. O contexto da conversa estabelece a pausa; os detalhes técnicos e números abaixo foram informados pelo proprietário.

## Estado real verificado no GitHub

Inspeção somente de arquivos e metadados do GitHub, sem executar o backend, consultar banco ou chamar endpoints de produção.

- Branch padrão: `main`.
- Commit-base inspecionado: [724a22bc63e9d00d218cf4da236a5302fa5668fd](https://github.com/wpontieri-boop/wpimports-backend/commit/724a22bc63e9d00d218cf4da236a5302fa5668fd), de 2026-08-28, mensagem `Update erp_units.py`.
- Árvore completa nesse commit: `.gitignore`, `README.md`, `app.py`, `erp_units.py` e `requirements.txt`.
- Não existiam `AGENTS.md`, `docs/CURRENT-STATE.md`, outros diretórios, workflows do GitHub Actions ou manifesto `render.yaml` nessa árvore. Nenhum PR aberto foi encontrado na inspeção inicial.
- Todos os cinco arquivos preexistentes foram preservados. A ausência de configuração de deploy no repositório não comprova ausência de deploy automático configurado externamente.

## Arquitetura e integração

| Componente | Evidência / nível de confirmação |
| --- | --- |
| Backend Python / Flask | Verificado em `app.py`, com blueprint de `erp_units.py`. |
| PostgreSQL | `app.py` utiliza `psycopg.connect(DATABASE_URL)`; schema inclui `products`, `product_units` e `marketplace_listings`. Banco em execução não consultado. |
| Render | Hospedagem informada pelo proprietário. Serviço, configurações, logs e commit implantado não foram consultados; status do deploy não confirmado. |
| Mercado Livre | Código contém OAuth, renovação de tokens, sincronização de itens e importação de anúncios para o ERP. Integração operacional não testada nesta tarefa. |
| Fotos / Gemini | `erp_units.py` contém formulário de entrada física, compressão de fotos e POST `/erp/units/gemini-read`, usando `google-genai`. |
| Unidade física / QR Code | Código contém POST `/erp/units/create`, código `WP-U-...`, token QR e consulta `/erp/units/qr/<qr_token>`; `qrcode[pil]` consta nas dependências. Impressão e fluxo completo não validados. |

Dependências atuais em `requirements.txt`: Flask, gunicorn, requests, python-dotenv, psycopg[binary], qrcode[pil] e google-genai. Nenhuma dependência foi alterada.

Configurações referenciadas no código incluem `DATABASE_URL`, `ML_CLIENT_ID`, `ML_CLIENT_SECRET`, `ML_REDIRECT_URI`, `ADMIN_USER`, `ADMIN_PASSWORD` e `GEMINI_API_KEY`. Somente os nomes são registrados; nenhum valor de segredo deve ser incluído aqui.

## Último checkpoint histórico de dados

**Informado pelo proprietário, sem recontagem nesta tarefa:**

| Indicador | Último checkpoint |
| --- | ---: |
| Anúncios Mercado Livre | 67 |
| Produtos centrais | 0 |
| Unidades físicas | 0 |

Esses números não são uma fotografia atual do banco. A data da medição original não foi confirmada. Não inferir que anúncios já estejam vinculados a produtos centrais ou unidades físicas.

## Pendência: timeout e temporary_error em erp_units.py

O histórico registra problema de timeout e da variável `temporary_error` no fluxo Gemini. **Permanece pendente de validação; status do deploy não confirmado.**

Diferença observada no código do commit-base:

- `types.HttpOptions(timeout=25000, retry_options=types.HttpRetryOptions(attempts=1))` está presente: timeout configurado em 25.000 ms por chamada, sem comprovar o tempo total da requisição.
- A lista de tentativas contém os identificadores `gemini-3.6-flash` e `gemini-3.7-flash`. Isso descreve o código; disponibilidade e compatibilidade desses modelos não foram verificadas.
- `temporary_error` está definido dentro de `except Exception as model_exc`, antes do teste `if not temporary_error`. Classifica mensagens com 503/UNAVAILABLE, 429/RESOURCE_EXHAUSTED e termos de timeout.
- O código tenta outro modelo em erros classificados como temporários; se nenhuma resposta for obtida, propaga o último erro.

A presença dessa lógica no GitHub não confirma que a mesma revisão esteja no Render, que o problema histórico tenha sido corrigido em execução ou que o cadastro por fotos esteja concluído. Nenhuma correção funcional foi realizada neste checkpoint.

## CenterPhone Suite: preservar intocado

**Estado informado pelo proprietário:** CenterPhone Suite Expedição PRO V1.3 funciona localmente no Windows.

Fluxo de abertura:
`ABRIR_CENTERPHONE_ETIQUETAS.bat` → `CenterPhone_Suite_Expedicao_PRO_V1_3.ps1`.

Esses arquivos não aparecem na árvore do backend inspecionada. Seu local, conteúdo e execução não foram inspecionados. Não fazem parte das alterações deste checkpoint e devem permanecer intocados. Não confundir a ferramenta de expedição com o backend WP Smart Switch.

## Retomada futura, somente após autorização

1. Confirmar com o proprietário a conclusão/prioridade de PepDay e WP Rotina e obter instrução explícita para retomar WP Smart Switch.
2. Ler este checkpoint e `AGENTS.md`; reinspecionar branch, commits, documentação e alterações posteriores.
3. Com autorização para a inspeção operacional, conferir no Render o commit implantado, status e logs, sem revelar segredos e sem disparar deploy.
4. Investigar o timeout e `temporary_error` a partir do erro real e do código implantado; verificar modelos Gemini, limites e tempo total. Preparar reprodução isolada, sem credenciais ou dados de produção.
5. Revalidar os números 67/0/0 apenas em acesso autorizado que não altere dados. Não usar `/erp/status` como leitura pura: essa função chama `init_erp_tables()`.
6. Planejar e validar o fluxo fotos → revisão dos dados → unidade física → QR Code em ambiente isolado. Manter CenterPhone intocado e os projetos separados.

## Limites desta entrega

Somente criação de `AGENTS.md` e deste documento em branch separada, com commit de documentação e PR para revisão. Sem alterações de código, dependências, banco, produção, infraestrutura ou deploy. Merge exige aprovação explícita do proprietário e avaliação do eventual deploy automático.
