"""Recognized component kinds shared by component and layout contracts."""

from enum import Enum


class ComponentType(str, Enum):
    PAGE = "page"
    CONTAINER = "container"
    HEADER = "header"
    SIDEBAR = "sidebar"
    FOOTER = "footer"
    CARD = "card"
    BUTTON = "button"
    INPUT = "input"
    TEXT = "text"
    HEADING = "heading"
    IMAGE = "image"
    DIVIDER = "divider"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    UNKNOWN = "unknown"
