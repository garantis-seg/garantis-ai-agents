"""Flag booleana de env dos agents.

A dona do vocabulario truthy e `garantis_shared.engine_v6.feature_flags.flag_enabled`
({'true','1','yes','on'}, com strip e lower; env ausente ou vazia = `default`, que e
bool). Este modulo so a re-exporta, pra uma cópia local não divergir do engine.

Env vars são estáticas durante o lifetime do container Cloud Run; restart pra
rotacionar.
"""
from garantis_shared.engine_v6.feature_flags import flag_enabled

__all__ = ["flag_enabled"]
