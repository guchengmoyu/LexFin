"""OCR 引擎（Tesseract 5 + pytesseract，docs/04 §4）。

预处理链：灰度 → 自适应放大 → OTSU 二值化 → 中值滤波 → 输出 PNG（内存）；
按 block→par→line 聚合还原段落（比裸文本质量高）；
结果缓存于 /data/ocr_cache/{file_md5}/p{page_no}.json。
"""
from __future__ import annotations

import json
import re
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


class OcrEngine:
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
                if cached.get("lang") == self.lang:
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
                current_words.append("")  # 换行占位
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
                        {"lang": self.lang, "paragraphs": paragraphs, "avg_conf": avg_conf},
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


ocr_engine = OcrEngine()
