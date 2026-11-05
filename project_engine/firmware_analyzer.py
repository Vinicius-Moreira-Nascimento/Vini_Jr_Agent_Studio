import re
from collections import Counter

TASK_PATTERN = re.compile(
    r"\b(xTaskCreate(?:PinnedToCore|Static)?|"
    r"xQueueCreate|xSemaphoreCreate\w*|"
    r"xTimerCreate|xEventGroupCreate)\s*\("
)

FUNCTION_PATTERN = re.compile(
    r"(?m)^\s*(?:static\s+)?"
    r"(?:[\w]+\s+|\*+\s*)+"
    r"([A-Za-z_]\w*)\s*\([^;{}]*\)\s*\{"
)

PERIPHERALS = {
    "UART": r"\buart_\w+",
    "I2C": r"\bi2c_\w+",
    "SPI": r"\bspi_\w+",
    "GPIO": r"\bgpio_\w+",
    "ADC": r"\badc_\w+",
    "LEDC": r"\bledc_\w+",
    "Wi-Fi": r"\b(?:esp_wifi|wifi)_\w+",
    "ESP-NOW": r"\besp_now_\w+",
    "CAN/TWAI": r"\btwai_\w+"
}


def analyze_firmware(files):
    task_calls = Counter()
    peripheral_calls = {
        name: Counter() for name in PERIPHERALS
    }

    functions = set()
    includes = set()
    todos = []
    analyzed = 0

    for filename, content in files.items():
        if not isinstance(content, str):
            continue

        analyzed += 1

        for match in TASK_PATTERN.finditer(content):
            task_calls[match.group(1)] += 1

        for match in FUNCTION_PATTERN.finditer(content):
            functions.add(match.group(1))

        for match in re.findall(
            r'(?m)^\s*#\s*include\s*[<"]([^>"]+)[>"]',
            content
        ):
            includes.add(match)

        for line_number, line in enumerate(
            content.splitlines(), start=1
        ):
            if "TODO" in line or "FIXME" in line:
                todos.append({
                    "file": filename,
                    "line": line_number,
                    "text": line.strip()
                })

        for peripheral, pattern in PERIPHERALS.items():
            matches = re.findall(pattern, content)
            peripheral_calls[peripheral].update(matches)

    return {
        "files_analyzed": analyzed,
        "task_apis": dict(task_calls),
        "functions": sorted(functions),
        "includes": sorted(includes),
        "peripherals": {
            name: dict(calls)
            for name, calls in peripheral_calls.items()
            if calls
        },
        "todos": todos
    }