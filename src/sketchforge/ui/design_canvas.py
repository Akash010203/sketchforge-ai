"""The design canvas: the rendered SVG with selection, drag-to-move, resize and issue overlays.

The canvas draws the *same SVG* the exporter writes, so what you edit is what you export. Mouse
actions become controller commands only on release (one undo step per drag).
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtSvgWidgets import QGraphicsSvgItem
from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsScene, QGraphicsView

from sketchforge.application.app_controller import AppController
from sketchforge.design_ir.schema import BBox, Component
from sketchforge.domain.component import Style, Typography
from sketchforge.domain.component_types import ComponentType
from sketchforge.editor.design_commands import (
    AddComponentCommand,
    CompositeCommand,
    MoveCommand,
    RemoveComponentCommand,
)
from sketchforge.editor.selection import hit_test
from sketchforge.exceptions import SketchForgeError

HANDLE = 10.0  # resize handle edge in design px
DRAG_THRESHOLD = 3.0
SEVERITY_COLOR = {"error": "#dc2626", "warning": "#d97706", "info": "#2563eb"}


class DesignCanvas(QGraphicsView):
    status_message = Signal(str)
    selection_requested = Signal(object)  # list of ids

    def __init__(self, controller: AppController, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setBackgroundBrush(QBrush(QColor("#e2e8f0")))
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self._renderer: QSvgRenderer | None = None
        self._svg_item: QGraphicsSvgItem | None = None
        self._overlays: list[QGraphicsRectItem] = []
        self._show_issues = True
        self._fit_pending = True
        self._drag: dict | None = None
        self._ghost: QGraphicsRectItem | None = None
        self._snap_guides: list[QGraphicsRectItem] = []
        self._tool: ComponentType | None = None

    def set_tool(self, kind: ComponentType | None) -> None:
        self._tool = kind
        self.setCursor(Qt.CursorShape.CrossCursor if kind else Qt.CursorShape.ArrowCursor)

    # ------------------------------------------------------------------ public
    def set_show_issues(self, on: bool) -> None:
        self._show_issues = on
        self.refresh_overlays()

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802 (Qt API)
        """Paint the dark dotted studio board behind the editable design."""
        painter.fillRect(rect, QColor("#101014"))
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#31303a"))
        spacing = 24
        x0 = int(rect.left() // spacing) * spacing
        y0 = int(rect.top() // spacing) * spacing
        x1, y1 = int(rect.right()) + spacing, int(rect.bottom()) + spacing
        for x in range(x0, x1, spacing):
            for y in range(y0, y1, spacing):
                painter.drawEllipse(QPointF(x, y), 1.0, 1.0)
        painter.restore()

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802 (Qt API)
        if self.controller.has_project:
            return
        center = self.mapToScene(self.viewport().rect().center())
        card = QRectF(center.x() - 235, center.y() - 96, 470, 192)
        painter.save()
        painter.setPen(QPen(QColor("#ffffff22"), 1))
        painter.setBrush(QColor("#19191f"))
        painter.drawRoundedRect(card, 18, 18)
        painter.setPen(QColor("#d9ff5f"))
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        painter.drawText(QRectF(card.left() + 28, card.top() + 32, card.width() - 56, 22),
                         Qt.AlignmentFlag.AlignCenter, "YOUR CANVAS IS READY")
        painter.setPen(QColor("#f2f0f7"))
        painter.setFont(QFont("Segoe UI", 19, QFont.Weight.Bold))
        painter.drawText(QRectF(card.left() + 24, card.top() + 63, card.width() - 48, 34),
                         Qt.AlignmentFlag.AlignCenter, "Start with a sketch")
        painter.setPen(QColor("#a6a3ae"))
        painter.setFont(QFont("Segoe UI", 10))
        painter.drawText(QRectF(card.left() + 24, card.top() + 106, card.width() - 48, 45),
                         Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                         "Import a sketch or open a sample from File to create your first editable design.")
        painter.restore()

    def reload(self) -> None:
        """Re-render the current document (call after any document change)."""
        scene = self.scene()
        if not self.controller.has_project:
            scene.clear()
            self._svg_item, self._renderer, self._overlays, self._ghost = None, None, [], None
            return
        rendered = self.controller.render()
        self._renderer = QSvgRenderer(QByteArray(rendered.svg.encode("utf-8")), self)
        if self._svg_item is None or self._svg_item.scene() is not scene:
            scene.clear()
            self._overlays, self._ghost = [], None
            self._svg_item = QGraphicsSvgItem()
            self._svg_item.setZValue(0)
            scene.addItem(self._svg_item)
        self._svg_item.setSharedRenderer(self._renderer)
        page = self.controller.document.page
        self._svg_item.setScale(page.width / max(self._renderer.defaultSize().width(), 1))
        scene.setSceneRect(QRectF(-40, -40, page.width + 80, page.height + 80))
        self.refresh_overlays()
        if self._fit_pending:
            self.fit()
            self._fit_pending = False

    def fit(self) -> None:
        if self._svg_item is not None:
            self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def zoom(self, factor: float) -> None:
        self.scale(factor, factor)

    def refresh_overlays(self) -> None:
        scene = self.scene()
        for item in self._overlays:
            scene.removeItem(item)
        self._overlays = []
        for item in self._snap_guides:
            scene.removeItem(item)
        self._snap_guides = []
        if not self.controller.has_project:
            return
        doc = self.controller.document
        project = self.controller.project
        if self._show_issues and project.evaluation is not None:
            for issue in project.evaluation.issues:
                for cid in issue.component_ids:
                    comp = doc.get(cid)
                    if comp is not None:
                        self._add_rect(comp.bbox, SEVERITY_COLOR[issue.severity], dashed=True, width=1.6, z=5)
        for cid in project.selection.ids:
            comp = doc.get(cid)
            if comp is not None:
                self._add_rect(comp.bbox, "#2563eb", width=2.0, z=10)
                if cid == project.selection.primary:
                    b = comp.bbox
                    handle = QGraphicsRectItem(b.x2 - HANDLE / 2, b.y2 - HANDLE / 2, HANDLE, HANDLE)
                    handle.setBrush(QBrush(QColor("#ffffff")))
                    handle.setPen(QPen(QColor("#2563eb"), 1.5))
                    handle.setZValue(11)
                    scene.addItem(handle)
                    self._overlays.append(handle)

    def _add_rect(self, b, color: str, *, dashed: bool = False, width: float = 1.5, z: float = 5) -> QGraphicsRectItem:
        item = QGraphicsRectItem(b.x, b.y, b.w, b.h)
        pen = QPen(QColor(color), width)
        pen.setCosmetic(True)
        if dashed:
            pen.setStyle(Qt.PenStyle.DashLine)
        item.setPen(pen)
        item.setZValue(z)
        self.scene().addItem(item)
        self._overlays.append(item)
        return item

    # ------------------------------------------------------------------ mouse
    def _on_handle(self, comp: Component, pos: QPointF) -> bool:
        b = comp.bbox
        tol = min(12.0, max(HANDLE, 8.0 / max(self.transform().m11(), 1e-6)))
        return abs(pos.x() - b.x2) <= tol and abs(pos.y() - b.y2) <= tol

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if event.button() != Qt.MouseButton.LeftButton or not self.controller.has_project:
            return super().mousePressEvent(event)
        pos = self.mapToScene(event.position().toPoint())
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        if self._tool is not None:
            self._drag = {"mode": "create", "start": pos, "moved": False, "kind": self._tool}
            return
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            hit = hit_test(self.controller.document, pos.x(), pos.y())
            if hit:
                ids = list(self.controller.project.selection.ids)
                ids.remove(hit.id) if hit.id in ids else ids.append(hit.id)
                self.selection_requested.emit(ids)
            return
        doc = self.controller.document
        primary = self.controller.project.selection.primary
        current = doc.get(primary) if primary else None
        if current is not None and self._on_handle(current, pos):
            self._drag = {"mode": "resize", "id": current.id, "start": pos, "box": current.bbox, "moved": False}
            return
        hit = hit_test(doc, pos.x(), pos.y())
        if hit is None:
            self._drag = {"mode": "select", "start": pos, "moved": False}
            return
        if hit.id != primary:
            self.selection_requested.emit([hit.id])
        ids = self.controller.project.selection.ids if hit.id in self.controller.project.selection.ids else (hit.id,)
        ids = tuple(cid for cid in ids if not self._has_selected_ancestor(cid, set(ids)))
        boxes = {cid: self.controller.document.require(cid).bbox for cid in ids}
        self._drag = {"mode": "move", "id": hit.id, "ids": tuple(ids), "start": pos, "box": hit.bbox, "boxes": boxes, "moved": False}

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag is None:
            return super().mouseMoveEvent(event)
        pos = self.mapToScene(event.position().toPoint())
        d = self._drag
        dx, dy = pos.x() - d["start"].x(), pos.y() - d["start"].y()
        if not d["moved"] and (dx * dx + dy * dy) ** 0.5 < DRAG_THRESHOLD:
            return
        d["moved"] = True
        b = d.get("box")
        if d["mode"] == "move":
            dx, dy = self._snap_delta(d, dx, dy)
        if d["mode"] == "select":
            rect = QRectF(d["start"], pos).normalized()
        elif d["mode"] in ("move", "create"):
            rect = QRectF(b.x + dx, b.y + dy, b.w, b.h) if d["mode"] == "move" else QRectF(d["start"], pos).normalized()
        else:
            rect = QRectF(b.x, b.y, max(b.w + dx, 4.0), max(b.h + dy, 4.0))
        if self._ghost is None:
            self._ghost = QGraphicsRectItem()
            pen = QPen(QColor("#2563eb" if d["mode"] != "create" else "#d9ff5f"), 1.5, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            self._ghost.setPen(pen)
            self._ghost.setBrush(QBrush(QColor(37, 99, 235, 40)))
            self._ghost.setZValue(20)
            self.scene().addItem(self._ghost)
        self._ghost.setRect(rect)
        d["delta"] = (dx, dy)

    def _snap_delta(self, drag: dict, dx: float, dy: float) -> tuple[float, float]:
        """Snap moving bounds to nearby component edges/centres and show magnetic guides."""
        for item in self._snap_guides:
            self.scene().removeItem(item)
        self._snap_guides = []
        source = drag["box"]
        targets = [c.bbox for c in self.controller.document.components
                   if c.id not in drag["ids"] and c.id != self.controller.document.root_id and c.visible]
        tolerance = 7.0 / max(self.transform().m11(), 1e-6)
        xs = (source.x + dx, source.cx + dx, source.x2 + dx)
        ys = (source.y + dy, source.cy + dy, source.y2 + dy)
        x_candidates = [(abs(x - edge), edge - x, edge) for x in xs for box in targets for edge in (box.x, box.cx, box.x2)]
        y_candidates = [(abs(y - edge), edge - y, edge) for y in ys for box in targets for edge in (box.y, box.cy, box.y2)]
        snap_x = min(x_candidates, default=(tolerance + 1, 0, 0), key=lambda item: item[0])
        snap_y = min(y_candidates, default=(tolerance + 1, 0, 0), key=lambda item: item[0])
        if snap_x[0] <= tolerance:
            dx += snap_x[1]
            self._add_guide(True, snap_x[2])
        if snap_y[0] <= tolerance:
            dy += snap_y[1]
            self._add_guide(False, snap_y[2])
        return dx, dy

    def _add_guide(self, vertical: bool, coordinate: float) -> None:
        page = self.controller.document.page
        item = QGraphicsRectItem(coordinate - .5 if vertical else 0,
                                 0 if vertical else coordinate - .5,
                                 1 if vertical else page.width,
                                 page.height if vertical else 1)
        pen = QPen(QColor("#d9ff5f"), 1)
        pen.setCosmetic(True)
        item.setPen(pen)
        item.setBrush(QBrush(QColor("#d9ff5f")))
        item.setZValue(19)
        self.scene().addItem(item)
        self._snap_guides.append(item)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        d, self._drag = self._drag, None
        if self._ghost is not None:
            self.scene().removeItem(self._ghost)
            self._ghost = None
        for item in self._snap_guides:
            self.scene().removeItem(item)
        self._snap_guides = []
        if d is None:
            return super().mouseReleaseEvent(event)
        if d["mode"] == "select":
            if d["moved"]:
                p = self.mapToScene(event.position().toPoint())
                box = QRectF(d["start"], p).normalized()
                ids = [c.id for c in self.controller.document.components
                       if c.id != self.controller.document.root_id and c.visible
                       and c.bbox.x <= box.right() and c.bbox.x2 >= box.left()
                       and c.bbox.y <= box.bottom() and c.bbox.y2 >= box.top()]
                self.selection_requested.emit(ids)
            else:
                self.selection_requested.emit([])
            return
        if not d["moved"]:
            return super().mouseReleaseEvent(event)
        dx, dy = d["delta"]
        try:
            if d["mode"] == "move":
                commands = [__import__('sketchforge.editor.design_commands', fromlist=['MoveCommand']).MoveCommand(cid, round(dx, 1), round(dy, 1)) for cid in d["ids"]]
                self.controller.execute(CompositeCommand(commands, f"move {len(commands)} component(s)"))
            elif d["mode"] == "resize":
                b = d["box"]
                self.controller.resize_component(d["id"], round(max(b.w + dx, 4.0), 1), round(max(b.h + dy, 4.0), 1))
            else:
                p = self.mapToScene(event.position().toPoint())
                rect = QRectF(d["start"], p).normalized()
                if rect.width() < 8 or rect.height() < 8:
                    rect.setSize(rect.size().expandedTo(__import__('PySide6.QtCore', fromlist=['QSizeF']).QSizeF(120, 40)))
                self._add_component(d["kind"], rect)
        except SketchForgeError as exc:
            self.status_message.emit(str(exc))
            self.refresh_overlays()

    def _add_component(self, kind: ComponentType, rect: QRectF) -> None:
        doc = self.controller.document
        idx = 1
        while doc.get(f"{kind.value}-{idx}") is not None:
            idx += 1
        box = BBox(x=rect.x(), y=rect.y(), w=max(8, rect.width()), h=max(8, rect.height()))
        text = {ComponentType.BUTTON: "Button", ComponentType.INPUT: "Enter text", ComponentType.TEXT: "Text", ComponentType.HEADING: "Heading"}.get(kind)
        comp = Component(id=f"{kind.value}-{idx}", type=kind, parent_id=doc.root_id, bbox=box, text=text,
                         style=Style(fill="#2563eb" if kind is ComponentType.BUTTON else "transparent"),
                         typography=Typography() if kind in (ComponentType.BUTTON, ComponentType.INPUT, ComponentType.TEXT, ComponentType.HEADING) else None)
        self.controller.execute(AddComponentCommand(comp))
        self.selection_requested.emit([comp.id])

    def _has_selected_ancestor(self, component_id: str, selected: set[str]) -> bool:
        doc = self.controller.document
        parent = doc.get(doc.require(component_id).parent_id or "")
        while parent is not None and parent.id != doc.root_id:
            if parent.id in selected:
                return True
            parent = doc.get(parent.parent_id or "")
        return False

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        mime = event.mimeData()
        image_paths = [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]
        has_image = any(path.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")) for path in image_paths)
        if has_image or (mime.hasFormat("application/x-sketchforge-component") and self.controller.has_project):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        self.dragEnterEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        image_paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        image_path = next((path for path in image_paths
                           if path.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"))), None)
        if image_path:
            self.status_message.emit(f"Importing sketch: {image_path}")
            self.controller.import_sketch_async(image_path)
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        try:
            kind = ComponentType(bytes(event.mimeData().data("application/x-sketchforge-component")).decode())
            pos = self.mapToScene(event.position().toPoint())
            size = {ComponentType.BUTTON: (150, 44), ComponentType.INPUT: (220, 44),
                    ComponentType.TEXT: (160, 36), ComponentType.HEADING: (240, 52),
                    ComponentType.CARD: (240, 150), ComponentType.CONTAINER: (280, 180)}[kind]
            self._add_component(kind, QRectF(pos.x(), pos.y(), *size))
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        except (ValueError, SketchForgeError) as exc:
            self.status_message.emit(str(exc))
            event.ignore()

    def wheelEvent(self, event) -> None:  # noqa: N802
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom(1.15 if event.angleDelta().y() > 0 else 1 / 1.15)
            event.accept()
        else:
            super().wheelEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if not self.controller.has_project:
            return super().keyPressEvent(event)
        ids = list(self.controller.project.selection.ids)
        if event.key() == Qt.Key.Key_Escape:
            self._tool = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.selection_requested.emit([])
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and ids:
            selected = set(ids)
            roots = []
            for cid in ids:
                comp = self.controller.document.require(cid)
                parent = self.controller.document.get(comp.parent_id or "")
                while parent is not None and parent.id != self.controller.document.root_id and parent.id not in selected:
                    parent = self.controller.document.get(parent.parent_id or "")
                if parent is None or parent.id == self.controller.document.root_id:
                    roots.append(comp.id)
            try:
                self.controller.execute(CompositeCommand([RemoveComponentCommand(cid) for cid in roots], "delete selection"))
            except SketchForgeError as exc:
                self.status_message.emit(str(exc))
            event.accept()
            return
        directions = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0),
                      Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1)}
        if event.key() in directions and ids:
            dx, dy = directions[event.key()]
            step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            selected = set(ids)
            doc = self.controller.document
            roots = []
            for cid in ids:
                parent = doc.get(doc.require(cid).parent_id or "")
                while parent is not None and parent.id != doc.root_id and parent.id not in selected:
                    parent = doc.get(parent.parent_id or "")
                if parent is None or parent.id == doc.root_id:
                    roots.append(cid)
            try:
                self.controller.execute(CompositeCommand(
                    [MoveCommand(cid, dx * step, dy * step) for cid in roots], "nudge selection"))
            except SketchForgeError as exc:
                self.status_message.emit(str(exc))
            event.accept()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._fit_pending is False and self._svg_item is not None and self.transform().isIdentity():
            self.fit()
