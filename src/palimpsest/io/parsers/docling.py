"""Docling parser — ML layout analysis, GPU-friendly. OCR disabled (text layer exists).

Install via: `uv sync --extra pilot-docling` on the GPU host.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from .base import ParseResult

logging.basicConfig(level=logging.INFO)


class DoclingParser:
    name = "docling"

    def parse(self, pdf_path: Path, out_dir: Path) -> ParseResult:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import (
            PdfPipelineOptions,
            smolvlm_picture_description,
        )
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling_core.types.doc import ImageRefMode

        out_dir.mkdir(parents=True, exist_ok=True)
        images_dir = out_dir / "images"
        images_dir.mkdir(exist_ok=True)
        md_path = out_dir / "output.md"

        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = False
        pipeline_options.generate_picture_images = True
        pipeline_options.images_scale = 2.0
        # SmolVLM-256M: lightweight local VLM; describes image content as alt-text in markdown
        pipeline_options.do_picture_description = True
        pipeline_options.picture_description_options = smolvlm_picture_description

        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
            }
        )

        t0 = time.perf_counter()
        result = converter.convert(str(pdf_path))
        elapsed = time.perf_counter() - t0

        result.document.save_as_markdown(
            md_path,
            image_mode=ImageRefMode.REFERENCED,
            artifacts_dir=images_dir,
        )

        return ParseResult(
            parser_name=self.name,
            markdown_path=md_path,
            images_dir=images_dir,
            metadata={"elapsed_s": round(elapsed, 2)},
        )
