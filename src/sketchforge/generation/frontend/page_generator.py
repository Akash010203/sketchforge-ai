"""Page generator: converts AppSpec pages into React + TypeScript page components."""
from __future__ import annotations

from sketchforge.generation.app_specification import PageSpec, FieldSpec, ActionSpec


def generate_page(page: PageSpec, app_name: str = "App") -> str:
    """Generate a React page component from a PageSpec."""
    imports = _build_imports(page)
    form_state = _build_form_state(page)
    handlers = _build_handlers(page)
    jsx = _build_jsx(page, app_name)

    pascal_name = _pascal(page.name)
    return f'''\
import React, {{ useState }} from "react";
{imports}
import styles from "./../styles/{page.name.lower()}.module.css";

{form_state}

const {pascal_name}: React.FC = () => {{
{handlers}
  return (
    <div className={{styles.page}}>
{jsx}
    </div>
  );
}};

export default {pascal_name};
'''


def _build_imports(page: PageSpec) -> str:
    lines: list[str] = []
    seen: set[str] = set()

    # Always import Link for navigation actions
    if any(a.action == "navigate" for f in page.forms for a in page.actions):
        lines.append('import { useNavigate } from "react-router-dom";')

    # Import UI components based on component types present
    types_present = {c.get("type", "").lower() for c in page.components}
    component_map = {
        "button": "Button",
        "input": "Input",
        "card": "Card",
        "header": "Header",
        "nav": "Nav",
        "text": "Text",
        "heading": "Text",
        "image": "Image",
        "checkbox": "Checkbox",
        "divider": "Divider",
    }
    for t, comp in component_map.items():
        if t in types_present and comp not in seen:
            lines.append(f'import {comp} from "./../components/{comp}";')
            seen.add(comp)

    # Always import Button for form submit actions
    if page.forms and "Button" not in seen:
        lines.append('import Button from "./../components/Button";')
    if page.forms and "Input" not in seen:
        lines.append('import Input from "./../components/Input";')

    return "\n".join(lines)


def _build_form_state(page: PageSpec) -> str:
    if not page.forms:
        return ""
    lines: list[str] = []
    lines.append("interface FormState {")
    for form in page.forms:
        for field in form:
            ts_type = "string" if field.type in ("text", "email", "password", "select") else "string"
            lines.append(f"  {field.name}: {ts_type};")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _build_handlers(page: PageSpec) -> str:
    if not page.forms:
        return ""
    lines: list[str] = []

    # Build initial state
    inits: list[str] = []
    for form in page.forms:
        for field in form:
            inits.append(f'    {field.name}: "",')
    lines.append("  const [form, setForm] = useState<FormState>({")
    lines.extend(inits)
    lines.append("  });")
    lines.append("  const [errors, setErrors] = useState<Partial<FormState>>({});")
    lines.append("")
    lines.append("  const handleChange = (name: keyof FormState) => (value: string) => {")
    lines.append("    setForm((prev) => ({ ...prev, [name]: value }));")
    lines.append("    setErrors((prev) => ({ ...prev, [name]: undefined }));")
    lines.append("  };")
    lines.append("")
    # Build submit handler with basic validation
    required_fields = [
        f for form in page.forms for f in form if f.required
    ]
    lines.append("  const handleSubmit = (e: React.FormEvent) => {")
    lines.append("    e.preventDefault();")
    lines.append("    const newErrors: Partial<FormState> = {};")
    for rf in required_fields:
        lines.append(f'    if (!form.{rf.name}) newErrors.{rf.name} = "{rf.label} is required";')
    if required_fields:
        lines.append("    if (Object.keys(newErrors).length > 0) { setErrors(newErrors); return; }")
    lines.append("    console.log('Form submitted:', form);")
    lines.append("  };")
    lines.append("")

    return "\n".join(lines)


def _build_jsx(page: PageSpec, app_name: str) -> str:
    """Build the JSX body for the page."""
    lines: list[str] = []

    # Render a heading section if the page has a title
    lines.append(f'      <div className={{styles.pageHeader}}>')
    lines.append(f'        <h1 className={{styles.pageTitle}}>{page.title}</h1>')
    if page.description:
        lines.append(f'        <p className={{styles.pageDesc}}>{page.description}</p>')
    lines.append(f'      </div>')

    # Render forms
    for i, form in enumerate(page.forms):
        lines.append(f'      <form className={{styles.form}} onSubmit={{handleSubmit}} noValidate>')
        for field in form:
            input_type = field.type if field.type in ("text", "email", "password", "number") else "text"
            lines.append(f'        <Input')
            lines.append(f'          label="{field.label}"')
            lines.append(f'          type="{input_type}"')
            if field.placeholder:
                lines.append(f'          placeholder="{field.placeholder}"')
            lines.append(f'          required={{{str(field.required).lower()}}}')
            lines.append(f'          onChange={{handleChange("{field.name}")}}')
            lines.append(f'          error={{errors.{field.name}}}')
            lines.append(f'        />')
        # Submit button
        lines.append(f'        <Button label="Submit" type="submit" />')
        lines.append(f'      </form>')

    # Render action buttons that aren't form submissions
    extra_actions = [a for a in page.actions if a.action != "submit_form"]
    if extra_actions:
        lines.append(f'      <div className={{styles.actions}}>')
        for action in extra_actions:
            lines.append(f'        <Button label="{action.label}" onClick={{() => {{}} }} />')
        lines.append(f'      </div>')

    return "\n".join(lines)


def _pascal(s: str) -> str:
    return "".join(p.capitalize() for p in s.replace("-", "_").split("_"))
