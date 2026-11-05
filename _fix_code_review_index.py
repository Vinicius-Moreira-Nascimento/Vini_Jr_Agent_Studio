from pathlib import Path

path = Path(r"C:\Users\pasta\Desktop\Vini_Jr_Agent_Studio\interface\code_review_panel.py")

source = path.read_text(encoding="utf-8-sig")

old = "for index, finding in enumerate(self.findings, 1):"
new = "for index, finding in enumerate(self.findings):"

if old not in source:
    raise RuntimeError(
        "Trecho esperado nao encontrado. Nenhuma alteracao foi feita."
    )

source = source.replace(old, new, 1)

path.write_text(source, encoding="utf-8")

print("Correcao aplicada: indices agora comecam em zero.")
