from pathlib import Path
import shutil

root = Path(r"C:\Users\pasta\Desktop\Vini_Jr_Agent_Studio")

main_path = root / "interface" / "main_window.py"
source = main_path.read_text(encoding="utf-8-sig")

# Backup antes de modificar.

backup = main_path.with_name("main_window.py.backup_code_review")

if not backup.exists():
    shutil.copy2(main_path, backup)

# Importar novo painel.

import_line = "from interface.code_review_panel import CodeReviewPanel"

if import_line not in source:
    source = source.replace(
        "from interface.chat_panel import ChatPanel",
        "from interface.chat_panel import ChatPanel\n" + import_line
    )

# Localizar bloco de integracao do Embedded Development.

start_marker = "        self.embedded = EmbeddedPanel()"
end_marker = "        self.load_autonomy_mode()"

start = source.find(start_marker)

if start < 0:
    raise RuntimeError(
        "Nao foi localizado o inicio da integracao do EmbeddedPanel."
    )

end = source.find(end_marker, start)

if end < 0:
    raise RuntimeError(
        "Nao foi localizado o final da inicializacao da janela."
    )

new_block = '''        self.embedded = EmbeddedPanel()

        self.chat.set_project_path_provider(
            lambda: self.embedded.project_path.text().strip()
        )

        self.tabs.addTab(
            self.embedded,
            "Embedded Development"
        )

        self.code_review = CodeReviewPanel()

        self.code_review.set_project_path_provider(
            lambda: self.embedded.project_path.text().strip()
        )

        self.tabs.addTab(
            self.code_review,
            "Code Review"
        )

'''

source = source[:start] + new_block + source[end:]

main_path.write_text(source, encoding="utf-8")

print("MainWindow integrado com sucesso.")
print("Backup:", backup)
