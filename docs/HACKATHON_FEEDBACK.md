# Nebius Token Factory and NVIDIA Nemotron: Developer Feedback

*Submitted for the Most Valuable Feedback Award*

## 1. Nebius Token Factory experience

### What worked well

- **Low latency:** In our tests, `nvidia/Nemotron-3_5-Lightning` averaged 610 ms per completion, making it a good fit for real-time agent workflows.
- **OpenAI API compatibility:** Connecting through `openai-python` was straightforward. Existing chat completion prompts required very few changes.
- **Large context windows:** Lightning and Super-VL support a 1,048,576-token context window, which could help agents process large web projects and DOM trees with less chunking.

### Suggestions for improvement

- **Expose Zero Data Retention status:** The `/v1/models` endpoint does not indicate whether an organization has Zero Data Retention (ZDR) enabled. An endpoint such as `GET /v1/organization/privacy` would allow privacy-sensitive desktop agents to check the organization's retention settings before sending data.
- **Use consistent streaming errors:** Length errors during streaming can make recovery difficult. Standardizing Server-Sent Events (SSE) error formats across Nemotron model variants would help developers handle failures more reliably.

## 2. NVIDIA Nemotron open-source models

- **Nemotron-3_5-Lightning:** In our tests, it provided a good balance of speed and output quality, particularly when generating HTML5/CSS interfaces and Flask REST routes.
- **Nemotron-3-Nano-30B:** This model worked well for focused CSS and DOM patches during iterative repair workflows.
- **Nemotron-3.5-Super-VL:** Native image input through Token Factory is useful for multimodal agents that need to interpret visual layouts and generate corresponding code.
