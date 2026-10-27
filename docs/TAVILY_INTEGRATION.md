## Tavily AI Search Integration 

SketchForge AI uses the Tavily Search API to help its coding agents find up-to-date information online.

### Problem

AI coding models can rely on outdated training data, leading to old CSS techniques or incorrect icon names.

### How it works

1. **Search before generation:** When a user submits an app brief, `TavilyResearcher` (`sketchforge/integrations/tavily/client.py`) searches for relevant web resources.
2. **Add context to prompts:** The system extracts useful UI design patterns, CSS examples, and accessibility guidelines, then adds them to the Nemotron-3-Ultra and Nemotron-3_5-Lightning prompts.
3. **Generate better interfaces:** This gives the models current design references to work with, helping them produce more modern, polished applications.
