from pathlib import Path
from project_engine.file_manager import validate_project

SUPPORTED_EXTENSIONS = {
    ".c", ".h", ".cpp", ".hpp", ".cc", ".hh",
    ".s", ".py", ".cmake", ".md", ".yml", ".yaml",
    ".csv", ".mk"
}

SPECIAL_FILES = {
    "cmakelists.txt",
    "kconfig",
    "kconfig.projbuild",
    "makefile",
    "component.mk",
    "idf_component.yml",
    "sdkconfig.defaults",
    "partitions.csv",
    "readme",
    "readme.md"
}

IGNORED_DIRS = {
    ".git", ".venv", "venv", "__pycache__",
    "build", "dist", "out", ".idea", ".vscode",
    "node_modules"
}

MAX_FILE_SIZE = 512 * 1024


def scan_project(root, max_files=2000):
    base = validate_project(root)
    results = []

    for current, dirs, files in __import__("os").walk(base):
        dirs[:] = sorted(
            d for d in dirs
            if d.lower() not in IGNORED_DIRS
        )

        for filename in sorted(files):
            path = Path(current) / filename
            extension = path.suffix.lower()

            if extension not in SUPPORTED_EXTENSIONS:
                if filename.lower() not in SPECIAL_FILES:
                    continue

            if filename.lower() in {
                ".env", "providers.json", "credentials.json",
                "secrets.json"
            }:
                continue

            try:
                size = path.stat().st_size

                if size > MAX_FILE_SIZE:
                    continue

                relative = path.relative_to(base).as_posix()

                results.append({
                    "path": relative,
                    "name": filename,
                    "extension": extension,
                    "size": size
                })

                if len(results) >= max_files:
                    return results

            except OSError:
                continue

    return results