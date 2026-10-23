"""auditor_ficha: o AUDITOR CEGO da ficha (etapa S6), versao 2.

Ultimo portao antes de a ficha ser persistida. Confere a ficha (S4, ja
aprovada na S5) contra o dossie, o esqueleto da S3b e o gabarito, com o
checklist do Livro da Ficha por bloco. Devolve o veredito em dois baldes
(Livro §10.2):

- balde 1: erro objetivo. Volta ao redator (S4).
- balde 2: juizo de substancia. Vira pendencia no `meta`. Nunca vai ao redator.

O codigo calcula o veredito: `retida` so com balde 2 de grau alta,
`aprovada_com_correcoes` com balde 1, `aprovada` sem nenhum dos dois.

Ver README.md nesta pasta.
"""

from .agent import auditar_ficha, calcular_veredito
from .schemas import (
    AuditarFichaRequest,
    AuditarFichaResponse,
    ItemBalde1,
    ItemBalde2,
    Reprovacao,
)

__all__ = [
    "auditar_ficha",
    "calcular_veredito",
    "AuditarFichaRequest",
    "AuditarFichaResponse",
    "ItemBalde1",
    "ItemBalde2",
    "Reprovacao",
]
