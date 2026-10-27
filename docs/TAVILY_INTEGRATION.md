# Tavily AI Search Integration ($3,000 Best Use Award)

SketchForge AI utilizes **Tavily Search API** to give its coding agents real-time web awareness.

### Problem Solved
Code generation models often suffer from training cutoffs, generating outdated CSS properties or hallucinating non-existent icon names.

### Architecture
1. **Pre-Synthesis Retrieval**: When a user inputs an app brief (e.g. *"Modern SaaS Analytics Dashboard with dark glassmorphism and Lucide icons"*), `TavilyResearcher` (`sketchforge/integrations/tavily/client.py`) performs an advanced query.
2. **Context Injection**: Relevant UI design patterns, CSS gradient snippets, and accessibility best practices are parsed and injected into the Nemotron-3-Ultra and Nemotron-3_5-Lightning prompts.
3. **Outcome**: Clean, modern applications using state-of-the-art styling rather than generic 2021-era templates.
