"""
Text Normalizer.

Normalizes dates, units, numbers, and other entities in extracted text.
"""

import re
from datetime import datetime
from typing import Dict, List, Tuple, Optional
import logging

logger = logging.getLogger(__name__)


class Normalizer:
    """Normalize extracted text for consistent indexing and search."""

    # Date patterns (various formats)
    DATE_PATTERNS = [
        (r'\b(\d{1,2})/(\d{1,2})/(\d{4})\b', 'mdy'),  # MM/DD/YYYY
        (r'\b(\d{4})-(\d{2})-(\d{2})\b', 'iso'),      # YYYY-MM-DD (ISO)
        (r'\b(\d{1,2})-(\w{3})-(\d{2,4})\b', 'dmy'),  # DD-MMM-YY(YY)
        (r'\b(\w+)\s+(\d{1,2}),?\s+(\d{4})\b', 'mdy_text'),  # November 14, 2025
    ]

    # Unit conversions (imperial <-> metric)
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
        Normalize text and extract structured metadata.

        Args:
            text: Raw extracted text

        Returns:
            Tuple of (normalized_text, metadata_dict)
        """
        normalized = text
        metadata = {
            "dates": [],
            "measurements": [],
            "entities": [],
        }

        # Normalize dates
        dates_found = self._extract_and_normalize_dates(text)
        metadata["dates"] = dates_found

        # Normalize measurements (numbers + units)
        measurements_found = self._extract_and_normalize_measurements(text)
        metadata["measurements"] = measurements_found

        # Normalize numbers (remove commas, handle parentheses for negatives)
        normalized = self._normalize_numbers(normalized)

        return normalized, metadata

    def _extract_and_normalize_dates(self, text: str) -> List[Dict]:
        """Extract and normalize dates to ISO 8601."""
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

    def _extract_and_normalize_measurements(self, text: str) -> List[Dict]:
        """Extract measurements (number + unit) and convert to metric."""
        measurements = []

        # Pattern: number + unit (e.g., "3.5 feet", "12 inches", "5-7 ft")
        pattern = r'(\d+(?:\.\d+)?(?:\s*-\s*\d+(?:\.\d+)?)?)\s*(feet|ft|inches|in|yards|yd|miles|mi|meters?|m)\b'
        matches = re.finditer(pattern, text, re.IGNORECASE)

        for match in matches:
            value_str, unit = match.groups()
            unit_lower = unit.lower().rstrip('s')  # normalize plural

            # Handle ranges (e.g., "3-5 ft")
            if '-' in value_str:
                parts = value_str.split('-')
                value = (float(parts[0]) + float(parts[1])) / 2  # take average
                is_range = True
            else:
                value = float(value_str)
                is_range = False

            # Convert to metric if imperial unit
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

    def _normalize_numbers(self, text: str) -> str:
        """Normalize number formats (remove commas, handle parentheses for negatives)."""
        # Remove commas from numbers
        text = re.sub(r'(\d),(\d)', r'\1\2', text)

        # Convert (123) to -123 (accounting notation)
        text = re.sub(r'\((\d+(?:\.\d+)?)\)', r'-\1', text)

        return text


# TODO: Add entity extraction (contractors, locations) with NER model
# TODO: Normalize phone numbers, emails, addresses
