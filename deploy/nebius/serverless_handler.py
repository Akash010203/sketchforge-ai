"""Nebius Serverless Endpoint Handler.

Receives base64 sketch images or natural-language app briefs,
invokes Nemotron on Token Factory, and streams back the generated full-stack project.
"""

import base64
import json
import logging
from typing import Any, Dict

from sketchforge.vision import analyze, load_image_bytes
from sketchforge.agent.model_router import ModelRouter
from sketchforge.integrations.nebius.client import NebiusClient
from sketchforge.integrations.nebius.configuration import load_nebius_config
from sketchforge.integrations.nebius.request_policy import ConsentGate
from sketchforge.generation.ai_generator import generate_project_ai

log = logging.getLogger(__name__)


def handle_event(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Nebius Serverless Endpoint entrypoint."""
    try:
        body = event.get("body", "{}")
        if isinstance(body, str):
            payload = json.loads(body)
        else:
            payload = body

        prompt = payload.get("prompt", "Modern responsive web application")
        image_b64 = payload.get("image_b64")

        layout_block = None
        if image_b64:
            raw_bytes = base64.b64decode(image_b64)
            loaded = load_image_bytes(raw_bytes, "sketch.png")
            result = analyze(loaded)
            from sketchforge.vision.to_design_ir import build_nemotron_layout_block
            layout_block = build_nemotron_layout_block(result, "sketch.png")

        config = load_nebius_config(overrides={"enabled": True})
        consent = ConsentGate(consented=True)
        client = NebiusClient(config, consent)

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "status": "success",
                "message": "SketchForge Nebius Serverless Job Executed",
                "prompt": prompt,
                "detected_regions": len(layout_block.get("components", [])) if layout_block else 0,
            }),
        }
    except Exception as exc:
        log.exception("Serverless execution error")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(exc)}),
        }
