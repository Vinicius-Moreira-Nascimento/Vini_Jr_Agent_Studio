from pathlib import Path

path = Path(r"C:\Users\pasta\Desktop\Vini_Jr_Agent_Studio\interface\code_review_panel.py")

source = path.read_text(encoding="utf-8-sig")

old_import = "QSplitter, QPlainTextEdit, QMessageBox"
new_import = "QSplitter, QPlainTextEdit, QTextEdit, QMessageBox"

old_selection = "QPlainTextEdit.ExtraSelection()"
new_selection = "QTextEdit.ExtraSelection()"

if old_import not in source:
    raise RuntimeError("Import esperado nao encontrado.")

if old_selection not in source:
    raise RuntimeError("Trecho ExtraSelection nao encontrado.")

source = source.replace(old_import, new_import, 1)
source = source.replace(old_selection, new_selection, 1)

path.write_text(source, encoding="utf-8")

print("Correcao ExtraSelection aplicada.")
