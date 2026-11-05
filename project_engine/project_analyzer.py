from pathlib import Path

from project_engine.project_context import build_project_context


class ProjectAnalyzer:
    """Consolida os analisadores locais sem modificar o projeto analisado."""

    def __init__(self, max_files=200, max_total_chars=60000):
        self.max_files = max_files
        self.max_total_chars = max_total_chars

    def analyze(self, project_root):
        root = Path(project_root).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise NotADirectoryError(str(root))

        context = build_project_context(
            root,
            max_files=self.max_files,
            max_total_chars=self.max_total_chars,
        )
        firmware = context.get("analysis", {})
        static = context.get("static_analysis", {})

        return {
            "project_path": str(root),
            "total_files_found": int(context.get("total_files_found", 0)),
            "files_read": int(context.get("files_read", 0)),
            "extensions": context.get("extensions", {}),
            "inventory": context.get("inventory", []),
            "firmware_analysis": firmware,
            "static_analysis": static,
            "limitations": [
                "A analise estatica e heuristica e nao substitui compilacao ou revisao humana.",
                "O inventario e a leitura respeitam os limites configurados.",
                "A ausencia de achados nao comprova ausencia de defeitos.",
            ],
        }

    @staticmethod
    def build_planning_input(analysis, objective="Analisar e planejar melhorias"):
        """Remove o codigo-fonte bruto e prepara dados compactos para a IA."""
        inventory = analysis.get("inventory", [])
        static = analysis.get("static_analysis", {})
        firmware = analysis.get("firmware_analysis", {})

        return {
            "project_path": analysis.get("project_path", ""),
            "objective": str(objective).strip() or "Analisar o projeto",
            "total_files_found": analysis.get("total_files_found", 0),
            "files_read": analysis.get("files_read", 0),
            "extensions": analysis.get("extensions", {}),
            "inventory": [
                {
                    "path": item.get("path", ""),
                    "extension": item.get("extension", ""),
                    "size": item.get("size", 0),
                }
                for item in inventory
                if isinstance(item, dict)
            ],
            "firmware_analysis": {
                "files_analyzed": firmware.get("files_analyzed", 0),
                "task_apis": firmware.get("task_apis", {}),
                "functions": firmware.get("functions", [])[:300],
                "includes": firmware.get("includes", [])[:300],
                "peripherals": firmware.get("peripherals", {}),
                "todos": firmware.get("todos", [])[:100],
            },
            "static_analysis": {
                "files_analyzed": static.get("files_analyzed", 0),
                "total_findings": static.get("total_findings", 0),
                "counts": static.get("counts", {}),
                "findings": static.get("findings", [])[:200],
                "notice": static.get("notice", ""),
            },
            "limitations": analysis.get("limitations", []),
        }