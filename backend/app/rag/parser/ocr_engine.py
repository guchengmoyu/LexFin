"""OCR 引擎（Tesseract 5 + pytesseract，docs/04 §4）。

预处理链：灰度 → 自适应放大 → OTSU 二值化 → 中值滤波 → 输出 PNG（内存）；
按 block→par→line 聚合还原段落（比裸文本质量高）；
结果缓存于 /data/ocr_cache/{file_md5}/p{page_no}.json。
"""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import List, Optional, Tuple

from loguru import logger

from app.core.config import settings

try:
    import pytesseract
    from PIL import Image
except ImportError:  # pragma: no cover - OCR 依赖缺失时由健康检查暴露
    pytesseract = None  # type: ignore
    Image = None  # type: ignore


class TesseractOcrEngine:
    def __init__(self) -> None:
        self.lang = settings.ocr_lang
        self.dpi = settings.ocr_dpi
        self.psm = settings.ocr_psm
        self.oem = settings.ocr_oem

    # ------------------------------------------------------------------ 探测
    def available(self) -> Tuple[bool, str]:
        if pytesseract is None:
            return False, "pytesseract 未安装"
        try:
            version = pytesseract.get_tesseract_version()
            langs = pytesseract.get_languages(config="")
            return True, f"Tesseract {version} ({','.join(langs)})"
        except Exception as exc:
            return False, str(exc)

    # ------------------------------------------------------------- 预处理链
    def preprocess(self, image: "Image.Image") -> "Image.Image":
        img = image.convert("L")  # 灰度化
        # 自适应放大：短边 < 2000px 时放大到长边 ≈ 2500px
        w, h = img.size
        if max(w, h) < 2500 and min(w, h) < 2000:
            scale = 2500 / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        try:
            import cv2
            import numpy as np

            arr = np.array(img)
            arr = cv2.threshold(arr, 0, 255, cv2.THRESH_OTSU + cv2.THRESH_BINARY)[1]
            arr = cv2.medianBlur(arr, 3)
            img = Image.fromarray(arr)
        except Exception:  # OpenCV 可选；缺失时保留灰度图
            pass
        return img

    # ---------------------------------------------------------------- OCR 主流程
    def ocr_image(self, image: "Image.Image", cache_path: Optional[Path] = None) -> Tuple[List[str], float]:
        """返回 (段落列表, 平均置信度 0~100)。"""
        if pytesseract is None:
            raise RuntimeError("OCR 引擎不可用：pytesseract 未安装")

        if cache_path and cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                cache_config = {"lang": self.lang, "dpi": self.dpi, "psm": self.psm, "oem": self.oem}
                if cached.get("engine") == "tesseract" and cached.get("config") == cache_config and cached.get("format_version") == 3:
                    return cached["paragraphs"], cached["avg_conf"]
            except Exception:
                pass

        processed = self.preprocess(image)
        config = f"--oem {self.oem} --psm {self.psm} -c preserve_interword_spaces=1"
        data = pytesseract.image_to_data(
            processed, lang=self.lang, config=config, output_type=pytesseract.Output.DICT
        )

        # block → par → line 聚合还原段落
        paragraphs: List[str] = []
        current_key: Optional[tuple] = None
        current_line: Optional[int] = None
        current_words: List[str] = []
        confidences: List[float] = []
        for i, word in enumerate(data["text"]):
            word = (word or "").strip()
            conf = float(data["conf"][i])
            if not word or conf < 0:
                continue
            confidences.append(conf)
            key = (data["block_num"][i], data["par_num"][i])
            if key != current_key:
                if current_words:
                    paragraphs.append("".join(current_words))
                current_words = []
                current_key = key
                current_line = None
            line_key = data["line_num"][i]
            if current_words and line_key != current_line:
                current_words.append("\n")  # 保留条文行边界
            current_line = line_key
            current_words.append(word)
        if current_words:
            paragraphs.append("".join(current_words))

        paragraphs = [re.sub(r"[ \t]+", " ", p).strip() for p in paragraphs if p.strip()]
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0

        if cache_path:
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(
                    json.dumps(
                        {
                            "engine": "tesseract",
                            "config": {"lang": self.lang, "dpi": self.dpi, "psm": self.psm, "oem": self.oem},
                            "format_version": 3,
                            "paragraphs": paragraphs,
                            "avg_conf": avg_conf,
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            except Exception as exc:
                logger.warning("OCR 缓存写入失败: {}", exc)
        return paragraphs, avg_conf

    def quality_check(self, text: str, avg_conf: float) -> Optional[str]:
        """docs/04 §4.5 质量兜底：返回告警文案或 None（不阻断入库）。"""
        cn = len(re.findall(r"[\u4e00-\u9fa5]", text or ""))
        non_space = max(1, len(re.sub(r"\s", "", text or "")))
        cn_ratio = cn / non_space
        if avg_conf < settings.ocr_min_confidence or cn_ratio < 0.30:
            return (
                f"OCR 识别质量偏低（置信度 {avg_conf:.0f}），建议人工校对关键条文"
            )
        return None


class PaddleOcrEngine:
    """Optional PaddleOCR 3 backend. Paddle dependencies load only when selected."""

    def __init__(self) -> None:
        self._ocr = None
        self._lock = threading.RLock()

    def _get_ocr(self):
        if self._ocr is None:
            with self._lock:
                if self._ocr is None:
                    os.environ["PADDLE_PDX_CACHE_HOME"] = settings.paddle_ocr_cache_dir
                    try:
                        from paddleocr import PaddleOCR
                    except ImportError as exc:
                        raise RuntimeError("PaddleOCR 未安装；请安装 backend/requirements-ocr-paddle.txt") from exc
                    self._ocr = PaddleOCR(
                        text_detection_model_name=settings.paddle_ocr_det_model,
                        text_recognition_model_name=settings.paddle_ocr_rec_model,
                        use_doc_orientation_classify=False,
                        use_doc_unwarping=False,
                        use_textline_orientation=False,
                        device=settings.paddle_ocr_device,
                        cpu_threads=settings.paddle_ocr_cpu_threads,
                        enable_mkldnn=settings.paddle_ocr_enable_mkldnn,
                    )
        return self._ocr

    def available(self) -> Tuple[bool, str]:
        try:
            self._get_ocr()
            return True, f"PaddleOCR {settings.paddle_ocr_det_model}+{settings.paddle_ocr_rec_model} ({settings.paddle_ocr_device})"
        except Exception as exc:
            return False, str(exc)

    @staticmethod
    def _result_fields(result) -> Tuple[List[str], List[float]]:
        """Read PaddleOCR 3 result dictionaries and their JSON-compatible wrapper."""
        if hasattr(result, "json"):
            result = result.json
            if callable(result):
                result = result()
        if isinstance(result, dict) and "res" in result:
            result = result["res"]
        if not isinstance(result, dict):
            return [], []
        texts = result.get("rec_texts")
        scores = result.get("rec_scores")
        texts = [] if texts is None else list(texts)
        scores = [] if scores is None else list(scores)
        return [str(text).strip() for text in texts if str(text).strip()], [float(score) for score in scores]

    def ocr_image(self, image: "Image.Image", cache_path: Optional[Path] = None) -> Tuple[List[str], float]:
        if cache_path and cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                cache_config = {
                    "det_model": settings.paddle_ocr_det_model,
                    "rec_model": settings.paddle_ocr_rec_model,
                    "device": settings.paddle_ocr_device,
                }
                if cached.get("engine") == "paddle" and cached.get("config") == cache_config and cached.get("format_version") == 3:
                    return cached["paragraphs"], cached["avg_conf"]
            except Exception:
                pass

        import numpy as np

        with self._lock:
            results = self._get_ocr().predict(input=np.asarray(image.convert("RGB")))
        paragraphs: List[str] = []
        confidences: List[float] = []
        for result in results or []:
            texts, scores = self._result_fields(result)
            paragraphs.extend(texts)
            confidences.extend(scores)
        avg_conf = (sum(confidences) / len(confidences) * 100) if confidences else 0.0
        if cache_path:
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(
                    json.dumps(
                        {
                            "engine": "paddle",
                            "config": {
                                "det_model": settings.paddle_ocr_det_model,
                                "rec_model": settings.paddle_ocr_rec_model,
                                "device": settings.paddle_ocr_device,
                            },
                            "format_version": 3,
                            "paragraphs": paragraphs,
                            "avg_conf": avg_conf,
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            except Exception as exc:
                logger.warning("OCR 缓存写入失败: {}", exc)
        return paragraphs, avg_conf

    def quality_check(self, text: str, avg_conf: float) -> Optional[str]:
        return _quality_check(text, avg_conf)


def _quality_check(text: str, avg_conf: float) -> Optional[str]:
    cn = len(re.findall(r"[\u4e00-\u9fa5]", text or ""))
    non_space = max(1, len(re.sub(r"\s", "", text or "")))
    if avg_conf < settings.ocr_min_confidence or cn / non_space < 0.30:
        return f"OCR 识别质量偏低（置信度 {avg_conf:.0f}），建议人工校对关键条文"
    return None


class OcrEngine:
    """Stable parser-facing facade; Tesseract remains the default engine."""

    def __init__(self) -> None:
        engine = settings.ocr_engine.strip().lower()
        if engine == "tesseract":
            self._backend = TesseractOcrEngine()
        elif engine == "paddle":
            self._backend = PaddleOcrEngine()
        else:
            raise ValueError(f"OCR_ENGINE must be 'tesseract' or 'paddle', got {settings.ocr_engine!r}")

    def available(self) -> Tuple[bool, str]:
        return self._backend.available()

    def ocr_image(self, image: "Image.Image", cache_path: Optional[Path] = None) -> Tuple[List[str], float]:
        return self._backend.ocr_image(image, cache_path)

    def quality_check(self, text: str, avg_conf: float) -> Optional[str]:
        return self._backend.quality_check(text, avg_conf)


ocr_engine = OcrEngine()
