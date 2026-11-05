import json
import re

from autonomy.plan_validator import validate_plan


SYSTEM_PROMPT = """Voce e um engenheiro senior de firmware embarcado e planejamento tecnico.
Responda em portugues do Brasil e retorne SOMENTE um objeto JSON valido.
O contexto contem dados de analise local; nao invente fatos nem trate heuristicas como defeitos confirmados.
Diferencie evidencias observadas de hipoteses de causa.
Nao proponha executar comandos, compilar, gravar firmware, apagar arquivos ou alterar arquivos nesta etapa.
Nao solicite nem exponha chaves, tokens ou credenciais.
Use somente caminhos relativos presentes no inventario fornecido.
Se nao houver achados, explique isso e proponha no maximo tarefas de verificacao justificadas pelo contexto.
Formato obrigatorio:
{
  "summary": "resumo tecnico",
  "findings": [{"id":"F001","severity":"critical|high|medium|low|info","title":"...","file":"caminho relativo ou vazio","line":1,"evidence":"...","cause_hypothesis":"...","confidence":"high|medium|low","recommendation":"..."}],
  "actions": [{"id":"A001","title":"...","description":"...","priority":"critical|high|medium|low","files":["caminho relativo"],"related_findings":["F001"],"depends_on":[],"acceptance_criteria":["..."],"requires_approval":true}],
  "risks": [{"description":"..."}]
}
Todos os campos de cada item devem respeitar o formato demonstrado. Nao inclua Markdown."""


class PlanningAgent:
    """Gera e valida planos. Nao possui ferramentas de escrita ou execucao."""

    def __init__(self, provider, model, max_input_chars=50000):
        if provider is None or not callable(getattr(provider, "send_message", None)):
            raise TypeError("provider precisa disponibilizar send_message(messages, model).")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("Modelo de IA nao configurado.")
        self.provider = provider
        self.model = model.strip()
        self.max_input_chars = max(1000, int(max_input_chars))

    @staticmethod
    def _parse_json(response):
        if not isinstance(response, str):
            raise ValueError("A resposta do provedor nao e texto.")
        cleaned = response.strip()
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE).strip()
        try:
            result = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(f"A IA nao retornou JSON valido: {exc}") from exc
        if not isinstance(result, dict):
            raise ValueError("A resposta JSON precisa ser um objeto.")
        return result

    def create_plan(self, planning_input):
        if not isinstance(planning_input, dict):
            raise TypeError("planning_input precisa ser um dicionario.")
        payload = json.dumps(planning_input, ensure_ascii=False)
        if len(payload) > self.max_input_chars:
            raise ValueError(
                f"Contexto de planejamento excede {self.max_input_chars} caracteres. "
                "Reduza o inventario ou os achados antes de enviar."
            )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Elabore o plano tecnico com base neste contexto:\n" + payload},
        ]
        response = self.provider.send_message(messages, self.model)
        plan = self._parse_json(response)
        return validate_plan(plan, inventory=planning_input.get("inventory", []))