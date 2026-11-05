import re
from pathlib import Path


INTEGER_TYPES = {
    "uint8_t", "uint16_t", "uint32_t", "uint64_t",
    "int8_t", "int16_t", "int32_t", "int64_t",
    "unsigned char", "unsigned short", "unsigned int",
    "signed char", "short", "int", "long"
}

FORMAT_CALL = re.compile(
    r'\b(?:printf|fprintf|sprintf|snprintf|'
    r'vprintf|uart_log)\s*\(\s*"([^"]*)"([^;]*)'
)

DECLARATION = re.compile(
    r'\b(' + '|'.join(
        re.escape(t) for t in sorted(
            INTEGER_TYPES, key=len, reverse=True
        )
    ) + r')\s+([A-Za-z_]\w*)\b'
)

UNSAFE_FUNCTIONS = {
    "sprintf": (
        "Uso de sprintf",
        "sprintf nao recebe limite de tamanho do destino. "
        "Avalie snprintf e valide o tamanho do buffer."
    ),
    "strcpy": (
        "Uso de strcpy",
        "strcpy nao verifica o tamanho do destino. "
        "Avalie uma alternativa com limite explicito."
    ),
    "strcat": (
        "Uso de strcat",
        "strcat nao verifica o espaco restante no destino. "
        "Avalie uma alternativa com limite explicito."
    )
}


def analyze_c_file(filename, content):
    findings = []

    declarations = {}

    for line_number, line in enumerate(content.splitlines(), 1):
        for match in DECLARATION.finditer(line):
            declarations[match.group(2)] = {
                "type": match.group(1),
                "line": line_number
            }

    lines = content.splitlines()

    for line_number, line in enumerate(lines, 1):

        # Verificacao de especificadores de formato.
        for match in FORMAT_CALL.finditer(line):
            format_string = match.group(1)
            arguments = match.group(2)

            if "%ld" in format_string:
                for variable, declaration in declarations.items():
                    if (
                        declaration["type"] in {
                            "uint8_t", "uint16_t", "uint32_t",
                            "int8_t", "int16_t", "int32_t"
                        }
                        and re.search(
                            r"\b" + re.escape(variable) + r"\b",
                            arguments
                        )
                    ):
                        findings.append({
                            "file": filename,
                            "line": line_number,
                            "rule": "C_FORMAT_001",
                            "severity": "warning",
                            "title": "Possivel incompatibilidade de formato",
                            "evidence": line.strip(),
                            "declaration": (
                                f"{declaration['type']} {variable} "
                                f"na linha {declaration['line']}"
                            ),
                            "recommendation": (
                                "Confira o tipo promovido passado "
                                "pela lista variadica. Considere "
                                "usar PRIu16/PRId16 com inttypes.h "
                                "ou fazer cast explicito para o "
                                "tipo esperado pelo especificador."
                            ),
                            "confidence": "alta"
                        })

        # Funcoes que exigem cuidado com limites de memoria.
        for function, details in UNSAFE_FUNCTIONS.items():
            if re.search(r"\b" + function + r"\s*\(", line):
                findings.append({
                    "file": filename,
                    "line": line_number,
                    "rule": "C_BUFFER_001",
                    "severity": "warning",
                    "title": details[0],
                    "evidence": line.strip(),
                    "recommendation": details[1],
                    "confidence": "media"
                })

        # Marcadores de trabalho pendente.
        if re.search(r"\b(TODO|FIXME)\b", line):
            findings.append({
                "file": filename,
                "line": line_number,
                "rule": "C_TODO_001",
                "severity": "info",
                "title": "Marcador de trabalho pendente",
                "evidence": line.strip(),
                "recommendation": (
                    "Verifique se a implementacao pendente "
                    "precisa ser concluida."
                ),
                "confidence": "alta"
            })

    return findings


def analyze_sources(files):
    findings = []
    analyzed_files = 0

    for filename, content in files.items():
        extension = Path(filename).suffix.lower()

        if extension not in {
            ".c", ".h", ".cpp", ".hpp", ".cc", ".hh"
        }:
            continue

        if not isinstance(content, str):
            continue

        analyzed_files += 1
        findings.extend(analyze_c_file(filename, content))

    counts = {
        "error": 0,
        "warning": 0,
        "info": 0
    }

    for finding in findings:
        severity = finding["severity"]
        counts[severity] = counts.get(severity, 0) + 1

    return {
        "files_analyzed": analyzed_files,
        "total_findings": len(findings),
        "counts": counts,
        "findings": findings,
        "notice": (
            "Analise estatica heuristica. Os achados devem "
            "ser revisados antes de qualquer alteracao."
        )
    }