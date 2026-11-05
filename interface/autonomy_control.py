from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QComboBox
from PySide6.QtCore import Signal

class AutonomyControl(QWidget):

    mode_changed = Signal(str)

    def __init__(self):
        super().__init__()

        layout = QHBoxLayout(self)

        layout.addWidget(QLabel("Autonomia:"))

        self.mode = QComboBox()

        self.mode.addItem("Manual", "manual")
        self.mode.addItem("Supervisionado", "supervised")
        self.mode.addItem("Autonomo", "autonomous")

        self.mode.currentIndexChanged.connect(
            self.on_mode_changed
        )

        layout.addWidget(self.mode)

    def on_mode_changed(self):
        self.mode_changed.emit(
            self.mode.currentData()
        )
