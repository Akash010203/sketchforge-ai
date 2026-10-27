# NVIDIA / Nebius integration

**Status (2026-10-21): Nebius live model-list and Nemotron completion probes pass; mock-transport tests pass; local SketchForge detector inference loads on the NVIDIA GPU. The three-arm remote edit benchmark remains unrun.**
See "Verification status" below for evidence and limits.

## 1. Official requirements (verified from the official pages, 2026-10-21)

Sources: Devpost hackathon page <https://nebiusglobalaihackathon.devpost.com/> and its rules page
<https://nebiusglobalaihackathon.devpost.com/rules>; Token Factory docs
<https://docs.tokenfactory.nebius.com/> (`llms.txt` index, API introduction, vision, legal quick guide,
August-2026 deprecation notice).

| Item | Requirement as published |
|---|---|
| Hackathon | Nebius x NVIDIA Global AI Hackathon (Devpost). Tracks: Coding and Agentic Engineering · Best Apps and Agents · Personal AI · Physical AI |
| **Deadline** | **Friday 30 Oct 2026, 10:00 am Pacific Time** (= 22:30 IST the same day) |
| Platform | "a working software application that **runs on either Nebius Token Factory or Nebius AI Cloud**" and "**uses at least one NVIDIA open source model**" (Nemotron or other NVIDIA open models) |
| What "runs on" means | the project "makes a **runtime call to the Token Factory inference API**", or "is deployed/run using Nebius AI Cloud compute" (Serverless Jobs / Endpoints / DevPods) |
| Repository | public, with an open-source license file visible at the top of the repo (e.g. **Apache 2.0, MIT, MPL 2.0**), all source + README with setup instructions; README must say how NVIDIA models are used, where Token Factory helped, other Nebius tools used |
| Demo | URL to "a working demo, hosted application, or **test build**" (not needed for Physical AI); public YouTube video **< 3 min** showing the project working on the device it was built for; available free of charge and without restriction until judging ends |
| Other | project description; feedback on Nebius Token Factory / AI Cloud / NVIDIA tools; original work solely owned by the entrant; if it pre-dates the submission period, a written explanation of what was significantly updated; must not derive from work with financial/preferential support from the sponsor |
| Judging (equal weight) | Technological Implementation · Design (a complete coherent product, not a proof of concept) · Potential Impact · Quality of the Idea |
| Not stated on the pages read | any rule on AI coding tools (the full Official Rules should be read by the entrant before submitting) |

**Token Factory facts** (docs): OpenAI-compatible API, base URL `https://api.tokenfactory.nebius.com/v1/`,
`Authorization: Bearer <key>`, key conventionally in `NEBIUS_API_KEY`, chat completions at
`POST /v1/chat/completions`, models at `GET /v1/models` (`?verbose=true` adds modality), structured
output ("JSON") and function calling documented, image input documented as OpenAI-style
`image_url` content parts. **Data handling** (Legal Quick Guide): without Zero Data Retention (ZDR)
"we keep your inputs and outputs to speed up inference" (stored in Finland/EU; may be used for
speculative decoding); content is **not used to train** models in either mode; ZDR is an
organisation-level setting; public endpoints' processing location is decided dynamically.

**NVIDIA models on Token Factory.** The *August 2026 deprecation notice* removed
`nvidia/Nemotron-3-Nano-Omni`, `nvidia/Llama-3_1-Nemotron-Ultra-253B-v1` and `nvidia/Cosmos3-Super-Reasoner`
from serverless on 31 Aug 2026 and names these NVIDIA replacements: **`nvidia/Nemotron-3_5-Lightning`**
and **`nvidia/nemotron-3-super-120b-a12b`**. Whether those two accept image input is **not stated** in
the pages read, and the live model list needs an API key. The integration is therefore
*capability-driven* (see §3) and the exact IDs must be confirmed by `scripts/verify_nebius.py`.

## 2. What this means for SketchForge

* The no-application-API rule stands: SketchForge only ever acts as an **outbound client**. A
  runtime call to the Token Factory inference API satisfies "runs on Token Factory"; no server of ours
  is created and no cloud backend of ours exists.
* **Privacy by construction.** The default remote task sends a *compact structured summary* of the
  design (ids, types, rounded boxes, tree) plus the user's instruction — **never the sketch image**, and
  never the text inside components unless the user opts in (`include_user_text`).
* **Off by default; explicit consent.** The client refuses to send unless the provider is enabled in
  configuration *and* the user acknowledged the egress notice for this session. The notice states what
  is sent, where, and Nebius's retention behaviour (ZDR off ⇒ inputs/outputs retained).
* **The model proposes, local code disposes.** Model output is parsed into a typed edit plan,
  validated against the Design IR rules, applied as an ordinary undoable command, then checked by the
  same evaluator and bounded repair loop as everything else. A malformed or unsafe answer is rejected,
  never "fixed up" silently.
* **Demo/testing requirement.** The hackathon wants a "working demo … or test build" URL. SketchForge
  is a desktop application; a downloadable test build (GitHub release) is the architecture-compatible
  route. Whether the organisers accept that is for the entrant to confirm with them. Hosting our own
  demo server is excluded by the project rules.

## 3. Design (this phase)

```
assist/  (edit plans, local rule parser, model planner, verified apply)
   │ typed objects only
integrations/provider_interface.py   ModelProvider · CompletionRequest/Result · ProviderError family
   │
integrations/nebius/   configuration · request_policy · client (OpenAI SDK) · model_registry · health_check
integrations/nvidia/   model_configuration (eligible model ids + capability notes)
```

Provider capabilities are discovered, not assumed (`model_registry`): text-only vs image input,
JSON-mode availability. Timeouts, bounded retries (429/5xx/timeouts only, capped backoff), response
validation and per-request latency/usage tracking are implemented in `client.py`; the code that
uses a provider never sees Nebius's response format.

## 4. Benchmark (spec §10): three arms

1. **Local** — rule-based parser for natural-language edits.
2. **Model** — Nemotron on Token Factory translates the instruction into an edit plan, then local plan validation and evaluation run; automatic repair is off.
3. **Hybrid** — use the model plan when valid, fall back to the local parser when unavailable, then run local validation, evaluator checks and bounded repair.

The default command runs these three arms: `python scripts/run_visual_benchmark.py --enable --accept-egress`. The `oracle` arm remains available as a reference control, but is not one of the three measured product arms. Model and hybrid runs require `NEBIUS_API_KEY`, network access and explicit egress acknowledgement. The script checks credentials before building fixtures or starting benchmark tasks.

Task set: `tests/evaluation/edit_tasks.json` (instruction → machine-checkable expectation).
Metrics: edit success, invalid-plan rate, new layout issues introduced, repair success, latency,
tokens. Run: `python scripts/run_visual_benchmark.py --enable --accept-egress` (needs a key and network).
A neutral or negative result is reported as such.

## 5. Verification status

| Claim | Status | Evidence |
|---|---|---|
| Official rules read and recorded | VERIFIED | this file, §1 |
| Client speaks the documented protocol | IMPLEMENTED; mock transport verified | `tests/integration/test_nebius_integration.py` (does not verify live service access) |
| Live Token Factory access and Nemotron completion | VERIFIED on 2026-10-21 | `experiments/results/live_nebius_benchmark.json`: `/v1/models` returned 28 models and the fixed completion succeeded on `nvidia/Nemotron-3_5-Lightning` (96 output tokens, 697.7 ms) |
| Live model IDs and capabilities | VERIFIED on 2026-10-21 | response listed five NVIDIA models; `nvidia/Nemotron-3_5-Lightning` is `text->text` and does not accept images. `nvidia/Nemotron-3.5-Super-VL` reports `text+image->text` |
| Three-arm edit benchmark | **NOT RUN** | automatic approval review rejected the benchmark because it exports task instructions and compact design summaries. It requires the user's explicit approval for that payload |
| Local NVIDIA runtime | VERIFIED for load and one inference call | RTX 4050 Laptop GPU (6140 MiB); the local SketchForge component-detector checkpoint loaded at epoch 5 and returned an inference result. This is not local Nemotron inference, and the saved detector report has mAP 0.0 |
| Local Nemotron weights | **NOT INSTALLED** | the default laptop runtime uses the SketchForge detector; no Nemotron GGUF/AWQ loader or checkpoint is configured |
| ZDR setting | **UNKNOWN** | the Token Factory API does not expose the organisation-level retention setting; confirm it in the Nebius organisation console |
| Local edit baseline | MEASURED | `output/reports/local_edit_benchmark.json`: 34/58 tasks passed (58.62%) |

### Running the live probe

Set `NEBIUS_API_KEY` in the environment (or the ignored local `.env` file), then run `python scripts/verify_nebius.py --enable --accept-egress`. The probe sends only a fixed one-line completion prompt and requests the model list. It writes its result to `experiments/results/live_nebius_benchmark.json` by default; override with `--out`. The report includes model-list status, selected model, latency and token counts, but not the API key or prompt/response contents. ZDR remains `unknown`: the endpoint does not report the organisation-level retention setting.

The NVIDIA local runtime is a separate, on-device path. It loads SketchForge's trained component detector from generated local checkpoints; that checkpoint has a reported mAP of 0.0, so successful loading and inference do not establish useful detector accuracy. It is not a Nemotron runtime. The hosted Token Factory client is the verified Nemotron path. Do not describe local detector inference as local Nemotron inference.

The full remote edit benchmark is a distinct data export from the fixed probe: it sends benchmark instructions and compact synthetic design summaries for each model/hybrid task. Automatic approval review rejected that run; it remains pending explicit user approval. The offline local arm is recorded separately and does not validate model-assisted or hybrid scores.
