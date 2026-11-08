import json
import sys
from types import SimpleNamespace

import pytest
from PIL import Image

from app.core.config import settings
from app.rag.parser.ocr_engine import OcrEngine, PaddleOcrEngine, TesseractOcrEngine


def test_default_engine_is_tesseract(monkeypatch):
    monkeypatch.setattr(settings, "ocr_engine", "tesseract")

    assert isinstance(OcrEngine()._backend, TesseractOcrEngine)


def test_paddle_must_be_selected_explicitly(monkeypatch):
    monkeypatch.setattr(settings, "ocr_engine", "paddle")

    assert isinstance(OcrEngine()._backend, PaddleOcrEngine)


def test_paddle_backend_uses_orientation_and_cpu_settings(monkeypatch):
    captured = {}

    def fake_paddle_ocr(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setitem(sys.modules, "paddleocr", SimpleNamespace(PaddleOCR=fake_paddle_ocr))
    monkeypatch.setattr(settings, "paddle_ocr_use_doc_orientation", True)
    monkeypatch.setattr(settings, "paddle_ocr_enable_mkldnn", False)
    backend = PaddleOcrEngine()

    backend._get_ocr()

    assert captured["use_doc_orientation_classify"] is True
    assert captured["enable_mkldnn"] is False


def test_unknown_engine_fails_with_configuration_error(monkeypatch):
    monkeypatch.setattr(settings, "ocr_engine", "unknown")

    with pytest.raises(ValueError, match="OCR_ENGINE"):
        OcrEngine()


def test_paddle_result_fields_accept_result_wrapper():
    result = SimpleNamespace(json={"res": {"rec_texts": ["第一条", "第二条"], "rec_scores": [0.9, 0.7]}})

    texts, scores = PaddleOcrEngine._result_fields(result)

    assert texts == ["第一条", "第二条"]
    assert scores == [0.9, 0.7]


def test_paddle_confidence_is_scaled_and_cache_is_engine_specific():
    backend = PaddleOcrEngine()
    backend._ocr = SimpleNamespace(predict=lambda **_: [{"rec_texts": ["第一条"], "rec_scores": [0.87]}])

    class MemoryCache:
        payload = json.dumps({"engine": "tesseract", "format_version": 3, "paragraphs": ["old"], "avg_conf": 99})

        def exists(self):
            return True

        def read_text(self, **_):
            return self.payload

        @property
        def parent(self):
            return self

        def mkdir(self, **_):
            pass

        def write_text(self, payload, **_):
            self.payload = payload

    cache = MemoryCache()

    paragraphs, confidence = backend.ocr_image(Image.new("RGB", (20, 20)), cache)

    assert paragraphs == ["第一条"]
    assert confidence == pytest.approx(87.0)
    cached = json.loads(cache.payload)
    assert cached["engine"] == "paddle"
    assert cached["config"]["det_model"] == settings.paddle_ocr_det_model
    assert cached["paragraphs"] == paragraphs


def test_paddle_unavailable_is_reported_without_tesseract_fallback(monkeypatch):
    backend = PaddleOcrEngine()
    monkeypatch.setattr(backend, "_get_ocr", lambda: (_ for _ in ()).throw(RuntimeError("PaddleOCR 未安装")))

    ok, detail = backend.available()

    assert not ok
    assert "PaddleOCR 未安装" in detail
