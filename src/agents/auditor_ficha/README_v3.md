# v3 (agente): o auditor abre os autos para refutar

Card 869ffv22t. Decisão do Alfredo de 23/10/2026: "núcleo obrigatório + índice
navegável; o auditor vira v3 como agente". Código em 23/10/2026.

Esta seção entra no `README.md` do auditor_ficha depois do PR #280.

## Quando o v3 liga

A rota é a mesma: `POST /ficha/auditar`. O v3 liga quando o request traz
`nucleo`, `indice_navegavel` ou `trilha_leitura`. O v2 não muda para o request
antigo.

O v2 não tinha ferramenta, de propósito: o verificador com ferramenta deu mais
falso-positivo. O v3 contém esse risco com 2 regras do código. Cada acusação
traz prova de documento, e uma acusação sem prova não fica no balde 1.

## Entrada: o v2 mais 3 chaves

- `nucleo`: o mesmo do redator v5 (`ficha_writer/README_v5.md`).
- `indice_navegavel`: o mesmo do redator v5.
- `trilha_leitura`: a trilha que o redator v5 devolveu,
  `[{slot, doc_id, paginas, trecho_apoio}]`. Pode vir vazia.

Regras do schema:

- O v3 exige `nucleo` e `indice_navegavel`. Meio v3 dá 422.
- O v3 NUNCA recebe `gabarito` (Livro §10.2). Um request v3 com `gabarito` dá 422.
- Chave a mais dá 422, como no v2.

## As 2 fases

1. **Fase A (navegação), sem schema.** O auditor abre os documentos que o
   redator citou na trilha, e outros, com as ferramentas do redator v5. O
   prompt manda procurar o trecho que CONTRADIZ a ficha.
2. **Fase B (veredito), JSON.** A saída do v2, com prova em cada item e
   `fatos_conferidos`. O código confere a saída e pede 1 correção (as `MAX_RODADAS = 2`
   do v2).

Budget da fase A: 20 chamadas por ficha, 5 por documento, 3 páginas cruas por
documento, circuit breaker depois de 3 falhas seguidas.

## Saída: o v2 mais 4 chaves

Cada item do `balde1` e do `balde2` ganha 2 chaves:

```json
{"campo": "bullets[0]", "motivo": "...", "regra": "D-01", "correcao_sugerida": "...",
 "prova": {"doc_id": "carf:recurso.pdf", "pagina": 2,
           "trecho": "O recurso especial não foi admitido em 01/09/2026."},
 "sem_prova_no_doc": false}
```

A resposta ganha:

```json
{
  "fatos_conferidos": [
    {"slot": "bullets[0]", "doc_id": "carf:recurso.pdf", "confere": false,
     "motivo": "o despacho diz não admitido"}
  ],
  "documentos_lidos": ["carf:recurso.pdf"],
  "chamadas_ferramenta": 1,
  "budget_esgotado": false
}
```

Os campos v1 (`aprovado`, `reprovacoes`, `pendencias`) continuam derivados, como
no v2. `prompt_version` = `auditor_ficha_v3+<hash>`.

## Regras duras (no código)

1. Cada item dos baldes traz `prova` {doc_id, pagina, trecho} OU
   `sem_prova_no_doc: true`. Nunca os dois e nunca nenhum.
2. A prova cita um documento do núcleo ou um documento do índice que o auditor
   leu na fase A. Com o texto disponível, o trecho está na página citada.
3. Um fato "contradito" sem prova de documento NÃO fica no balde 1. O código
   move o item ao balde 2 com grau `media`. Ele vira pendência e não retém a
   ficha.
4. Todo slot da trilha do redator tem um item em `fatos_conferidos`. Silêncio
   não aprova. Todo `confere=false` tem um item no balde 1 ou no balde 2 do
   mesmo campo. O `doc_id` do fato existe no núcleo ou no índice.
5. `divergencias_gabarito` fica vazio.
6. As regras do v2 continuam: o código calcula o veredito, a regra fora do
   checklist leva a marca "(ancora nao reconhecida)", e o item "SÓ balde 2" vai
   ao balde 2.

Saída com erro depois de 2 rodadas: `success=false`, `aprovado=false`,
`auditor_enabled=false` e `erros_validacao[]`. É o estado "não auditada" do v2.

## O que o shared tem de mandar

O request do v2 sem `gabarito`, mais:

- `nucleo`: o mesmo objeto que foi ao redator v5.
- `indice_navegavel`: a mesma lista que foi ao redator v5.
- `trilha_leitura`: a `trilha_leitura` da resposta do redator v5, sem mudança.

O shared lê `fatos_conferidos` e as provas dos baldes para o `meta`.

## Arquivos

| Arquivo | O que tem |
|---|---|
| `agent_v3.py` | As 2 fases, a conferência da prova e a regra do balde |
| `prompts_v3.py` | Os prompts de navegação e de veredito. Reusa os blocos do v2 por import |
| `schemas.py` | `ProvaDoc`, `ItemBalde1V3`, `ItemBalde2V3`, `FatoConferido`, `SaidaAuditorV3` e os campos novos |

A navegação é o módulo `ficha_writer/ferramentas.py`, o mesmo do redator v5.

## Decisões de classe A (DECIDI-SOZINHO, 23/10/2026)

- Meio v3 dá 422: o v3 precisa dos autos.
- A prova de um documento do índice exige que o AUDITOR tenha lido o documento.
  A leitura do redator não conta.
- Todo slot da trilha precisa de conferência. Sem essa regra, o auditor
  aprovaria em silêncio.
- O teto de 5 chamadas por documento vale também no auditor.
- O item movido ao balde 2 pela regra 3 leva `sem_prova_no_doc=true` e uma
  recomendação para um humano conferir nos autos.

## Testes

`tests/test_auditor_ficha_v3.py` (sem rede e sem LLM).
