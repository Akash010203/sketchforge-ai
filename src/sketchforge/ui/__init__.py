"""PySide6 desktop UI. Everything here is a thin view over :class:`AppController`.

The UI never touches the document except through controller methods, so each user action is an
undoable command and every view stays in sync through controller events.
"""
