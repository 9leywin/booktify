"""Мелкие виджеты: зона перетаскивания, кольцо прогресса, обложка."""

from __future__ import annotations

import os

from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import theme

ALLOWED = (".epub", ".fb2", ".pdf", ".zip")


class DropZone(QFrame):
    """Большая пунктирная рамка: сюда кидают книгу или кликают, чтобы выбрать."""

    fileChosen = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(300)
        self.setCursor(Qt.PointingHandCursor)
        self.setProperty("dragging", False)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(10)

        icon = QLabel("📖")
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet("font-size: 56px;")
        layout.addWidget(icon)

        title = QLabel("Перетащи сюда книгу")
        title.setObjectName("H1")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        hint = QLabel("EPUB · FB2 · PDF с текстом")
        hint.setObjectName("Subtitle")
        hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(hint)

        button = QLabel()
        button.setObjectName("DropLink")
        button.setAlignment(Qt.AlignCenter)
        button.setStyleSheet("font-size: 16px; margin-top: 8px;")
        button.linkActivated.connect(self._browse)
        self._link = button
        layout.addWidget(button)
        self.refresh_theme()

    def refresh_theme(self) -> None:
        self._link.setText(
            f'<a href="#" style="color:{theme.PRIMARY}; text-decoration:none;">Выбрать файл</a>'
        )

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Выбери книгу", "", "Книги (*.epub *.fb2 *.pdf *.zip)"
        )
        if path:
            self.fileChosen.emit(path)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._browse()
        super().mousePressEvent(event)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_dragging(True)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._set_dragging(False)

    def dropEvent(self, event) -> None:  # noqa: N802
        self._set_dragging(False)
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(ALLOWED):
                self.fileChosen.emit(path)
                event.acceptProposedAction()
                return

    def _set_dragging(self, value: bool) -> None:
        self.setProperty("dragging", value)
        self.style().unpolish(self)
        self.style().polish(self)


class ProgressRing(QWidget):
    """Кольцо прогресса с процентом внутри. Крупное — его видно издалека."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._value = 0
        self.setMinimumSize(220, 220)

    def set_value(self, value: int) -> None:
        self._value = max(0, min(100, int(value)))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height()) - 16
        rect = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)

        pen = QPen(QColor(theme.RING_BG), 14, Qt.SolidLine, Qt.RoundCap)
        painter.setPen(pen)
        painter.drawArc(rect, 0, 360 * 16)

        pen.setColor(QColor(theme.PRIMARY))
        painter.setPen(pen)
        painter.drawArc(rect, 90 * 16, -int(360 * 16 * self._value / 100))

        font = QFont(self.font())
        font.setPointSize(30)
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(theme.TEXT))
        painter.drawText(rect, Qt.AlignCenter, f"{self._value}%")


class CoverView(QLabel):
    """Обложка книги или аккуратная заглушка с названием."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(150, 220)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("border-radius: 10px; background: #DDE4F2;")

    def set_book(self, title: str, data: bytes | None) -> None:
        pixmap = QPixmap()
        # Совсем маленькие «картинки» — это заглушки из демо-файлов, а не обложки.
        if data and len(data) > 1024 and pixmap.loadFromData(data):
            self.setPixmap(pixmap.scaled(self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
            self.setScaledContents(True)
            return

        placeholder = QPixmap(self.size())
        placeholder.fill(Qt.transparent)
        painter = QPainter(placeholder)
        painter.setRenderHint(QPainter.Antialiasing)
        gradient = QLinearGradient(0, 0, self.width(), self.height())
        gradient.setColorAt(0, QColor("#3B5BA5"))
        gradient.setColorAt(1, QColor("#1E2A4A"))
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self.width(), self.height()), 10, 10)
        painter.fillPath(path, gradient)
        painter.setPen(QColor("#FFFFFF"))
        font = QFont(self.font())
        font.setPointSize(11)
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        painter.drawText(
            QRectF(12, 20, self.width() - 24, self.height() - 40),
            Qt.AlignCenter | Qt.TextWordWrap,
            title[:120],
        )
        painter.end()
        self.setPixmap(placeholder)


def human_size(path: str) -> str:
    try:
        size = os.path.getsize(path)
    except OSError:
        return ""
    if size > 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} МБ"
    return f"{max(1, size // 1024)} КБ"


class RecentsPanel(QWidget):
    """Свёрнутый список недавних книг с плавным раскрытием."""

    fileChosen = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.header = QToolButton()
        self.header.setObjectName("RecentsHeader")
        self.header.setCheckable(True)
        self.header.setArrowType(Qt.RightArrow)
        self.header.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.header.setText("Недавние книги")
        self.header.setCursor(Qt.PointingHandCursor)
        self.header.clicked.connect(self._toggle)
        layout.addWidget(self.header, alignment=Qt.AlignLeft)

        self.body = QWidget()
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.itemClicked.connect(self._open_item)
        body_layout.addWidget(self.list)
        self.body.setMaximumHeight(0)
        layout.addWidget(self.body)

        self._anim = QPropertyAnimation(self.body, b"maximumHeight", self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.setVisible(False)

    # ------------------------------------------------------------------ данные

    def set_recents(self, paths: list[str]) -> None:
        self.list.clear()
        for path in paths[:6]:
            if not os.path.exists(path):
                continue
            item = QListWidgetItem(f"{os.path.basename(path)}   ·   {human_size(path)}")
            item.setData(Qt.UserRole, path)
            self.list.addItem(item)

        has_items = self.list.count() > 0
        self.setVisible(has_items)
        self.header.setText(f"Недавние книги · {self.list.count()}" if has_items else "Недавние книги")
        if not has_items:
            self._collapse(immediate=True)

    def _open_item(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.UserRole)
        if path:
            self.fileChosen.emit(path)

    # --------------------------------------------------------------- анимация

    def _toggle(self, checked: bool) -> None:
        if checked:
            self._expand()
        else:
            self._collapse()

    def _target_height(self) -> int:
        count = self.list.count()
        if not count:
            return 0
        row = self.list.sizeHintForRow(0) + 8
        return min(row * count + 8, 190)

    def _expand(self) -> None:
        self.header.setArrowType(Qt.DownArrow)
        self._animate(self._target_height())

    def _collapse(self, immediate: bool = False) -> None:
        self.header.setArrowType(Qt.RightArrow)
        self.header.setChecked(False)
        if immediate:
            self.body.setMaximumHeight(0)
            return
        self._animate(0)

    def _animate(self, target: int) -> None:
        self._anim.stop()
        self._anim.setStartValue(self.body.maximumHeight())
        self._anim.setEndValue(target)
        self._anim.start()
