"""
Text Metadata Extractor.

Extracts structured metadata (dates, measurements) from text without
modifying the original content. Previously called "Normalizer" but the
text normalization was harmful (removing commas from numbers, converting
accounting notation) so it has been repurposed to extraction-only.
"""

import re
from datetime import datetime
from typing import Dict, List, Tuple, Optional
import logging

logger = logging.getLogger(__name__)


class Normalizer:
    """Extract structured metadata from text.

    Note: Despite the class name (kept for backward compatibility),
    this class no longer modifies text. It only extracts metadata.
    """

    # Date patterns (various formats)
    DATE_PATTERNS = [
        (r'\b(\d{1,2})/(\d{1,2})/(\d{4})\b', 'mdy'),  # MM/DD/YYYY
        (r'\b(\d{4})-(\d{2})-(\d{2})\b', 'iso'),      # YYYY-MM-DD (ISO)
        (r'\b(\d{1,2})-(\w{3})-(\d{2,4})\b', 'dmy'),  # DD-MMM-YY(YY)
        (r'\b(\w+)\s+(\d{1,2}),?\s+(\d{4})\b', 'mdy_text'),  # November 14, 2025
    ]

    # Unit patterns for measurement extraction
    UNIT_CONVERSIONS = {
        'feet': {'to_metric': 0.3048, 'unit': 'm'},
        'ft': {'to_metric': 0.3048, 'unit': 'm'},
        'inches': {'to_metric': 0.0254, 'unit': 'm'},
        'in': {'to_metric': 0.0254, 'unit': 'm'},
        'yards': {'to_metric': 0.9144, 'unit': 'm'},
        'yd': {'to_metric': 0.9144, 'unit': 'm'},
        'miles': {'to_metric': 1609.34, 'unit': 'm'},
        'mi': {'to_metric': 1609.34, 'unit': 'm'},
    }

    MONTH_ABBR = {
        'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
        'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
    }

    def normalize_text(self, text: str) -> Tuple[str, Dict]:
        """
        Extract metadata from text. Returns text unchanged.

        This method preserves the original API signature for backward
        compatibility but no longer modifies the text.

        Args:
            text: Raw extracted text

        Returns:
            Tuple of (unchanged_text, metadata_dict)
        """
        metadata = self.extract_metadata(text)
        return text, metadata

    def extract_metadata(self, text: str) -> Dict:
        """
        Extract structured metadata from text.

        Args:
            text: Source text to analyze

        Returns:
            Dict with 'dates', 'measurements', 'entities' lists
        """
        metadata = {
            "dates": [],
            "measurements": [],
            "entities": [],
        }

        metadata["dates"] = self._extract_dates(text)
        metadata["measurements"] = self._extract_measurements(text)

        return metadata

    def _extract_dates(self, text: str) -> List[Dict]:
        """Extract dates and parse to ISO 8601."""
        dates = []

        for pattern, format_type in self.DATE_PATTERNS:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                try:
                    iso_date = self._convert_to_iso(match, format_type)
                    if iso_date:
                        dates.append({
                            "original": match.group(0),
                            "iso": iso_date,
                            "position": match.start(),
                        })
                except Exception as e:
                    logger.debug(f"Failed to parse date '{match.group(0)}': {e}")

        return dates

    def _convert_to_iso(self, match: re.Match, format_type: str) -> Optional[str]:
        """Convert date match to ISO 8601 format."""
        try:
            if format_type == 'mdy':
                month, day, year = match.groups()
                dt = datetime(int(year), int(month), int(day))
            elif format_type == 'iso':
                year, month, day = match.groups()
                dt = datetime(int(year), int(month), int(day))
            elif format_type == 'dmy':
                day, month_str, year = match.groups()
                month = self.MONTH_ABBR.get(month_str[:3].lower(), None)
                if not month:
                    return None
                year_int = int(year)
                if year_int < 100:
                    year_int += 2000 if year_int < 50 else 1900
                dt = datetime(year_int, month, int(day))
            elif format_type == 'mdy_text':
                month_str, day, year = match.groups()
                month = self.MONTH_ABBR.get(month_str[:3].lower(), None)
                if not month:
                    return None
                dt = datetime(int(year), month, int(day))
            else:
                return None

            return dt.strftime('%Y-%m-%d')

        except Exception:
            return None

    def _extract_measurements(self, text: str) -> List[Dict]:
        """Extract measurements (number + unit) with metric conversion."""
        measurements = []

        pattern = r'(\d+(?:\.\d+)?(?:\s*-\s*\d+(?:\.\d+)?)?)\s*(feet|ft|inches|in|yards|yd|miles|mi|meters?|m)\b'
        matches = re.finditer(pattern, text, re.IGNORECASE)

        for match in matches:
            value_str, unit = match.groups()
            unit_lower = unit.lower().rstrip('s')

            if '-' in value_str:
                parts = value_str.split('-')
                value = (float(parts[0].strip()) + float(parts[1].strip())) / 2
                is_range = True
            else:
                value = float(value_str)
                is_range = False

            if unit_lower in self.UNIT_CONVERSIONS:
                conversion = self.UNIT_CONVERSIONS[unit_lower]
                metric_value = value * conversion['to_metric']
                metric_unit = conversion['unit']
            else:
                metric_value = value
                metric_unit = unit_lower

            measurements.append({
                "original": match.group(0),
                "value": value,
                "unit": unit,
                "metric_value": round(metric_value, 3),
                "metric_unit": metric_unit,
                "is_range": is_range,
                "position": match.start(),
            })

        return measurements
