#!/usr/bin/env python3
"""Tests for the FAL.ai image generation plugin.

The plugin is a thin registration adapter — actual FAL pipeline logic
lives in ``tools.image_generation_tool`` and is exercised by
``tests/tools/test_image_generation.py``. These tests focus on:

* the ``ImageGenProvider`` ABC surface (name, models, schema)
* call-time indirection (``_it`` resolution at ``generate()`` time so
  ``monkeypatch.setattr(image_tool, ...)`` keeps working)
* response shape stamping (provider/prompt/aspect_ratio/model)
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Provider surface
# ---------------------------------------------------------------------------


class TestFalImageGenProviderSurface:


    def test_default_model_matches_legacy(self):
        from plugins.image_gen.fal import FalImageGenProvider
        from tools.image_generation_catalog import DEFAULT_MODEL

        assert FalImageGenProvider().default_model() == DEFAULT_MODEL

    def test_list_models_uses_legacy_catalog(self):
        from plugins.image_gen.fal import FalImageGenProvider
        from tools.image_generation_catalog import FAL_MODELS

        provider = FalImageGenProvider()
        models = provider.list_models()
        ids = {m["id"] for m in models}
        # Whatever FAL_MODELS ships, the provider mirrors verbatim.
        assert ids == set(FAL_MODELS.keys())
        # Spot-check the expected first-class fields are present.
        for entry in models:
            for field in ("id", "display", "speed", "strengths", "price"):
                assert field in entry





# ---------------------------------------------------------------------------
# generate() — call-time indirection
# ---------------------------------------------------------------------------


class TestFalImageGenProviderGenerate:
    @pytest.mark.parametrize("image_url", [None, "https://example.com/source.png"])
    def test_model_override_selects_requested_endpoint_and_reports_it(self, monkeypatch, image_url):
        import tools.image_generation_tool as image_tool
        from plugins.image_gen.fal import FalImageGenProvider
        from tools.image_generation_catalog import FAL_MODELS

        selected = "fal-ai/nano-banana-pro"
        default = "fal-ai/flux-2/klein/9b"
        calls = []
        monkeypatch.setattr(image_tool, "_resolve_fal_model", lambda: (default, FAL_MODELS[default]))
        monkeypatch.setattr(image_tool, "_debug", MagicMock())
        monkeypatch.setattr(image_tool, "fal_key_is_configured", lambda: True)
        monkeypatch.setattr(image_tool, "_submit_fal_request", lambda endpoint, arguments: calls.append(endpoint))
        monkeypatch.setattr(image_tool, "_wait_fal_result", lambda _request: {"images": [{"url": "https://example.com/a.png"}]})
        monkeypatch.setattr(image_tool, "_format_images", lambda images, *_args: images)

        result = FalImageGenProvider().generate("a lighthouse", model=selected, image_url=image_url)

        assert result["success"] is True
        assert calls == [FAL_MODELS[selected]["edit_endpoint"] if image_url else selected]
        assert result["model"] == selected

    def test_unknown_override_reports_the_configured_fallback(self, monkeypatch):
        import tools.image_generation_tool as image_tool
        from plugins.image_gen.fal import FalImageGenProvider
        from tools.image_generation_catalog import FAL_MODELS

        default = "fal-ai/flux-2/klein/9b"
        calls = []
        monkeypatch.setattr(image_tool, "_resolve_fal_model", lambda: (default, FAL_MODELS[default]))
        monkeypatch.setattr(image_tool, "_debug", MagicMock())
        monkeypatch.setattr(image_tool, "fal_key_is_configured", lambda: True)
        monkeypatch.setattr(image_tool, "_submit_fal_request", lambda endpoint, arguments: calls.append(endpoint))
        monkeypatch.setattr(image_tool, "_wait_fal_result", lambda _request: {"images": [{"url": "https://example.com/a.png"}]})
        monkeypatch.setattr(image_tool, "_format_images", lambda images, *_args: images)

        result = FalImageGenProvider().generate("a lighthouse", model="unknown")

        assert result["success"] is True
        assert calls == [default]
        assert result["model"] == default

    def test_generate_delegates_to_legacy_image_generate_tool(self, monkeypatch):
        """Plugin must look up ``image_generate_tool`` at call time so
        ``monkeypatch.setattr(image_tool, "image_generate_tool", ...)``
        takes effect."""
        import tools.image_generation_tool as image_tool
        from plugins.image_gen.fal import FalImageGenProvider

        captured = {}

        def fake_image_generate_tool(prompt, aspect_ratio, **kwargs):
            captured["prompt"] = prompt
            captured["aspect_ratio"] = aspect_ratio
            captured["kwargs"] = kwargs
            return json.dumps({"success": True, "image": "https://fake/image.png"})

        monkeypatch.setattr(image_tool, "image_generate_tool", fake_image_generate_tool)
        monkeypatch.setattr(image_tool, "_resolve_fal_model",
                            lambda: ("fal-ai/flux-2/klein/9b", {}))

        result = FalImageGenProvider().generate(
            "a serene mountain landscape",
            aspect_ratio="square",
            seed=42,
        )

        assert captured["prompt"] == "a serene mountain landscape"
        assert captured["aspect_ratio"] == "square"
        assert captured["kwargs"] == {"seed": 42}
        assert result["success"] is True
        assert result["image"] == "https://fake/image.png"
        # Stamped fields for the unified response shape
        assert result["provider"] == "fal"
        assert result["prompt"] == "a serene mountain landscape"
        assert result["aspect_ratio"] == "square"
        assert result["model"] == "fal-ai/flux-2/klein/9b"


# ---------------------------------------------------------------------------
# Registry wiring
# ---------------------------------------------------------------------------


class TestFalImageGenPluginRegistration:
    def test_register_wires_provider_into_registry(self):
        from plugins.image_gen.fal import FalImageGenProvider, register

        ctx = MagicMock()
        register(ctx)

        ctx.register_image_gen_provider.assert_called_once()
        (registered,), _ = ctx.register_image_gen_provider.call_args
        assert isinstance(registered, FalImageGenProvider)
