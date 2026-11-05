import json
from pathlib import Path

from providers.openai_provider import OpenAIProvider
from project_engine.project_analyzer import ProjectAnalyzer
from autonomy.planning_agent import PlanningAgent


class PlanningService:
    # app_root: raiz do Agent Studio.
    # project_root: raiz do firmware autorizado para analise.
    # Nenhum arquivo do firmware e alterado por este servico.

    def __init__(
        self,
        app_root,
        project_root,
        provider=None,
        model=None,
        max_files=200,
        max_total_chars=60000,
        max_input_chars=50000,
    ):
        self.app_root = Path(app_root).expanduser().resolve(strict=True)
        self.project_root = Path(project_root).expanduser().resolve(strict=True)

        if not self.app_root.is_dir():
            raise NotADirectoryError(str(self.app_root))

        if not self.project_root.is_dir():
            raise NotADirectoryError(str(self.project_root))

        # Quando provider nao e fornecido, utiliza a configuracao existente.
        if provider is None:
            providers_path = self.app_root / "config" / "providers.json"
            settings_path = self.app_root / "config" / "settings.json"

            if not providers_path.is_file():
                raise FileNotFoundError("config/providers.json nao encontrado.")

            if not settings_path.is_file():
                raise FileNotFoundError("config/settings.json nao encontrado.")

            with providers_path.open("r", encoding="utf-8-sig") as file:
                providers_config = json.load(file)

            with settings_path.open("r", encoding="utf-8-sig") as file:
                settings = json.load(file)

            api_key = (
                providers_config.get("openai", {}).get("api_key", "")
            )

            if not isinstance(api_key, str) or not api_key.strip():
                raise ValueError("Chave da OpenAI nao configurada.")

            if model is None:
                model = settings.get("model", "gpt-4.1-mini")

            provider = OpenAIProvider(api_key.strip())

        if not callable(getattr(provider, "send_message", None)):
            raise TypeError("Provider precisa implementar send_message(messages, model).")

        if not isinstance(model, str) or not model.strip():
            raise ValueError("Modelo de IA nao configurado.")

        self.provider = provider
        self.model = model.strip()
        self.max_input_chars = max_input_chars

        self.analyzer = ProjectAnalyzer(
            max_files=max_files,
            max_total_chars=max_total_chars,
        )

    def analyze_and_plan(
        self,
        objective="Analisar e planejar melhorias no firmware",
    ):
        # Analise local.
        analysis = self.analyzer.analyze(self.project_root)

        # Prepara somente os dados compactos de planejamento.
        planning_input = self.analyzer.build_planning_input(
            analysis,
            objective=objective,
        )

        # Nao compartilhar o caminho absoluto do computador com a API.
        planning_input["project_path"] = self.project_root.name

        # Esta chamada utiliza a API somente quando o metodo e executado.
        agent = PlanningAgent(
            provider=self.provider,
            model=self.model,
            max_input_chars=self.max_input_chars,
        )

        plan = agent.create_plan(planning_input)

        return {
            "analysis": analysis,
            "planning_input": planning_input,
            "plan": plan,
        }
