"""
Image OCR Extractor using Tesseract.

Handles scanned PDFs (converted to images) and standalone image files.
"""

import pytesseract
from PIL import Image
from pathlib import Path
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class ImageOCR:
    """Perform OCR on images using Tesseract."""

    def __init__(self, lang: str = "eng"):
        """
        Initialize OCR engine.

        Args:
            lang: Tesseract language code (default: 'eng')
        """
        self.lang = lang

        # Verify Tesseract is installed
        try:
            pytesseract.get_tesseract_version()
        except Exception as e:
            logger.warning(f"Tesseract not found or not configured: {e}")

    def extract_from_image(self, image_path: Path) -> Dict:
        """
        Extract text from a single image file.

        Args:
            image_path: Path to image file (PNG, JPG, TIFF, etc.)

        Returns:
            Dict with:
                - text: Extracted text
                - confidence: Average OCR confidence (0-100)
                - bbox_available: bool (always False for now)
        """
        try:
            image = Image.open(image_path)

            # Perform OCR
            text = pytesseract.image_to_string(image, lang=self.lang)

            # Get confidence data (word-level)
            data = pytesseract.image_to_data(image, lang=self.lang, output_type=pytesseract.Output.DICT)
            confidences = [int(conf) for conf in data["conf"] if int(conf) > 0]
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

            return {
                "text": text.strip(),
                "confidence": avg_confidence,
                "bbox_available": False,
            }

        except Exception as e:
            logger.error(f"Failed to OCR image {image_path}: {e}")
            raise

    def extract_from_pdf_page_image(self, image: Image.Image) -> Dict:
        """
        Extract text from a PIL Image object (e.g., PDF page converted to image).

        Args:
            image: PIL Image object

        Returns:
            Dict with:
                - text: Extracted text
                - confidence: Average OCR confidence
        """
        try:
            text = pytesseract.image_to_string(image, lang=self.lang)

            data = pytesseract.image_to_data(image, lang=self.lang, output_type=pytesseract.Output.DICT)
            confidences = [int(conf) for conf in data["conf"] if int(conf) > 0]
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

            return {
                "text": text.strip(),
                "confidence": avg_confidence,
            }

        except Exception as e:
            logger.error(f"Failed to OCR image object: {e}")
            raise

    def extract_standalone_image(self, file_path: Path) -> Dict:
        """
        Extract text from a standalone image file (simulates one-page document).

        Args:
            file_path: Path to image file

        Returns:
            Dict with:
                - pages: List with single page dict
                - total_pages: 1
                - requires_ocr: False (already OCRed)
                - metadata: dict
        """
        result = self.extract_from_image(file_path)

        return {
            "pages": [{
                "page_num": 1,
                "text": result["text"],
                "bbox_available": False,
                "width": None,
                "height": None,
                "ocr_confidence": result["confidence"],
            }],
            "total_pages": 1,
            "requires_ocr": False,
            "metadata": {
                "ocr_confidence": result["confidence"],
            },
        }


# TODO: Consider PaddleOCR for handwritten text or complex layouts
# TODO: Add image preprocessing (deskew, denoise) for better OCR accuracy
