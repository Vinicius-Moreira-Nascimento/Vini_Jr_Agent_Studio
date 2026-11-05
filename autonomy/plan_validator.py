from pathlib import PurePosixPath


VALID_SEVERITIES = {"critical", "high", "medium", "low", "info"}
VALID_PRIORITIES = {"critical", "high", "medium", "low"}


class PlanValidationError(ValueError):
    pass


def _require_text(value, field, max_length=4000):
    if not isinstance(value, str) or not value.strip():
        raise PlanValidationError(f"Campo obrigatorio invalido: {field}")
    if len(value) > max_length:
        raise PlanValidationError(f"Campo excede o limite: {field}")
    return value.strip()


def _validate_relative_path(value, field):
    path_text = _require_text(value, field, 500).replace("\\", "/")
    path = PurePosixPath(path_text)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise PlanValidationError(f"Caminho fora da raiz ou invalido em {field}: {value}")
    if len(path.parts) and path.parts[0].endswith(":"):
        raise PlanValidationError(f"Caminho absoluto bloqueado em {field}: {value}")
    return path.as_posix()


def validate_plan(plan, inventory=None):
    """Valida estrutura, referências, caminhos e dependências. Não executa ações."""
    if not isinstance(plan, dict):
        raise PlanValidationError("O plano precisa ser um objeto JSON.")

    required = ("summary", "findings", "actions", "risks")
    for key in required:
        if key not in plan:
            raise PlanValidationError(f"Campo ausente no plano: {key}")

    _require_text(plan.get("summary"), "summary", 8000)
    findings = plan.get("findings")
    actions = plan.get("actions")
    risks = plan.get("risks")
    if not isinstance(findings, list) or len(findings) > 200:
        raise PlanValidationError("findings deve ser uma lista com no maximo 200 itens.")
    if not isinstance(actions, list) or len(actions) > 100:
        raise PlanValidationError("actions deve ser uma lista com no maximo 100 itens.")
    if not isinstance(risks, list) or len(risks) > 100:
        raise PlanValidationError("risks deve ser uma lista com no maximo 100 itens.")

    known_files = None
    if inventory is not None:
        known_files = {
            str(item.get("path", "")).replace("\\", "/")
            for item in inventory if isinstance(item, dict)
        }

    finding_ids = set()
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            raise PlanValidationError(f"Achado {index} nao e um objeto.")
        fid = _require_text(finding.get("id"), f"findings[{index}].id", 80)
        if fid in finding_ids:
            raise PlanValidationError(f"ID de achado duplicado: {fid}")
        finding_ids.add(fid)
        _require_text(finding.get("title"), f"findings[{index}].title", 500)
        severity = _require_text(finding.get("severity"), f"findings[{index}].severity", 20).lower()
        if severity not in VALID_SEVERITIES:
            raise PlanValidationError(f"Severidade invalida no achado {fid}.")
        if finding.get("file"):
            path = _validate_relative_path(finding["file"], f"findings[{index}].file")
            if known_files is not None and path not in known_files:
                raise PlanValidationError(f"Arquivo do achado nao consta no inventario: {path}")
        if "line" in finding and finding["line"] is not None:
            if not isinstance(finding["line"], int) or finding["line"] < 1:
                raise PlanValidationError(f"Linha invalida no achado {fid}.")

    action_ids = set()
    normalized_actions = []
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            raise PlanValidationError(f"Acao {index} nao e um objeto.")
        aid = _require_text(action.get("id"), f"actions[{index}].id", 80)
        if aid in action_ids:
            raise PlanValidationError(f"ID de acao duplicado: {aid}")
        action_ids.add(aid)
        _require_text(action.get("title"), f"actions[{index}].title", 500)
        _require_text(action.get("description"), f"actions[{index}].description", 4000)
        priority = _require_text(action.get("priority"), f"actions[{index}].priority", 20).lower()
        if priority not in VALID_PRIORITIES:
            raise PlanValidationError(f"Prioridade invalida na acao {aid}.")

        files = action.get("files", [])
        related = action.get("related_findings", [])
        depends = action.get("depends_on", [])
        criteria = action.get("acceptance_criteria", [])
        for field, value in (("files", files), ("related_findings", related),
                             ("depends_on", depends), ("acceptance_criteria", criteria)):
            if not isinstance(value, list) or len(value) > 100:
                raise PlanValidationError(f"{field} invalido na acao {aid}.")

        normalized_files = []
        for file_index, filename in enumerate(files):
            path = _validate_relative_path(filename, f"actions[{index}].files[{file_index}]")
            if known_files is not None and path not in known_files:
                raise PlanValidationError(f"Arquivo da acao nao consta no inventario: {path}")
            normalized_files.append(path)

        if any(not isinstance(fid, str) for fid in related):
            raise PlanValidationError(f"related_findings deve conter IDs de texto na acao {aid}.")
        if any(not isinstance(dep, str) for dep in depends):
            raise PlanValidationError(f"depends_on deve conter IDs de texto na acao {aid}.")
        for fid in related:
            if fid not in finding_ids:
                raise PlanValidationError(f"Achado relacionado inexistente na acao {aid}: {fid}")
        for criterion_index, criterion in enumerate(criteria):
            _require_text(criterion, f"actions[{index}].acceptance_criteria[{criterion_index}]", 1000)
        if not isinstance(action.get("requires_approval", True), bool):
            raise PlanValidationError(f"requires_approval precisa ser booleano na acao {aid}.")

        normalized_actions.append({**action, "files": normalized_files})

    for action in normalized_actions:
        for dependency in action.get("depends_on", []):
            if dependency not in action_ids:
                raise PlanValidationError(
                    f"Dependencia inexistente na acao {action['id']}: {dependency}"
                )
            if dependency == action["id"]:
                raise PlanValidationError(f"Acao nao pode depender de si mesma: {dependency}")

    # Detecta ciclos no grafo de dependencias.
    graph = {item["id"]: item.get("depends_on", []) for item in normalized_actions}
    visiting, visited = set(), set()

    def visit(node):
        if node in visiting:
            raise PlanValidationError("Ciclo detectado nas dependencias das acoes.")
        if node in visited:
            return
        visiting.add(node)
        for dependency in graph[node]:
            visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)

    for index, risk in enumerate(risks):
        if isinstance(risk, str):
            _require_text(risk, f"risks[{index}]", 1000)
        elif isinstance(risk, dict):
            _require_text(risk.get("description"), f"risks[{index}].description", 1000)
        else:
            raise PlanValidationError(f"Risco {index} possui formato invalido.")

    result = dict(plan)
    result["findings"] = findings
    result["actions"] = normalized_actions
    return result