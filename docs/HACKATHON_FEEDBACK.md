# Nebius Token Factory and NVIDIA Nemotron: Developer Feedback

Submitted for the **Most Valuable Feedback Award** 

## 1. Nebius Token Factory experience

### What worked well

- **Low latency:** In our tests, `nvidia/Nemotron-3_5-Lightning` averaged 610 ms per completion, making it a strong option for real-time agent workflows.
- **OpenAI API compatibility:** Integration with `openai-python` was straightforward, with minimal changes needed to existing chat completion prompts.
- **Large context windows:** The 1,048,576-token context window on Lightning and Super-VL could support large web projects and DOM trees with less need for chunking.

### Suggestions for improvement

- **Make Zero Data Retention status accessible:** The `/v1/models` endpoint does not expose whether an organization has ZDR enabled. An endpoint such as `GET /v1/organization/privacy` would let privacy-sensitive desktop agents verify the organization's data retention settings before sending data to the API.
- **Standardize streaming errors:** Length errors that occur during streaming can complicate recovery. Consistent Server-Sent Events (SSE) error formats across Nemotron model variants would make it easier for developers to handle failures reliably.

## 2. NVIDIA Nemotron open-source models

- **Nemotron-3_5-Lightning:** In our experience, it offers a strong balance of speed and output quality, particularly for generating HTML5/CSS interfaces and Flask REST routes.
- **Nemotron-3-Nano-30B:** A useful option for targeted CSS and DOM patches in iterative repair workflows.
- **Nemotron-3.5-Super-VL:** Native image input through Token Factory is particularly useful for multimodal agents that combine visual understanding with code generation.