from project_engine.file_manager import safe_resolve
from project_engine.project_scanner import scan_project


MAX_FILE_CHARS = 150000
MAX_TOTAL_CHARS = 500000


def read_file(root, relative_path):
    path = safe_resolve(root, relative_path)

    try:
        content = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        content = path.read_text(encoding="cp1252")

    if len(content) > MAX_FILE_CHARS:
        content = content[:MAX_FILE_CHARS]
        content += "\n\n[ARQUIVO TRUNCADO PELO LIMITE DE LEITURA]"

    return content


def read_project_sources(root, max_files=200, max_total_chars=500000):
    inventory = scan_project(root, max_files=max_files)
    contents = {}
    total = 0

    for item in inventory:
        relative = item["path"]

        try:
            content = read_file(root, relative)

            remaining = max_total_chars - total

            if remaining <= 0:
                break

            if len(content) > remaining:
                content = content[:remaining]

            contents[relative] = content
            total += len(content)

        except (OSError, ValueError) as error:
            contents[relative] = (
                "[ERRO DE LEITURA] " + str(error)
            )

    return contents