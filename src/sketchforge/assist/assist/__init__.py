"""Natural-language design edits.

A sentence becomes an :class:`~sketchforge.assist.edit_plan.EditPlan` (a small, typed, allowlisted
list of operations), the plan is validated against the document, and only then does it become an
ordinary undoable editor command. Two planners produce plans: a local rule-based parser
(``local_parser``, the baseline, no network) and a model planner (``model_planner``) that uses any
:class:`~sketchforge.integrations.provider_interface.ModelProvider`.
"""
