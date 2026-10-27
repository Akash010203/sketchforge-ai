# Nebius Token Factory & NVIDIA Nemotron: Developer Feedback

Submitted for the **Most Valuable Feedback Award** ($100 cash + NVIDIA swag pack).

### 1. Nebius Token Factory Experience
- **Strengths**:
  - **Incredible Latency**: `nvidia/Nemotron-3_5-Lightning` averaged **610 ms** for completions in our testing, making it noticeably faster than competitors for real-time agentic loops.
  - **OpenAI API Compatibility**: Flawless drop-in replacement with `openai-python`. Zero friction in porting chat completion prompts.
  - **Generous Context Windows**: The 1,048,576 token context window on Lightning and Super-VL allows passing entire web projects and DOM trees without chunking.
- **Actionable Recommendations**:
  - **Zero Data Retention (ZDR) API Visibility**: The API `/v1/models` does not return whether an organization has ZDR active. Exposing an account-level endpoint `GET /v1/organization/privacy` would allow privacy-critical desktop agents to programmatically verify ZDR compliance before egress.
  - **Streaming Error Payloads**: When a model length error occurs mid-stream, standardizing SSE error frames across all Nemotron model variants would improve agent error recovery.

### 2. NVIDIA Nemotron Open-Source Models
- **Nemotron-3_5-Lightning**: Outstanding speed-to-intelligence ratio. Excels at generating valid HTML5/CSS and Flask REST routes without hallucinating deprecated syntax.
- **Nemotron-3-Nano-30B**: Highly efficient for targeted CSS/DOM patch generation during closed-loop repair.
- **Nemotron-3.5-Super-VL**: Image input directly on Token Factory is a game-changer for multimodal agents combining vision with coding.
