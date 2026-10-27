"""Rollback points: restore a document exactly to an earlier state."""

from __future__ import annotations

from sketchforge.design_ir.schema import DesignDocument
from sketchforge.design_ir.serialization import document_hash
from sketchforge.exceptions import RepairError


class RollbackPoint:
    """A snapshot plus its hash, so a restore can be *verified*, not assumed."""

    def __init__(self, doc: DesignDocument) -> None:
        self.snapshot = doc.snapshot()
        self.hash = document_hash(doc)

    def matches(self, doc: DesignDocument) -> bool:
        return document_hash(doc) == self.hash

    def restore(self, doc: DesignDocument) -> None:
        doc.restore(self.snapshot)
        if not self.matches(doc):
            raise RepairError("rollback did not reproduce the original document")
