"""Compare the configured PaddleOCR and Tesseract engines on scanned PDFs."""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path

import numpy as np
import pytesseract
import pymupdf as fitz
from PIL import Image
from pytesseract import Output


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def tesseract_page(image: Image.Image, rotate: int = 0) -> tuple[str, float]:
    if rotate:
        image = image.rotate(rotate, expand=True)
    gray = image.convert("L")
    width, height = gray.size
    if max(width, height) < 2500 and min(width, height) < 2000:
        scale = 2500 / max(width, height)
        gray = gray.resize((int(width * scale), int(height * scale)), Image.Resampling.LANCZOS)
    data = pytesseract.image_to_data(
        gray,
        lang="chi_sim+eng",
        config="--oem 1 --psm 6 -c preserve_interword_spaces=1",
        output_type=Output.DICT,
    )
    words: list[str] = []
    scores: list[float] = []
    previous_line = None
    for i, raw_word in enumerate(data["text"]):
        word = (raw_word or "").strip()
        score = float(data["conf"][i])
        if not word or score < 0:
            continue
        line = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        if words and line != previous_line:
            words.append("\n")
        words.append(word)
        scores.append(score)
        previous_line = line
    return "".join(words), (sum(scores) / len(scores) if scores else 0.0)


def paddle_page(ocr, image: Image.Image) -> tuple[str, float, int | None]:
    result_list = ocr.predict(input=np.asarray(image.convert("RGB"))) or []
    texts: list[str] = []
    scores: list[float] = []
    angle = None
    for result in result_list:
        result = result.json
        if callable(result):
            result = result()
        result = result.get("res", result) if isinstance(result, dict) else {}
        angle = (result.get("doc_preprocessor_res") or {}).get("angle", angle)
        texts.extend(str(text).strip() for text in result.get("rec_texts", []) if str(text).strip())
        scores.extend(float(score) for score in result.get("rec_scores", []))
    return "\n".join(texts), (sum(scores) / len(scores) * 100 if scores else 0.0), angle


def evaluate(pdf_path: Path, ocr, dpi: int, selected_pages: set[int] | None, tess_rotate: int) -> list[dict]:
    rows = []
    with fitz.open(pdf_path) as document:
        for page_index, page in enumerate(document):
            if selected_pages is not None and page_index + 1 not in selected_pages:
                continue
            image = Image.open(__import__("io").BytesIO(page.get_pixmap(dpi=dpi).tobytes("png")))
            started = time.perf_counter()
            paddle_text, paddle_conf, paddle_angle = paddle_page(ocr, image)
            paddle_seconds = time.perf_counter() - started
            started = time.perf_counter()
            tess_text, tess_conf = tesseract_page(image, tess_rotate)
            tess_seconds = time.perf_counter() - started
            rows.append(
                {
                    "page": page_index + 1,
                    "paddle_text": paddle_text,
                    "paddle_confidence": round(paddle_conf, 2),
                    "paddle_detected_angle": paddle_angle,
                    "tesseract_rotation": tess_rotate,
                    "paddle_seconds": round(paddle_seconds, 2),
                    "tesseract_text": tess_text,
                    "tesseract_confidence": round(tess_conf, 2),
                    "tesseract_seconds": round(tess_seconds, 2),
                    "normalized_similarity": round(
                        __import__("difflib").SequenceMatcher(
                            None, normalize_text(paddle_text), normalize_text(tess_text), autojunk=False
                        ).ratio(),
                        4,
                    ),
                }
            )
            print(
                f"{pdf_path.name}: {page_index + 1}/{len(document)} "
                f"Paddle={paddle_seconds:.1f}s Tesseract={tess_seconds:.1f}s",
                flush=True,
            )
    return rows


def write_report(pdf_path: Path, rows: list[dict], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{pdf_path.stem}.json"
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [f"# OCR 对照：{pdf_path.name}", "", "置信分数是各引擎内部评分，未经校准；文本相似度只衡量两种输出的一致性，不等于识别正确率。", ""]
    lines.append("| 页 | Paddle 角度 | Paddle 置信度 | Paddle 秒 | Tesseract 置信度 | Tesseract 秒 | 输出相似度 |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|")
    for row in rows:
        lines.append(
            f"| {row['page']} | {row['paddle_detected_angle']} | {row['paddle_confidence']} | {row['paddle_seconds']} | "
            f"{row['tesseract_confidence']} | {row['tesseract_seconds']} | {row['normalized_similarity']} |"
        )
    for row in rows:
        lines.extend(
            [
                "",
                f"## 第 {row['page']} 页",
                "",
                "### PaddleOCR",
                "",
                "```text",
                row["paddle_text"],
                "```",
                "",
                "### Tesseract",
                "",
                "```text",
                row["tesseract_text"],
                "```",
            ]
        )
    (output_dir / f"{pdf_path.stem}.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tesseract", type=Path, required=True)
    parser.add_argument("--model-cache", type=Path, required=True)
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--pages", type=int, nargs="+", help="Optional 1-based pages to evaluate")
    parser.add_argument("--doc-orientation", action="store_true", help="Enable Paddle's document orientation classifier")
    parser.add_argument("--tesseract-rotate", type=int, choices=(0, 90, 180, 270), default=0)
    args = parser.parse_args()

    os.environ["PADDLE_PDX_CACHE_HOME"] = str(args.model_cache)
    pytesseract.pytesseract.tesseract_cmd = str(args.tesseract)
    from paddleocr import PaddleOCR

    ocr = PaddleOCR(
        text_detection_model_name="PP-OCRv5_mobile_det",
        text_recognition_model_name="PP-OCRv5_mobile_rec",
        use_doc_orientation_classify=args.doc_orientation,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        device="cpu",
        cpu_threads=4,
        enable_mkldnn=False,
    )
    for pdf_path in args.pdf:
        rows = evaluate(pdf_path, ocr, args.dpi, set(args.pages) if args.pages else None, args.tesseract_rotate)
        write_report(pdf_path, rows, args.output)
        print(f"Report: {args.output / (pdf_path.stem + '.md')}", flush=True)


if __name__ == "__main__":
    main()
