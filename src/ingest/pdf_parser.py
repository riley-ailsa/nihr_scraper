"""
PDF text extraction with multiple fallback methods.
Start with PyPDF2, fallback to pdfplumber if needed.
"""

from typing import Optional
import logging
from io import BytesIO
import PyPDF2
import pdfplumber

logger = logging.getLogger(__name__)


class PDFParser:
    """Extract text from PDF bytes with robust error handling."""

    def __init__(self, use_ocr: bool = False):
        self.use_ocr = use_ocr

    def extract_text(self, pdf_bytes: bytes) -> Optional[str]:
        """
        Extract text from PDF bytes using multiple methods.

        Returns None if extraction fails completely.
        """
        # Method 1: PyPDF2 (fastest, works for 90% of PDFs)
        text = self._extract_with_pypdf2(pdf_bytes)
        if text and len(text.strip()) > 100:
            return self._clean_text(text)

        # Method 2: pdfplumber (better for tables/complex layouts)
        text = self._extract_with_pdfplumber(pdf_bytes)
        if text and len(text.strip()) > 100:
            return self._clean_text(text)

        logger.warning("PDF extraction failed")
        return None

    def _extract_with_pypdf2(self, pdf_bytes: bytes) -> Optional[str]:
        try:
            pdf_file = BytesIO(pdf_bytes)
            reader = PyPDF2.PdfReader(pdf_file)

            text_parts = []
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    text_parts.append(text)

            return "\n\n".join(text_parts)
        except Exception as e:
            logger.debug(f"PyPDF2 failed: {e}")
            return None

    def _extract_with_pdfplumber(self, pdf_bytes: bytes) -> Optional[str]:
        try:
            pdf_file = BytesIO(pdf_bytes)
            text_parts = []

            with pdfplumber.open(pdf_file) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        text_parts.append(text)

            return "\n\n".join(text_parts)
        except Exception as e:
            logger.debug(f"pdfplumber failed: {e}")
            return None

    def _clean_text(self, text: str) -> str:
        """Clean extracted text."""
        # Remove excessive whitespace
        lines = [line.strip() for line in text.split('\n')]
        lines = [line for line in lines if line]
        return "\n".join(lines)