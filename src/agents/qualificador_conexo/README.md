# S2c — qualificador do conexo

Card 869ffv22t. Plano de 21/10/2026, Parte 3, S2c. Código em 22/10/2026. A pergunta 3
entrou em 23/10/2026 (v2).

O agente responde 3 perguntas sobre um conexo. Cada resposta tem prova literal.

1. Cada processo é fiscal?
2. Qual é o estado de cada garantia: `ativa`, `substituida`, `liberada` ou `sem_evidencia`?
3. Qual é o estado processual de cada PA (CARF/TIT) e de cada processo judicial alvo?

A S2 (`garantis_shared.fichas.contratos.classificar_tipo`) lê a resposta em
`estados_s2c: {garantia_id: estado}`. A S0 (`prontidao.py`) lê `e_fiscal` em
`SinalProcesso` e bloqueia a ficha com `processo_nao_fiscal`. A S3b (esqueleto) lê
`processos[].estado_processual` para montar a timeline e o termômetro.

## Rota

`POST /ficha/qualificar-conexo`

| Código | Quando | Corpo |
|---|---|---|
| 200 | A resposta passou nas regras duras | `QualificarConexoResponse` |
| 422, `detail` objeto | A resposta do LLM falhou nas regras duras depois de 2 rodadas de correção | `{"detail": {"erro": "qualificacao_invalida", "erros": [{campo, erro, valor_anterior}], "rodadas", "custo_usd", "modelo", "prompt_version"}}` |
| 422, `detail` lista | O FastAPI recusou a entrada (chave extra, enum errado) | Erro padrão do FastAPI. Corrija o pedido |
| 500 | Falha de infraestrutura | `{"detail": "<repr>"}` |

O chamador pode tentar de novo depois de um 422 com `detail` objeto. Não tente
de novo um 422 com `detail` lista sem corrigir o pedido.

## Entrada

Todo modelo usa `extra="forbid"`. Chave a mais é erro.

```json
{
  "conexo_id": 77,
  "empresa": {"razao_social": "ACME S.A.", "cnpj_raiz": "12345678", "grupo_economico": ["12345678"]},
  "classe_macro": "FISCAL",
  "processos": [
    {"numero": "0001234-56.2020.4.03.6182", "item_type": "judicial", "classe_cnj_code": 1116,
     "assunto": "IRPJ", "tribunal": "TRF3", "partes": ["ACME S.A.", "União"], "e_da_empresa": true}
  ],
  "garantias": [
    {"id": "g-1", "especie": "bank_letter_of_guarantee", "issuer_code": "341", "valor": 1000000.0,
     "susep_number": null, "termination_date": "2030-01-01", "processo_numero": "0001234-56.2020.4.03.6182"}
  ],
  "documentos_indexados": [
    {"doc_id": "ef:peticao.pdf", "nome": "peticao.pdf", "tipo": "peticao", "paginas": 2,
     "gcs_path": "gs://...", "processo_numero": "0001234-56.2020.4.03.6182",
     "documento_indexado": {"...": "to_dict() do DocumentoIndexado"}}
  ],
  "alertas": [
    {"codigo": "garantia_sem_vigencia", "escopo": "garantia", "alvo": "g-1", "texto": "A fiança não tem fim de vigência."}
  ],
  "auditar": true
}
```

Notas da entrada:

- `garantias[].id` vem de `contratos.garantia_id`. A S2c, o fe-api e a S2 usam a mesma função.
- `especie` aceita `surety_bond`, `bank_letter_of_guarantee`, `judicial_deposit` e `judicial_attachment`.
- `documentos_indexados[]` usa os campos do ItemDoc (`indice_docs.py`): `doc_id`, `nome`,
  `tipo`, `paginas`, `ancora`, `gcs_path`, `processo_numero`, `data`, `movimento_ref`,
  `grau`, `fls`.
- `documentos_indexados[].documento_indexado` é o `to_dict()` que o `/doc-indexer/indexar`
  devolve. Sem ele, o agente vê o documento no índice, mas não consegue ler o documento.
  O chamador junta o item do índice com o conteúdo da S2b.
- `alertas[]` é a lista que o CÓDIGO detectou antes do LLM. Exemplos:
  `classe_cnj_nao_fiscal`, `processo_sem_autos`, `garantia_sem_vigencia`,
  `garantias_mesma_especie`, `daycoval_e_outra_vigentes`. `escopo` aceita `processo`,
  `garantia` e `conexo`.
- `auditar` liga o auditor. O default é `true`.

## Saída

```json
{
  "conexo_id": 77,
  "processos": [
    {"numero": "...", "e_fiscal": false, "confianca": "alta",
     "prova": {"doc_id": "tjsp:inicial.pdf", "pagina": 1, "trecho": "Ação de indenização por danos morais..."},
     "motivo": "Ação de consumidor por dano moral.", "fonte": "documentos", "requer_revisao": false}
  ],
  "garantias": [
    {"id": "g-1", "estado": "substituida", "substituida_por": "g-2",
     "debito_coberto": {"processo_numero": "...", "valor": 1000000.0},
     "prova": {"doc_id": "...", "pagina": 2, "trecho": "Defiro a substituição da carta de fiança..."},
     "documentos_lidos": ["ef:peticao.pdf"], "confianca": "alta", "motivo": "...",
     "fonte": "documentos", "requer_revisao": false}
  ],
  "alertas_respondidos": [
    {"codigo": "garantia_sem_vigencia", "alvo": "g-1", "resposta": "confirmado",
     "prova": null, "motivo": "...", "requer_revisao": false}
  ],
  "divergencias": [],
  "alertas_gerados": [],
  "requer_revisao": false,
  "modo": "documentos",
  "auditado": true,
  "budget_esgotado": false,
  "rodadas_de_correcao": 0,
  "custo_usd": 0.0123,
  "chamadas": 4,
  "chamadas_llm": 7,
  "modelo": "<model_for('ficha_calculo')>",
  "modelo_auditor": "<model_for('ficha_auditoria_evidencias')>",
  "prompt_version": "qualificador_conexo_v2+<hash>"
}
```

O LLM escreve só `processos`, `garantias` e `alertas_respondidos` (modelo
`QualificacaoLLM`). O código calcula os outros campos:

| Campo | Regra |
|---|---|
| `fonte` | `documentos` quando o item tem documento legível para citar. `capa` quando não tem |
| `requer_revisao` (item) | `true` quando o auditor diverge, ou quando um processo `capa` sai não fiscal |
| `requer_revisao` (topo) | `true` quando um item tem `requer_revisao` |
| `divergencias[]` | Uma por afirmação que o auditor não aceitou |
| `alertas_gerados[]` | Alertas do código para a prontidão: `{codigo, escopo, alvo}`. Ver a pergunta 3 e o modo capa |
| `chamadas` | Chamadas de ferramenta na fase A |
| `chamadas_llm` | Chamadas de LLM nas 3 fases |
| `prompt_version` | `qualificador_conexo_v2` mais o hash de `prompts.py` e `schemas.py`. Compare por prefixo |

Tetos: `trecho` até 300 caracteres. `motivo` até 200 caracteres.

## Regras duras (no código, não no prompt)

O código valida a resposta do LLM em `agent.validar_qualificacao`.

1. A resposta tem um item por processo, um por garantia e um por alerta de entrada.
   Item a mais ou a menos é erro.
2. `e_fiscal=false` exige `prova`.
3. `estado` `substituida` ou `liberada` exige `prova`.
4. `sem_evidencia` exige `documentos_lidos` não vazio. Cada doc_id da lista foi lido na
   fase A (o código registra as leituras). O agente tem de ler antes de desistir.
   `sem_evidencia` não exige `prova`: a falta de prova é o próprio estado.
5. Alerta `refutado` exige `prova`.
6. Toda `prova` tem `doc_id` do índice e `pagina` do documento. Com o documento
   legível, o `trecho` tem de estar na página citada. A comparação ignora acento,
   caixa e espaço repetido. `...` separa pedaços do trecho.
7. `substituida_por` só vale com `estado=substituida`, e aponta para outra garantia da entrada.
8. `debito_coberto.processo_numero` é um processo da entrada.

Erro de regra volta ao LLM como `{campo, erro, valor_anterior}`. Há 1 emissão e até 2
rodadas de correção. Depois disso, a rota devolve 422.

### Modo capa

O conexo está em modo capa quando nenhum documento é legível: índice vazio, ou índice
sem `documento_indexado`. Neste modo:

- Não há fase A. O LLM recebe 1 prompt e responde pelos sinais da capa (classe CNJ,
  assunto, partes, tipo do item).
- O código força `prova=null` e `confianca="baixa"` em todo processo e alerta.
- O código preenche as garantias: `estado="ativa"`, `confianca="baixa"`, `prova=null`,
  `documentos_lidos=[]`, `motivo="sem documentos legíveis: estado não verificado"`,
  `fonte="capa"`, `requer_revisao=true`.
- A saída leva `alertas_gerados` com `qualificacao_sem_documentos` e
  `estado_processual_sem_documentos`, os 2 com escopo `conexo` e `alvo=null`. O shared
  leva os alertas ao catálogo de prontidão.
- Decisão de 23/10/2026 (classe A): no modo capa, o agente não leu nada. Então ele não
  marca `sem_evidencia`. Esse estado fica reservado ao caso em que o agente leu
  documentos e não achou prova (regra 4).
- Processo não fiscal sai com `requer_revisao=true`.
- O auditor não roda: não há prova para auditar.

Fora do modo capa, um processo sem documento próprio também sai com `fonte="capa"` e
`confianca="baixa"`, e a regra 2 não se aplica a ele. O processo "tem documento" quando
um documento legível tem o mesmo `processo_numero`. Se nenhum documento legível tem
`processo_numero`, o vínculo é desconhecido, e todo documento serve a todo processo.

## Pergunta 3: estado processual

Desde 23/10/2026 (v2). Motivo: na rodada do IRB 1481420 (23/10/2026), a S3b montou a
timeline sem os sinais de decisão, porque eles só existem nos autos. O CARF saiu "Não
disponível na fonte". A etapa atual saiu CSRF, porque o aggregate estava velho. A ficha
aprovada dizia: "via esgotada: RE não conhecido em 24/06/2026, Cobrança, muito_quente".

### Saída

Cada processo leva `estado_processual`. Todo modelo usa `extra="forbid"`.

```json
"estado_processual": {
  "origem": {"tipo": "auto_de_infracao|despacho_decisorio|aiim|null", "data": "2019-05-10|null"},
  "decisoes": [
    {"etapa": "DRJ|CARF|CSRF|DTJ|camara_julgadora|camara_superior|1a_instancia|2a_instancia|STJ|STF",
     "resultado": "favoravel|desfavoravel|parcial",
     "data": "2024-03-12",
     "acordao": "1402-004.321|null",
     "prova": {"doc_id": "carf:acordaos.pdf", "pagina": 2, "trecho": "<até 300 caracteres>"}}
  ],
  "recurso_pendente": {"tipo": "<TipoRecurso>|null", "de_quem": "contribuinte|fazenda|null",
                       "data": "AAAA-MM-DD|null"} ,
  "admissibilidade": {"recurso": "<TipoRecurso>",
                      "resultado": "admitido|nao_admitido|nao_conhecido",
                      "orgao": "presidencia_camara|presidencia_csrf|presidencia_camara_superior_tit|vice_presidencia_tribunal|STJ|STF|outro",
                      "data": "2026-06-24|null",
                      "prova": {"doc_id": "...", "pagina": 3, "trecho": "..."}},
  "cabe_agravo": "true|false|null",
  "via_esgotada": "true|false|null",
  "esgotada_em": "2026-06-24|null",
  "expedido_pgfn_em": "AAAA-MM-DD|null",
  "voto_qualidade": "true|false|null",
  "confianca": "alta|media|baixa",
  "documentos_lidos": ["carf:acordaos.pdf"],
  "requer_revisao": false
}
```

Notas da saída:

- `recurso_pendente` e `admissibilidade` podem ser `null`. Os booleanos são JSON
  (`true`, `false`, `null`). O exemplo usa texto só para mostrar os valores.
- `TipoRecurso`: `impugnacao`, `manifestacao_inconformidade`, `RV`, `RE`,
  `recurso_oficio`, `recurso_ordinario`, `agravo`, `embargos`, `apelacao`,
  `agravo_instrumento`, `recurso_especial`, `recurso_extraordinario`. `RV` e `RE` são os
  recursos ADMINISTRATIVOS (CARF e TIT). `recurso_especial` (STJ) e
  `recurso_extraordinario` (STF) são os recursos JUDICIAIS.
- `resultado` é do ponto de vista do contribuinte.
- `data` da decisão é a da SESSÃO de julgamento, não a da publicação (Livro da Ficha,
  lição 34).
- `requer_revisao` do estado: o CÓDIGO escreve. Ver "Auditor".
- `ultima_decisao` não sai: o shared toma a decisão de `data` maior em `decisoes`.
- O processo não fiscal pode sair com `estado_processual=null`.

### As etapas

| Trilho | Régua | `origem.tipo` | `decisoes[].etapa` |
|---|---|---|---|
| CARF (federal) | AI ou DD → DRJ → CARF → CSRF → PGFN | `auto_de_infracao`, `despacho_decisorio` | `DRJ`, `CARF`, `CSRF` |
| TIT-SP (estadual) | AIIM → DTJ → Câmara Julgadora → Câmara Superior → UFC → PGE | `aiim` | `DTJ`, `camara_julgadora`, `camara_superior` |
| Judicial | 1ª instância → 2ª instância → STJ → STF | `null` | `1a_instancia`, `2a_instancia`, `STJ`, `STF` |

Sinais de esgotamento que o prompt ensina: RE não conhecido ou não admitido pela
Presidência da CSRF, prazo de agravo, "enviado para cobrança", "expedido para PGFN",
"Baixa definitiva no contencioso", "AIIM enviado para a UFC".

### Regras duras da pergunta 3

O código valida em `agent._validar_estado` e em `agent.validar_qualificacao`.

1. `e_fiscal=true` exige `estado_processual`.
2. Toda decisão e toda admissibilidade exigem `prova`. A prova segue a regra 6 geral:
   `doc_id` do índice e trecho literal na página citada.
3. Toda data é ISO `AAAA-MM-DD` e é uma data válida. O schema valida a data.
4. `via_esgotada=true` exige `esgotada_em` e uma decisão ou admissibilidade com data até
   `esgotada_em`. `esgotada_em` só vale com `via_esgotada=true`.
5. `cabe_agravo` (`true` ou `false`) exige `admissibilidade.resultado=nao_admitido` e
   `admissibilidade.data`. O código NÃO calcula o prazo de agravo (5 dias úteis). Ele
   devolve a data, e o shared decide.
6. A fase A leu cada doc_id de `documentos_lidos`.
7. Alerta `aggregate_diz_<etapa>` exige `prova` nas 2 respostas (confirmado ou
   refutado), quando o processo alvo tem documento legível.

### Alertas da entrada que o LLM responde

| Código | O que o chamador diz | O que o agente faz |
|---|---|---|
| `aggregate_diz_<etapa>` | A instância que o aggregate tem (ex.: `aggregate_diz_CSRF`) | Confirma ou refuta, com prova |
| `sem_acordao_no_indice` | A base não achou acórdão no índice | Refuta com a prova do acórdão, ou confirma |

### Sem documento

- Modo capa: o código guarda só `origem.tipo`. O resto sai vazio ou `null`:
  `decisoes=[]`, `confianca="baixa"`, `documentos_lidos=[]`. A saída leva
  `alertas_gerados` com `estado_processual_sem_documentos`, escopo `conexo`.
- Modo documentos, processo sem documento próprio e sem decisão provada: o estado sai
  com `confianca="baixa"`. A saída leva `estado_processual_sem_documentos`, escopo
  `processo`, `alvo` = número do processo.

## Fases

| Fase | O que faz | Schema |
|---|---|---|
| A — decisão | O LLM escolhe UMA ferramenta por turno. O código executa | Sem schema (JSON tolerante) |
| B — emissão | O LLM emite a resposta fechada. O código valida | `response_mime_type=application/json` |
| Auditor | Um segundo modelo tenta refutar cada prova | JSON fechado |

Todas as chamadas usam `temperature=0` e `seed` fixo por conexo, fase e turno.

### Ferramentas da fase A

| Ferramenta | Args | O que devolve |
|---|---|---|
| `resumir_com_missao` | `doc_id`, `missao`, `item` | Resumo do `doc_reader` e os trechos literais citados |
| `perguntar_ao_documento` | `doc_id`, `pergunta`, `item` | Resposta do `doc_reader` e os trechos literais citados |
| `pedir_pagina` | `doc_id`, `pagina`, `item` | Texto cru da página (até 6000 caracteres) |
| `{"fim": true}` | — | Encerra a fase A |

`item` é o número do processo ou o id da garantia que a leitura serve. O código resolve
cada `sid` citado pelo Leitor em página e texto literal. O agente copia o trecho daí.

### Budget e circuit breaker

| Teto | Valor | O que acontece no teto |
|---|---|---|
| Chamadas por conexo | 30 | A fase A termina. A fase B roda com o que foi lido. `budget_esgotado=true` |
| Chamadas por item | 5 | A chamada volta com erro e não executa |
| Páginas cruas por documento | 3 | A chamada volta com erro |
| Falhas seguidas de (ferramenta, documento) | 3 | A ferramenta sai do menu daquele documento (`CircuitBreaker` do C4) |
| Turnos seguidos sem JSON legível | 3 | A fase A termina |

O budget nunca vira resposta sem prova: as regras duras continuam a valer na fase B.

## Prompt

`prompts.py`, `PROMPT_VERSION = "qualificador_conexo_v2"`.

- Persona: "analista que confere, não escreve".
- Pergunta 1, "é fiscal?". Fiscal: tributo federal, estadual ou municipal, execução
  fiscal, anulatória, mandado de segurança, declaratória ou repetição sobre tributo,
  embargos à execução fiscal, PAF no CARF, AIIM no TIT. Não fiscal: consumidor,
  trabalhista, cível comum, regulatório, concorrencial.
- Pergunta 2, por garantia: ativa, substituída (por qual), liberada (levantamento,
  desconstituição, baixa) ou sem evidência. Sempre com o trecho literal.
- Regra de 28/09/2026: deduza pelos sinais óbvios antes de responder `sem_evidencia`.
- Pergunta 3, por processo: as etapas, os sinais de esgotamento e a regra da data da
  sessão. Ver a seção "Pergunta 3: estado processual".
- Defesa contra injeção: todo dado de terceiro entra numa cerca com token aleatório
  por chamada (`<dados-{token}>`, `<achados-{token}>`). `json_sanitizado` neutraliza
  todo `<` que abre tag.

## Modelos

O código não escreve modelo à mão. A guarda é `tests/test_modelo_vem_do_papel.py`.

| Papel | Módulo | Registro |
|---|---|---|
| Qualificador (fases A e B) | `agent.DEFAULT_MODEL` | `model_for("ficha_calculo")` |
| Auditor | `auditor.DEFAULT_MODEL` | `model_for("ficha_auditoria_evidencias")` |
| Leitor | `doc_reader.agent.DEFAULT_MODEL` | `model_for("leitor_autos_monolith")` |

Os 2 primeiros são de famílias diferentes (regra anti-conluio). 22/10/2026: os papéis
são provisórios. O pedido ao Elton de `ficha_qualificador` e `ficha_auditor_qualificacao`
no registro está no card 869ffv22t.

## Auditor

O auditor recebe SÓ as afirmações e as provas. Ele não vê o conexo nem o índice. Ele
audita:

- cada processo com `e_fiscal=false`.
- cada garantia `substituida` ou `liberada`.
- cada alerta `refutado`.
- cada decisão e cada admissibilidade do estado processual (desde 23/10/2026).
  O `auditor.py` não mudou: ele recebe afirmações genéricas com prova. O código monta
  as afirmações em `agent._afirmacoes_auditaveis`.

Divergência numa decisão ou na admissibilidade: o código marca SÓ o estado processual
(`confianca="baixa"`, `requer_revisao=true`) e grava a divergência com
`alvo_tipo="estado_processual"` e `codigo` = `decisoes[i]` ou `admissibilidade`. O
`requer_revisao` do processo e o do topo não mudam. Esses 2 campos governam o bloqueio
de não fiscal no shared (decisão de 23/10/2026, classe A).

Divergência: o código rebaixa a `confianca` do item para `baixa`, marca
`requer_revisao=true` e grava a divergência em `divergencias[]`. Silêncio não aprova:
afirmação sem veredito, ou auditor com JSON inválido em 2 tentativas, conta como
divergência.

Sem 3ª leitura por ora. O plano pede uma leitura dirigida à página citada quando há
divergência. A 3ª leitura entra quando os 15 casos mostrarem a taxa de divergência.

## Testes

`tests/test_qualificador_conexo.py`, sem rede e sem LLM. O fornecedor de LLM e o Leitor
são dublês. Para rodar como o CI (`cloudbuild-deploy.yaml`):

```bash
pip install -r requirements.txt "pytest>=8.0.0" "pytest-asyncio>=0.24.0" "ruff==0.15.10"
python -m pytest -q -p no:cacheprovider
```
