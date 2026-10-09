# AGENTS.md — WP Smart Switch / WP Imports

## Escopo e checkpoint obrigatório

Este repositório é `wpontieri-boop/wpimports-backend`, backend do software da loja WP Imports / WP Smart Switch. Antes de trabalhar, ler [docs/CURRENT-STATE.md](docs/CURRENT-STATE.md), conferir a branch, o estado do repositório e os arquivos existentes.

**Estado: PAUSADO**, conforme decisão do proprietário registrada em 2026-10-09 (America/Sao_Paulo). Prioridades: concluir PepDay (Happy Day no histórico) e WP Rotina antes de retomar o software da loja. Não iniciar evolução funcional por conta própria. A retomada depende de instrução explícita do proprietário.

## Limites de trabalho durante a pausa

- Apenas inspeção e documentação autorizadas. Não editar funcionalidades, dependências, configurações de execução ou infraestrutura.
- Não tocar produção: não executar deploy, reiniciar serviços, alterar variáveis no Render, acessar ou modificar dados de produção, migrar banco ou sincronizar/importar anúncios.
- Não presumir que uma rota GET é somente leitura: o código contém rotas que inicializam tabelas ou importam dados. Não chamar endpoints de produção para confirmar este checkpoint.
- Não executar o backend com credenciais reais nem disparar chamadas ao Mercado Livre ou Gemini.
- Preservar segredos: nunca registrar valores de tokens, chaves, senhas, URLs de conexão ou dados pessoais em documentos, commits, PRs ou saídas. Nomes de variáveis podem ser citados sem valores.
- Inspecionar antes de editar; preservar arquivos, conteúdo preexistente e alterações de terceiros. Não substituir documentação sem incorporá-la.
- Trabalhar em branch separada e fazer commits somente de documentação para este checkpoint. Não enviar alterações diretamente à `main`.
- Pedir aprovação explícita do proprietário antes de merge. Antes de eventual merge, conferir se ele acionaria deploy automático e obter autorização específica se necessário; aprovação de documentação não autoriza deploy.
- Ao atualizar o checkpoint, separar fatos verificados no código, histórico informado e estado operacional não confirmado.

## Projetos que devem permanecer separados

- **CenterPhone Suite Expedição PRO V1.3**: ferramenta local Windows informada como funcionando. `ABRIR_CENTERPHONE_ETIQUETAS.bat` chama `CenterPhone_Suite_Expedicao_PRO_V1_3.ps1`. Deve permanecer intocada: não editar, mover, executar, integrar ou substituir seus arquivos neste trabalho.
- PepDay e WP Rotina são prioridades externas a este repositório; não copiar seus arquivos, regras ou funcionalidades para cá.
- No espelho do projeto ChatGPT WP Imports Suite, `sources/` é material sincronizado somente para consulta; não editar, renomear, mover ou excluir seus arquivos.
