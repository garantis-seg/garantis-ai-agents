# v5 (agente): o redator lê os autos antes de escrever

Card 869ffv22t. Decisão do Alfredo de 23/10/2026: "núcleo obrigatório + índice
navegável; o redator vira v5 como agente". Código em 23/10/2026.

Esta seção entra no `README.md` do ficha_writer depois do PR #280.

## Quando o v5 liga

A rota é a mesma: `POST /ficha/write-fields`. O modo sai do request:

| O request traz | Modo |
|---|---|
| `nucleo` e `indice_navegavel` (e `esqueleto`) | v5 |
| `esqueleto`, sem `nucleo` | v4 |
| sem `esqueleto` | v3 |

O v4 e o v3 não mudam. Um request com só `nucleo` ou só `indice_navegavel` dá
422: o schema recusa o meio v5.

## Entrada: o v4 mais 2 chaves

```json
{
  "nucleo": {
    "acordaos": [{"processo": "16327.721182/2019-21", "doc_id": "carf:acordao.pdf", "texto": "..."}],
    "peticao_inicial": {"doc_id": "...", "texto": "..."},
    "ultima_decisao": {"doc_id": "...", "texto": "..."},
    "cdas": [],
    "premissas_v3": {},
    "qualificacao_s2c": {}
  },
  "indice_navegavel": [
    {"doc_id": "carf:recurso.pdf", "nome": "recurso.pdf", "tipo": "recurso", "data": "01/09/2026",
     "processo": "16327.721182/2019-21", "paginas": 2, "n_chars": 180,
     "documento_indexado": {"...": "to_dict() do DocumentoIndexado"}}
  ]
}
```

- Todo modelo usa `extra="forbid"`. Chave a mais dá 422.
- `peticao_inicial` e `ultima_decisao` podem ser `null`.
- O núcleo entra INTEIRO no prompt. Ele é a leitura obrigatória.
- O índice entra no prompt SEM o conteúdo. O agente abre um documento do índice
  com uma ferramenta. Sem `documento_indexado`, o documento aparece com
  `legivel=false` e o agente não consegue abrir o documento.

## As 2 fases

1. **Fase A (navegação), sem schema.** O LLM escolhe UMA ferramenta por turno:
   `resumir_com_missao`, `perguntar_ao_documento` ou `pedir_pagina`. O código
   executa a ferramenta. O Leitor é o `doc_reader`. O código resolve cada `sid`
   em página e trecho literal.
2. **Fase B (escrita), JSON.** O LLM escreve os slots no JSON do v4, mais a
   `trilha_leitura`. O código confere a saída. O erro volta ao LLM como
   `{campo, erro, valor_anterior}`, por até 3 rodadas (as do v4).

Budget da fase A (`ferramentas.py`):

| Teto | Valor |
|---|---|
| Chamadas de ferramenta por ficha | 25 |
| Chamadas por documento | 5 |
| Páginas cruas por documento | 3 |
| Falhas seguidas de (ferramenta, documento) antes do circuit breaker | 3 |
| Turnos seguidos sem JSON legível antes de encerrar a fase A | 3 |

Budget esgotado encerra a leitura. O agente escreve com o que leu, e as regras
duras continuam a valer. Sem nenhum documento legível no índice, a fase A não
chama o LLM.

## Saída: o v4 mais 4 chaves

```json
{
  "trilha_leitura": [
    {"slot": "bullets[0]", "doc_id": "carf:recurso.pdf", "paginas": [2],
     "trecho_apoio": "O recurso especial não foi admitido em 01/09/2026."}
  ],
  "documentos_lidos": ["carf:recurso.pdf"],
  "chamadas_ferramenta": 2,
  "budget_esgotado": false
}
```

`prompt_version` = `ficha_writer_v5+<hash>`. O hash muda com `prompts_v5.py`,
`prompts_v4.py` ou `schemas.py`.

## Regras duras (no código)

1. Todas as regras do v4 (`validacao.py`) continuam: slots pedidos, `max`,
   obrigatório, cifra em `valor.descricao`, processos citáveis, regra 25,
   status do SERPRO (regra 26), corretor, alertas respondidos.
2. `merito.p1`, `merito.p2`, `ultima_decisao.texto`, `descricao_infracao` e todo
   `bullets[i]` com texto têm pelo menos 1 item na trilha. Sem trilha, o slot
   reprova com o erro `"<slot>: slot sem trilha_leitura"`, e a próxima rodada
   pede só esse slot.
3. O `doc_id` da trilha existe no núcleo ou no índice.
4. A fase A leu de fato o documento do índice. Um documento do núcleo conta
   como lido.
5. Com o texto disponível, o `trecho_apoio` está no documento (nas páginas
   citadas, se há páginas). A comparação ignora acento, caixa e espaço
   repetido. `"..."` junta 2 pedaços. O teto é 200 caracteres.

Depois de 3 rodadas com erro, a resposta é `success=false` com `erros[]`, como
no v4. Este é o "422 estruturado" do write-fields: a rota devolve HTTP 200, e o
shared reenvia `erros[]` em `campos_com_erro`.

## O que o shared tem de mandar

Para ligar o v5 no `fichas/redator.py`, o shared manda o request do v4 mais:

- `nucleo.acordaos[]`: `{processo, doc_id, texto}`.
- `nucleo.peticao_inicial`: `{doc_id, texto}` ou `null`.
- `nucleo.ultima_decisao`: `{doc_id, texto}` ou `null`.
- `nucleo.cdas`, `nucleo.premissas_v3`, `nucleo.qualificacao_s2c`: como estão.
- `indice_navegavel[]`: `{doc_id, nome, tipo, data, processo, paginas, n_chars, documento_indexado}`.
  Só `doc_id` é obrigatório.

O shared repassa a `trilha_leitura` da resposta ao auditor v3
(`auditor_ficha/README_v3.md`).

## Arquivos

| Arquivo | O que tem |
|---|---|
| `agent_v5.py` | As 2 fases e as regras duras da trilha |
| `ferramentas.py` | `Autos` (núcleo e índice), o budget, o loop da fase A, a conferência da citação. O auditor v3 usa o mesmo módulo |
| `prompts_v5.py` | Os prompts de navegação e de escrita. Reusa os blocos do v4 por import |
| `schemas.py` | `Nucleo`, `ItemIndice`, `TrilhaItem` e os campos novos do request e da resposta |

## Decisões de classe A (DECIDI-SOZINHO, 23/10/2026)

- Meio v5 (só `nucleo` ou só `indice_navegavel`) dá 422. Cair no v4 em silêncio
  jogaria fora a leitura que o shared mandou.
- O v5 exige `esqueleto`. O v5 é o v4 mais a leitura.
- O trecho da trilha tem de estar no documento. O pedido não exigia isso, mas
  sem essa regra a trilha pode ser inventada. É a regra 5 do qualificador.
- O código descarta, com log, o item da trilha de um slot fora da rodada, como
  a chave a mais do v4.
- Bullet opcional vazio não exige trilha.
- O código recusa uma ferramenta num documento do núcleo, com uma mensagem: o
  texto inteiro já está no prompt.

## Testes

`tests/test_ficha_writer_v5.py` (sem rede e sem LLM).
