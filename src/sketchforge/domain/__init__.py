"""Stable domain API for project, component, layout, interaction, and validation contracts."""

from sketchforge.domain.component import BBox, Component, ComponentType
from sketchforge.domain.interaction import Interaction
from sketchforge.domain.layout import LayoutSpec
from sketchforge.domain.project import DesignDocument, DesignProject, Page, PageRoute

__all__ = ["BBox", "Component", "ComponentType", "DesignDocument", "DesignProject", "Interaction", "LayoutSpec", "Page", "PageRoute"]
