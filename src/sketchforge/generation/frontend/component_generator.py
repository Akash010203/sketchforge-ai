"""Component generator: converts Design IR component types into React + TypeScript source.

Each function returns a complete, formatted .tsx string for a reusable component.
Components use only React + CSS modules — no external UI library dependency.
"""
from __future__ import annotations

from sketchforge.design_ir.schema import ComponentType


# Map from component type string to a generator function
_GENERATORS: dict[str, "ComponentFn"] = {}
ComponentFn = "Callable[[str, dict], str]"


def generate_component(component_type: str, props: dict | None = None) -> str:
    """Generate a React functional component for the given Design IR type.

    Args:
        component_type: lowercased string matching ComponentType enum value.
        props: optional overrides (label, placeholder, …).
    """
    props = props or {}
    key = component_type.lower()
    fn = _GENERATORS.get(key)
    if fn is None:
        return _generic_component(component_type, props)
    return fn(component_type, props)


def _reg(name: str):
    """Decorator to register a component generator."""
    def _inner(fn):
        _GENERATORS[name.lower()] = fn
        return fn
    return _inner


# ---------------------------------------------------------------------------
# Individual component generators
# ---------------------------------------------------------------------------

@_reg("button")
def _button(name: str, props: dict) -> str:
    label = props.get("label", "Button")
    return f'''\
import React from "react";
import styles from "./Button.module.css";

interface ButtonProps {{
  label?: string;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "danger";
  disabled?: boolean;
  type?: "button" | "submit" | "reset";
}}

const Button: React.FC<ButtonProps> = ({{
  label = "{label}",
  onClick,
  variant = "primary",
  disabled = false,
  type = "button",
}}) => {{
  return (
    <button
      className={{`${{styles.btn}} ${{styles[variant]}}`}}
      onClick={{onClick}}
      disabled={{disabled}}
      type={{type}}
    >
      {{label}}
    </button>
  );
}};

export default Button;
'''


@_reg("input")
def _input(name: str, props: dict) -> str:
    placeholder = props.get("placeholder", "Enter value…")
    return f'''\
import React, {{ useState }} from "react";
import styles from "./Input.module.css";

interface InputProps {{
  label?: string;
  placeholder?: string;
  type?: string;
  value?: string;
  onChange?: (value: string) => void;
  required?: boolean;
  error?: string;
}}

const Input: React.FC<InputProps> = ({{
  label,
  placeholder = "{placeholder}",
  type = "text",
  value,
  onChange,
  required = false,
  error,
}}) => {{
  const [inner, setInner] = useState(value ?? "");

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {{
    setInner(e.target.value);
    onChange?.(e.target.value);
  }};

  return (
    <div className={{styles.wrapper}}>
      {{label && <label className={{styles.label}}>{{label}}{{required && <span className={{styles.required}}>*</span>}}</label>}}
      <input
        className={{`${{styles.input}} ${{error ? styles.error : ""}}`}}
        type={{type}}
        placeholder={{placeholder}}
        value={{inner}}
        onChange={{handleChange}}
        required={{required}}
        aria-invalid={{!!error}}
      />
      {{error && <span className={{styles.errorMsg}}>{{error}}</span>}}
    </div>
  );
}};

export default Input;
'''


@_reg("card")
def _card(name: str, props: dict) -> str:
    return '''\
import React from "react";
import styles from "./Card.module.css";

interface CardProps {
  title?: string;
  children?: React.ReactNode;
  className?: string;
  elevated?: boolean;
}

const Card: React.FC<CardProps> = ({ title, children, className = "", elevated = false }) => {
  return (
    <div className={`${styles.card} ${elevated ? styles.elevated : ""} ${className}`}>
      {title && <h3 className={styles.title}>{title}</h3>}
      <div className={styles.content}>{children}</div>
    </div>
  );
};

export default Card;
'''


@_reg("header")
def _header(name: str, props: dict) -> str:
    app_name = props.get("appName", "SketchForge App")
    return f'''\
import React from "react";
import styles from "./Header.module.css";

interface HeaderProps {{
  title?: string;
  subtitle?: string;
}}

const Header: React.FC<HeaderProps> = ({{ title = "{app_name}", subtitle }}) => {{
  return (
    <header className={{styles.header}}>
      <h1 className={{styles.title}}>{{title}}</h1>
      {{subtitle && <p className={{styles.subtitle}}>{{subtitle}}</p>}}
    </header>
  );
}};

export default Header;
'''


@_reg("nav")
def _nav(name: str, props: dict) -> str:
    return '''\
import React from "react";
import { NavLink } from "react-router-dom";
import styles from "./Nav.module.css";

interface NavItem {
  label: string;
  to: string;
}

interface NavProps {
  items?: NavItem[];
  brand?: string;
}

const Nav: React.FC<NavProps> = ({ items = [], brand = "App" }) => {
  return (
    <nav className={styles.nav}>
      <span className={styles.brand}>{brand}</span>
      <ul className={styles.menu}>
        {items.map((item) => (
          <li key={item.to}>
            <NavLink
              to={item.to}
              className={({ isActive }) =>
                isActive ? `${styles.link} ${styles.active}` : styles.link
              }
            >
              {item.label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
};

export default Nav;
'''


@_reg("text")
@_reg("heading")
@_reg("label")
def _text(name: str, props: dict) -> str:
    tag = "h2" if name.lower() == "heading" else "p"
    return f'''\
import React from "react";
import styles from "./Text.module.css";

interface TextProps {{
  children?: React.ReactNode;
  variant?: "heading" | "body" | "label" | "caption";
  className?: string;
}}

const Text: React.FC<TextProps> = ({{ children, variant = "body", className = "" }}) => {{
  if (variant === "heading") return <h2 className={{`${{styles.heading}} ${{className}}`}}>{{children}}</h2>;
  if (variant === "label") return <span className={{`${{styles.label}} ${{className}}`}}>{{children}}</span>;
  if (variant === "caption") return <span className={{`${{styles.caption}} ${{className}}`}}>{{children}}</span>;
  return <p className={{`${{styles.body}} ${{className}}`}}>{{children}}</p>;
}};

export default Text;
'''


@_reg("image")
@_reg("img")
def _image(name: str, props: dict) -> str:
    return '''\
import React from "react";
import styles from "./Image.module.css";

interface ImageProps {
  src?: string;
  alt?: string;
  width?: number | string;
  height?: number | string;
  className?: string;
}

const Image: React.FC<ImageProps> = ({
  src = "",
  alt = "",
  width,
  height,
  className = "",
}) => {
  if (!src) {
    return (
      <div className={`${styles.placeholder} ${className}`} style={{ width, height }}>
        <span>Image</span>
      </div>
    );
  }
  return (
    <img
      src={src}
      alt={alt}
      width={width}
      height={height}
      className={`${styles.img} ${className}`}
      loading="lazy"
    />
  );
};

export default Image;
'''


@_reg("checkbox")
def _checkbox(name: str, props: dict) -> str:
    label = props.get("label", "Checkbox")
    return f'''\
import React, {{ useState }} from "react";
import styles from "./Checkbox.module.css";

interface CheckboxProps {{
  label?: string;
  checked?: boolean;
  onChange?: (checked: boolean) => void;
  disabled?: boolean;
}}

const Checkbox: React.FC<CheckboxProps> = ({{
  label = "{label}",
  checked = false,
  onChange,
  disabled = false,
}}) => {{
  const [inner, setInner] = useState(checked);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {{
    setInner(e.target.checked);
    onChange?.(e.target.checked);
  }};

  return (
    <label className={{`${{styles.wrapper}} ${{disabled ? styles.disabled : ""}}`}}>
      <input
        type="checkbox"
        className={{styles.input}}
        checked={{inner}}
        onChange={{handleChange}}
        disabled={{disabled}}
      />
      <span className={{styles.label}}>{{label}}</span>
    </label>
  );
}};

export default Checkbox;
'''


@_reg("divider")
def _divider(name: str, props: dict) -> str:
    return '''\
import React from "react";
import styles from "./Divider.module.css";

interface DividerProps {
  orientation?: "horizontal" | "vertical";
  label?: string;
}

const Divider: React.FC<DividerProps> = ({ orientation = "horizontal", label }) => {
  if (label) {
    return (
      <div className={`${styles.divider} ${styles.labeled}`}>
        <span className={styles.label}>{label}</span>
      </div>
    );
  }
  return <hr className={`${styles.divider} ${styles[orientation]}`} />;
};

export default Divider;
'''


def _generic_component(component_type: str, props: dict) -> str:
    name = _pascal(component_type)
    return f'''\
import React from "react";

interface {name}Props {{
  children?: React.ReactNode;
  className?: string;
}}

const {name}: React.FC<{name}Props> = ({{ children, className = "" }}) => {{
  return (
    <div className={{`sketchforge-{component_type.lower()} ${{className}}`}}>
      {{children}}
    </div>
  );
}};

export default {name};
'''


def _pascal(s: str) -> str:
    return "".join(p.capitalize() for p in s.replace("-", "_").split("_"))
