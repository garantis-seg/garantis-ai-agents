"""
Sistema de carregamento e versionamento de prompts.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional


class PromptLoader:
    """Carregador de prompts com suporte a versionamento."""

    def __init__(self, prompts_dir: Optional[Path] = None):
        """
        Inicializa o carregador de prompts.

        Args:
            prompts_dir: Diretório raiz dos prompts. Se None, usa o diretório atual.
        """
        self.prompts_dir = prompts_dir or Path(__file__).parent
        self._index = self._load_index()

    def _load_index(self) -> dict:
        """Carrega o índice de prompts."""
        index_path = self.prompts_dir / "index.json"
        if not index_path.exists():
            return {}
        return json.loads(index_path.read_text(encoding="utf-8"))

    def load(
        self,
        agent_name: str,
        version: Optional[str] = None,
        process_data: Optional[str] = None,
    ) -> str:
        """
        Carrega um prompt para um agente, opcionalmente especificando versão.

        Args:
            agent_name: Nome do agente (ex: "timing_analysis")
            version: Versão do prompt (ex: "v3"). Se None, usa a versão ativa.
            process_data: Dados do processo para substituir no placeholder {DADOS_PROCESSO}

        Returns:
            Conteúdo do prompt com placeholders substituídos.

        Raises:
            ValueError: Se o agente ou versão não existir.
        """
        agent_config = self._index.get(agent_name)
        if not agent_config:
            raise ValueError(f"Agente desconhecido: {agent_name}")

        version = version or agent_config.get("active_version")
        if not version:
            raise ValueError(f"Nenhuma versão ativa definida para o agente: {agent_name}")

        version_info = next(
            (v for v in agent_config.get("versions", []) if v["id"] == version),
            None,
        )
        if not version_info:
            raise ValueError(f"Versão desconhecida {version} para o agente {agent_name}")

        # Carregar conteúdo do prompt
        prompt_path = self.prompts_dir / agent_name / version_info["file"]
        if not prompt_path.exists():
            raise ValueError(f"Arquivo de prompt não encontrado: {prompt_path}")

        prompt_content = prompt_path.read_text(encoding="utf-8")

        # Substituir placeholders
        today = datetime.now().strftime("%d/%m/%Y")
        prompt_content = prompt_content.replace("{DATA_ATUAL}", today)

        if process_data:
            prompt_content = prompt_content.replace("{DADOS_PROCESSO}", process_data)

        return prompt_content

    def list_versions(self, agent_name: str) -> list:
        """
        Lista todas as versões disponíveis para um agente.

        Args:
            agent_name: Nome do agente

        Returns:
            Lista de dicionários com informações das versões.
        """
        agent_config = self._index.get(agent_name, {})
        return agent_config.get("versions", [])

    def get_active_version(self, agent_name: str) -> Optional[str]:
        """
        Retorna a versão ativa para um agente.

        Args:
            agent_name: Nome do agente

        Returns:
            ID da versão ativa ou None.
        """
        agent_config = self._index.get(agent_name, {})
        return agent_config.get("active_version")

    def list_agents(self) -> list:
        """
        Lista todos os agentes disponíveis.

        Returns:
            Lista de nomes de agentes.
        """
        return list(self._index.keys())
