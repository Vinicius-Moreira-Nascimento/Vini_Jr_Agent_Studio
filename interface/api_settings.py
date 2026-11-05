from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QLineEdit,
    QComboBox, QPushButton, QMessageBox
)
import json
import os

class APISettingsDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Configuracao OpenAI")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("OpenAI API Key"))

        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("Cole sua API Key aqui")
        layout.addWidget(self.api_key)

        self.show_key = QPushButton("Mostrar / ocultar chave")
        self.show_key.clicked.connect(self.toggle_key)
        layout.addWidget(self.show_key)

        layout.addWidget(QLabel("Modelo OpenAI"))

        self.model = QComboBox()
        self.model.addItems([
            "gpt-4.1-mini",
            "gpt-4.1",
            "gpt-4o-mini",
            "gpt-4o",
            "o3",
            "o4-mini"
        ])

        layout.addWidget(self.model)

        self.save = QPushButton("Salvar configuracoes")
        self.save.clicked.connect(self.save_settings)
        layout.addWidget(self.save)

        self.load_settings()

    def toggle_key(self):
        mode = self.api_key.echoMode()

        if mode == QLineEdit.EchoMode.Password:
            self.api_key.setEchoMode(QLineEdit.EchoMode.Normal)
        else:
            self.api_key.setEchoMode(QLineEdit.EchoMode.Password)

    def load_settings(self):
        path = os.path.join("config", "providers.json")

        if os.path.exists(path):
            with open(path, "r", encoding="utf-8-sig") as file:
                data = json.load(file)

            self.api_key.setText(data.get("openai", {}).get("api_key", ""))

        path = os.path.join("config", "settings.json")

        if os.path.exists(path):
            with open(path, "r", encoding="utf-8-sig") as file:
                data = json.load(file)

            model = data.get("model", "gpt-4.1-mini")
            index = self.model.findText(model)

            if index >= 0:
                self.model.setCurrentIndex(index)

    def save_settings(self):

        path = os.path.join("config", "providers.json")

        with open(path, "r", encoding="utf-8-sig") as file:
            data = json.load(file)

        data["openai"]["api_key"] = self.api_key.text().strip()

        with open(path, "w", encoding="utf-8-sig") as file:
            json.dump(data, file, indent=4)

        path = os.path.join("config", "settings.json")

        with open(path, "r", encoding="utf-8-sig") as file:
            settings = json.load(file)

        settings["model"] = self.model.currentText()

        with open(path, "w", encoding="utf-8-sig") as file:
            json.dump(settings, file, indent=4)

        QMessageBox.information(
            self,
            "VINI_JR",
            "Configuracoes salvas com sucesso."
        )

        self.accept()
