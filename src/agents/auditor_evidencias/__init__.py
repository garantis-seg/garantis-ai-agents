"""auditor_evidencias agent — AUDITOR do C4.

Julga, evidencia por evidencia, se o trecho citado SUSTENTA o valor da celula.
A existencia do trecho no documento ja foi provada por codigo (shared:
`evidencias.verificar_evidencias`); aqui a pergunta e semantica.

Adversarial por desenho (default = reprovar na duvida) e com modelo DIFERENTE
do calculador. Ver agent.auditar_evidencias + api.routes.calculo_ficha.

## Dois modos, e o segundo e ADITIVO (onda 9)

- `auditar_evidencias` — o modo de HOJE: grafo inteiro + todas as evidencias +
  textos inteiros, um veredicto binario por celula. E o que o harness do shared
  chama, continua intacto, e so morre na onda 6.
- `verificar_par` — o VERIFICADOR CEGO (DESENHO §2.3): UM par (afirmacao,
  ancora, trecho) por chamada, sem grafo, sem historico, sem documento inteiro.
  Quatro rotulos em vez de dois, `motivo_tipado` de enum fechado,
  `numeros_divergentes` computados em CODIGO e confianca DINCO em campo.

A privacao de contexto do segundo nao e economia: o HALLMARK mediu falsos
positivos ~5x maiores quando o verificador ganha contexto e ferramenta
(pesquisa §4.5). Ver a construcao e herdar a hipotese de quem construiu.
"""

from .agent import auditar_evidencias
from .schemas import (
    AuditarEvidenciasRequest,
    AuditarEvidenciasResponse,
    Veredicto,
)
from .verificador import verificar_par
from .verificador_schemas import (
    MOTIVOS_TIPADOS,
    VEREDITOS,
    VerificarParRequest,
    VerificarParResponse,
)

__all__ = [
    "auditar_evidencias",
    "AuditarEvidenciasRequest",
    "AuditarEvidenciasResponse",
    "Veredicto",
    "verificar_par",
    "VerificarParRequest",
    "VerificarParResponse",
    "VEREDITOS",
    "MOTIVOS_TIPADOS",
]
