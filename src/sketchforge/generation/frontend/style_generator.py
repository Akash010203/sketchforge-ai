"""Style generator: produces CSS (modules and global) from Design IR layout tokens."""
from __future__ import annotations

from sketchforge.generation.app_specification import PageSpec


# ---------------------------------------------------------------------------
# Global styles
# ---------------------------------------------------------------------------

GLOBAL_CSS = '''\
/* SketchForge Generated Application — Global Styles */
/* Design tokens */
:root {
  --sf-primary:       #6C63FF;
  --sf-primary-dark:  #5A52D5;
  --sf-secondary:     #FF6584;
  --sf-surface:       #FFFFFF;
  --sf-surface-alt:   #F8F9FA;
  --sf-border:        #E2E8F0;
  --sf-text:          #1A202C;
  --sf-text-muted:    #718096;
  --sf-error:         #E53E3E;
  --sf-success:       #38A169;
  --sf-radius:        8px;
  --sf-radius-lg:     16px;
  --sf-shadow:        0 2px 8px rgba(0, 0, 0, 0.08);
  --sf-shadow-lg:     0 8px 32px rgba(0, 0, 0, 0.12);
  --sf-font:          -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  --sf-font-mono:     "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
  --sf-transition:    0.2s ease;
}

/* Reset */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html { font-size: 16px; scroll-behavior: smooth; }

body {
  font-family: var(--sf-font);
  color: var(--sf-text);
  background: var(--sf-surface-alt);
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
}

a { color: var(--sf-primary); text-decoration: none; transition: color var(--sf-transition); }
a:hover { color: var(--sf-primary-dark); }

ul, ol { list-style: none; }

img, video { max-width: 100%; display: block; }

button, input, select, textarea {
  font: inherit;
  outline: none;
}

/* Utility classes */
.sf-container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 24px;
}

.sf-flex { display: flex; }
.sf-col { flex-direction: column; }
.sf-center { align-items: center; justify-content: center; }
.sf-gap-sm { gap: 8px; }
.sf-gap-md { gap: 16px; }
.sf-gap-lg { gap: 24px; }

/* Scrollbar */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: var(--sf-surface-alt); }
::-webkit-scrollbar-thumb { background: var(--sf-border); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--sf-text-muted); }

/* Focus ring */
:focus-visible {
  outline: 2px solid var(--sf-primary);
  outline-offset: 2px;
}
'''


COMPONENT_CSS = {
    "Button.module.css": '''\
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 10px 20px;
  border: none;
  border-radius: var(--sf-radius);
  font-weight: 600;
  font-size: 0.9rem;
  cursor: pointer;
  transition: background var(--sf-transition), transform var(--sf-transition), box-shadow var(--sf-transition);
  letter-spacing: 0.02em;
  min-width: 88px;
  user-select: none;
}

.btn:hover:not(:disabled) { transform: translateY(-1px); box-shadow: var(--sf-shadow-lg); }
.btn:active:not(:disabled) { transform: translateY(0); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }

.primary { background: var(--sf-primary); color: #fff; }
.primary:hover:not(:disabled) { background: var(--sf-primary-dark); }

.secondary {
  background: transparent;
  color: var(--sf-primary);
  border: 2px solid var(--sf-primary);
}
.secondary:hover:not(:disabled) {
  background: var(--sf-primary);
  color: #fff;
}

.danger { background: var(--sf-error); color: #fff; }
.danger:hover:not(:disabled) { background: #C53030; }
''',

    "Input.module.css": '''\
.wrapper { display: flex; flex-direction: column; gap: 6px; }

.label {
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--sf-text);
}

.required { color: var(--sf-error); margin-left: 2px; }

.input {
  padding: 10px 14px;
  border: 1.5px solid var(--sf-border);
  border-radius: var(--sf-radius);
  background: var(--sf-surface);
  color: var(--sf-text);
  font-size: 0.9rem;
  transition: border-color var(--sf-transition), box-shadow var(--sf-transition);
  width: 100%;
}

.input:focus {
  border-color: var(--sf-primary);
  box-shadow: 0 0 0 3px rgba(108, 99, 255, 0.12);
}

.input.error { border-color: var(--sf-error); }
.input.error:focus { box-shadow: 0 0 0 3px rgba(229, 62, 62, 0.12); }

.input::placeholder { color: var(--sf-text-muted); }

.errorMsg { font-size: 0.8rem; color: var(--sf-error); }
''',

    "Card.module.css": '''\
.card {
  background: var(--sf-surface);
  border-radius: var(--sf-radius-lg);
  border: 1px solid var(--sf-border);
  padding: 24px;
  transition: box-shadow var(--sf-transition), transform var(--sf-transition);
}

.card:hover { box-shadow: var(--sf-shadow-lg); }

.elevated { box-shadow: var(--sf-shadow-lg); }

.title {
  font-size: 1.1rem;
  font-weight: 600;
  margin-bottom: 16px;
  color: var(--sf-text);
}

.content { color: var(--sf-text); }
''',

    "Header.module.css": '''\
.header {
  background: linear-gradient(135deg, var(--sf-primary), var(--sf-primary-dark));
  color: #fff;
  padding: 40px 24px;
  text-align: center;
}

.title {
  font-size: 2rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  margin-bottom: 8px;
}

.subtitle {
  font-size: 1rem;
  opacity: 0.85;
}
''',

    "Nav.module.css": '''\
.nav {
  display: flex;
  align-items: center;
  gap: 32px;
  background: var(--sf-surface);
  padding: 0 24px;
  height: 64px;
  border-bottom: 1px solid var(--sf-border);
  box-shadow: var(--sf-shadow);
  position: sticky;
  top: 0;
  z-index: 100;
}

.brand {
  font-size: 1.2rem;
  font-weight: 700;
  color: var(--sf-primary);
  margin-right: auto;
}

.menu { display: flex; gap: 4px; }

.link {
  padding: 8px 16px;
  border-radius: var(--sf-radius);
  font-weight: 500;
  font-size: 0.9rem;
  color: var(--sf-text-muted);
  transition: color var(--sf-transition), background var(--sf-transition);
}

.link:hover { color: var(--sf-text); background: var(--sf-surface-alt); }
.link.active { color: var(--sf-primary); background: rgba(108, 99, 255, 0.08); }
''',

    "Text.module.css": '''\
.heading { font-size: 1.5rem; font-weight: 700; color: var(--sf-text); line-height: 1.3; }
.body { font-size: 0.95rem; color: var(--sf-text); line-height: 1.7; }
.label { font-size: 0.875rem; font-weight: 500; color: var(--sf-text-muted); }
.caption { font-size: 0.78rem; color: var(--sf-text-muted); }
''',

    "Image.module.css": '''\
.img { border-radius: var(--sf-radius); object-fit: cover; }

.placeholder {
  background: var(--sf-surface-alt);
  border: 2px dashed var(--sf-border);
  border-radius: var(--sf-radius);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--sf-text-muted);
  font-size: 0.85rem;
  min-height: 120px;
}
''',

    "Checkbox.module.css": '''\
.wrapper {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  user-select: none;
}

.input {
  width: 18px;
  height: 18px;
  border: 2px solid var(--sf-border);
  border-radius: 4px;
  cursor: pointer;
  accent-color: var(--sf-primary);
}

.label { font-size: 0.9rem; color: var(--sf-text); }

.disabled { opacity: 0.5; cursor: not-allowed; }
.disabled .input { cursor: not-allowed; }
''',

    "Divider.module.css": '''\
.divider {
  border: none;
  border-top: 1px solid var(--sf-border);
  margin: 16px 0;
}

.vertical {
  border: none;
  border-left: 1px solid var(--sf-border);
  margin: 0 16px;
  align-self: stretch;
}

.labeled {
  position: relative;
  text-align: center;
  border-top: 1px solid var(--sf-border);
  margin: 16px 0;
}

.labeled .label {
  position: absolute;
  top: -0.6em;
  left: 50%;
  transform: translateX(-50%);
  background: var(--sf-surface);
  padding: 0 8px;
  font-size: 0.8rem;
  color: var(--sf-text-muted);
}
''',
}


def generate_page_css(page: PageSpec) -> str:
    """Generate a CSS module for a page based on its layout."""
    slug = page.name.replace(" ", "_").lower()
    return f'''\
/* CSS Module: {page.title} */

.page {{
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--sf-surface-alt);
}}

.pageHeader {{
  text-align: center;
  padding: 48px 24px 32px;
  background: linear-gradient(180deg, var(--sf-surface) 0%, var(--sf-surface-alt) 100%);
}}

.pageTitle {{
  font-size: 2rem;
  font-weight: 700;
  color: var(--sf-text);
  margin-bottom: 8px;
}}

.pageDesc {{
  font-size: 1rem;
  color: var(--sf-text-muted);
  max-width: 500px;
  margin: 0 auto;
}}

.form {{
  display: flex;
  flex-direction: column;
  gap: 20px;
  max-width: 480px;
  margin: 0 auto;
  padding: 40px 32px;
  background: var(--sf-surface);
  border-radius: var(--sf-radius-lg);
  box-shadow: var(--sf-shadow-lg);
  border: 1px solid var(--sf-border);
}}

.actions {{
  display: flex;
  gap: 12px;
  justify-content: center;
  padding: 24px;
  flex-wrap: wrap;
}}
'''


def global_css() -> str:
    return GLOBAL_CSS


def component_css(filename: str) -> str | None:
    return COMPONENT_CSS.get(filename)


def all_component_css_files() -> dict[str, str]:
    return dict(COMPONENT_CSS)
