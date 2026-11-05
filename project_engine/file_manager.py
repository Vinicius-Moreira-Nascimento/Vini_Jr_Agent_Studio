from pathlib import Path


def validate_project(root):
    path = Path(root).expanduser().resolve()

    if not path.exists() or not path.is_dir():
        raise ValueError("Diretorio do projeto inexistente.")

    return path


def safe_resolve(root, relative_path):
    base = validate_project(root)
    target = (base / relative_path).resolve()

    if not target.is_relative_to(base):
        raise ValueError("Acesso fora do diretorio do projeto bloqueado.")

    if not target.is_file():
        raise FileNotFoundError(str(target))

    return target