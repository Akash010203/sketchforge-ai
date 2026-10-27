# NVIDIA and Nebius integration

**Status (2026-10-21):** Live Nebius model-list and Nemotron completion probes pass. Mock-transport tests pass, and local SketchForge detector inference runs on the NVIDIA GPU. The three-arm remote edit benchmark has not been run.

See "Verification status" for the supporting evidence and remaining limitations.

## 1. Official requirements

Requirements below were checked against official pages on 2026-10-21.

Sources: [Nebius x NVIDIA Global AI Hackathon](https://nebiusglobalaihackathon.devpost.com/), [hackathon rules](https://nebiusglobalaihackathon.devpost.com/rules), and [Nebius Token Factory documentation](https://docs.tokenfactory.nebius.com/), including the `llms.txt` index, API introduction, vision documentation, legal quick guide, and August 2026 deprecation notice.

| Item | Published requirement |
|---|---|
| Hackathon | Nebius x NVIDIA Global AI Hackathon on Devpost. Tracks: Coding and Agentic Engineering, Best Apps and Agents, Personal AI, and Physical AI. |
| **Deadline** | **Friday, 30 October 2026, 10:00 am Pacific Time**, equivalent to 22:30 IST on the same day. |
| Platform | A working software application that **runs on either Nebius Token Factory or Nebius AI Cloud** and **uses at least one NVIDIA open-source model**, such as Nemotron or another NVIDIA open model. |
| What "runs on" means | The project makes a **runtime call to the Token Factory inference API**, or it is deployed or run using Nebius AI Cloud compute, such as Serverless Jobs, Endpoints, or DevPods. |
| Repository | The repository must be public, with an open-source license file visible at the top level, such as Apache 2.0, MIT, or MPL 2.0. It must include all source code and a README with setup instructions. The README must explain how NVIDIA models are used, where Token Factory helped, and which other Nebius tools were used. |
| Demo | Submit a URL to a working demo, hosted application, or **test build**. This is not required for Physical AI. A public YouTube video under 3 minutes must show the project working on the device it was built for. The project must remain available free of charge and without restrictions until judging ends. |
| Other requirements | Provide a project description and feedback on Nebius Token Factory, AI Cloud, and NVIDIA tools. The entrant must own the original work exclusively. If the project predates the submission period, provide a written explanation of the significant updates. Work derived from projects that received financial or preferential support from the sponsor is not eligible. |
| Judging criteria, equally weighted | Technological Implementation, Design (a complete and coherent product rather than a proof of concept), Potential Impact, and Quality of the Idea. |
| AI coding tools | The pages reviewed did not state a rule on AI coding tools. The entrant should read the complete Official Rules before submitting. |

### Token Factory API and data handling

The documentation describes an OpenAI-compatible API with these details:

- Base URL: `https://api.tokenfactory.nebius.com/v1/`
- Authentication: `Authorization: Bearer <key>`, conventionally configured through `NEBIUS_API_KEY`
- Chat completions: `POST /v1/chat/completions`
- Model listing: `GET /v1/models`; adding `?verbose=true` provides modality information
- Structured JSON output and function calling are documented.
- Image input uses OpenAI-style `image_url` content parts.

The Token Factory Legal Quick Guide states that, without Zero Data Retention (ZDR), Nebius retains inputs and outputs to speed up inference. Data is stored in Finland/EU and may be used for speculative decoding. Content is not used to train models in either mode. ZDR is configured at the organisation level, and the processing location for public endpoints is determined dynamically.

### NVIDIA models available through Token Factory

The August 2026 deprecation notice states that the following models were removed from serverless on 31 August 2026:

- `nvidia/Nemotron-3-Nano-Omni`
- `nvidia/Llama-3_1-Nemotron-Ultra-253B-v1`
- `nvidia/Cosmos3-Super-Reasoner`

The notice names two NVIDIA replacements:

- `nvidia/Nemotron-3_5-Lightning`
- `nvidia/nemotron-3-super-120b-a12b`

The documentation reviewed does not specify whether these two replacements accept image input. Checking the live model list also requires an API key. SketchForge therefore discovers capabilities at runtime through the model registry, as described in §3. `scripts/verify_nebius.py` must confirm the exact model IDs before they are relied on.

## 2. What this means for SketchForge

- **Outbound connections only.** SketchForge does not run an application API server. A runtime call to the Token Factory inference API satisfies the published "runs on Token Factory" requirement. The project does not create its own server or cloud backend.
- **Privacy by default.** Remote edit requests contain a compact structured summary of the design, including IDs, types, rounded bounding boxes, and the component tree, along with the user's instruction. The sketch image is never sent. Text inside components is excluded unless the user explicitly opts in through `include_user_text`.
- **Remote access requires consent.** The provider must be enabled in configuration, and the user must acknowledge the data-egress notice for the current session. The notice explains what information will be sent, where it will go, and Nebius's retention behavior. With ZDR disabled, inputs and outputs are retained.
- **All edits are validated locally.** The model returns a proposed edit plan, which is parsed into typed data and checked against the Design IR rules. SketchForge applies valid plans as ordinary undoable commands, then runs the same evaluator and bounded repair loop used for other edits. Malformed or unsafe responses are rejected rather than silently corrected.
- **Demo submission.** The hackathon requires a URL for a working demo, hosted application, or test build. Since SketchForge is a desktop application, a downloadable test build through a GitHub release is the architecture-compatible option. The entrant must confirm whether the organisers will accept it. Hosting a separate demo server is excluded by the project's rules.

## 3. Integration design

```text
assist/
  edit plans, local rule parser, model planner, verified apply
       |
       | typed objects only
       v
integrations/provider_interface.py
  ModelProvider · CompletionRequest/Result · ProviderError family
       |
       v
integrations/nebius/
  configuration · request_policy · client (OpenAI SDK)
  model_registry · health_check

integrations/nvidia/
  model_configuration (eligible model IDs and capability notes)
```

The `model_registry` discovers provider capabilities instead of assuming them, including whether a model accepts text only or image input and whether JSON mode is available.

`client.py` handles timeouts, bounded retries for HTTP 429 responses, server errors (5xx), and timeouts, capped backoff, response validation, and per-request latency and usage tracking. Code that calls a provider does not need to handle Nebius-specific response formats.

## 4. Benchmark: three arms

The benchmark specified in §10 compares three product configurations:

1. **Local:** a rule-based parser handles natural-language edit instructions.
2. **Model:** Nemotron on Token Factory converts the instruction into an edit plan. Local validation and evaluation follow, with automatic repair disabled.
3. **Hybrid:** SketchForge uses the model's plan when valid, falls back to the local parser when the model is unavailable, and then runs local validation, evaluator checks, and bounded repair.

Run all three arms with:

```bash
python scripts/run_visual_benchmark.py --enable --accept-egress
```

An `oracle` arm is also available as a reference control, but it is excluded from the three measured product arms.

Model and hybrid runs require `NEBIUS_API_KEY`, network access, and explicit acknowledgement of data egress. The script checks credentials before generating fixtures or starting benchmark tasks.

The task set is `tests/evaluation/edit_tasks.json`, which maps instructions to machine-checkable expectations.

Metrics include edit success, invalid-plan rate, newly introduced layout issues, repair success, latency, and token usage. The benchmark must report neutral or negative results accurately when they occur.

## 5. Verification status

| Claim | Status | Evidence |
|---|---|---|
| Official rules read and recorded | VERIFIED | This document, §1 |
| Client follows the documented protocol | IMPLEMENTED; mock transport verified | `tests/integration/test_nebius_integration.py`. This does not establish live service access. |
| Live Token Factory access and Nemotron completion | VERIFIED on 2026-10-21 | `experiments/results/live_nebius_benchmark.json`: `/v1/models` returned 28 models, and a fixed completion succeeded using `nvidia/Nemotron-3_5-Lightning` with 96 output tokens and 697.7 ms latency. |
| Live model IDs and capabilities | VERIFIED on 2026-10-21 | The response listed five NVIDIA models. `nvidia/Nemotron-3_5-Lightning` supports `text->text` and does not accept images. `nvidia/Nemotron-3.5-Super-VL` reports `text+image->text`. |
| Three-arm edit benchmark | **NOT RUN** | Automatic approval review rejected the benchmark because it exports task instructions and compact design summaries. Explicit user approval for this payload is required. |
| Local NVIDIA runtime | VERIFIED for model loading and one inference call | The component-detector checkpoint loaded on an RTX 4050 Laptop GPU with 6140 MiB VRAM and returned an inference result. This was not local Nemotron inference. The saved detector report has mAP 0.0. |
| Local Nemotron weights | **NOT INSTALLED** | The default laptop runtime uses the SketchForge detector. No Nemotron GGUF/AWQ loader or checkpoint is configured. |
| ZDR setting | **UNKNOWN** | The Token Factory API does not expose the organisation-level retention setting. Check it in the Nebius organisation console. |
| Local edit baseline | MEASURED | `output/reports/local_edit_benchmark.json`: 34 of 58 tasks passed, a success rate of 58.62%. |

### Running the live probe

Set `NEBIUS_API_KEY` in the environment or in the ignored local `.env` file, then run:

```bash
python scripts/verify_nebius.py --enable --accept-egress
```

The probe requests the model list and sends a fixed, one-line completion prompt. By default, it writes the result to `experiments/results/live_nebius_benchmark.json`. Use `--out` to specify another output path.

The report records model-list status, the selected model, latency, and token counts. It does not record the API key or prompt and response contents.

The ZDR setting remains `unknown` because the endpoint does not report the organisation-level retention configuration.

### Local inference versus hosted Nemotron

The NVIDIA local runtime is a separate on-device path. It loads SketchForge's component detector from local checkpoints. The checkpoint has a reported mAP of 0.0, so successful loading and a returned inference result do not establish useful detection accuracy. This is not a Nemotron runtime.

The hosted Token Factory client is the verified Nemotron path. Local detector inference must not be described as local Nemotron inference.

### Why the remote edit benchmark remains pending

The full edit benchmark sends more data than the fixed live probe. For each model or hybrid task, it exports the benchmark instruction and a compact synthetic design summary. Automatic approval review rejected the run, so explicit user approval is still required before proceeding.

The offline local arm has been measured separately. Its results do not establish the performance of model-assisted or hybrid editing.
