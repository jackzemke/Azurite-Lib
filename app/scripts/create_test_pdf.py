#!/usr/bin/env python3
"""
Generate a test PDF document for validation.
"""

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from pathlib import Path

def create_test_pdf():
    """Create a sample PDF with construction project data."""
    
    # Ensure directory exists
    output_dir = Path("data/raw_docs/demo_project")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_file = output_dir / "sample_report.pdf"
    
    # Create PDF
    doc = SimpleDocTemplate(str(output_file), pagesize=letter)
    styles = getSampleStyleSheet()
    story = []
    
    # Title
    title = Paragraph("<b>CONSTRUCTION PROJECT REPORT</b>", styles['Title'])
    story.append(title)
    story.append(Spacer(1, 12))
    
    subtitle = Paragraph("<b>Las Cruces City College - Drainage System</b>", styles['Heading2'])
    story.append(subtitle)
    story.append(Spacer(1, 24))
    
    # Content
    content = [
        ("<b>PROJECT OVERVIEW</b>", ""),
        ("", "This report documents the drainage ditch construction completed in November 2022 at Las Cruces City College. The contractor was Southwest Earthworks LLC."),
        
        ("<b>EXCAVATION DETAILS</b>", ""),
        ("", "The drainage ditch was excavated to a depth of 4.5 feet (approximately 1.37 meters). The width measured 8 feet at the top and 3 feet at the bottom."),
        
        ("<b>MATERIALS</b>", ""),
        ("", "PVC pipes with diameter of 12 inches were installed for the main drainage line. Gravel backfill of 6-8 inches was applied around all pipe sections."),
        
        ("<b>SUBGRADE COMPACTION</b>", ""),
        ("", "Subgrade compaction testing was performed by the contractor on November 15, 2022. All tests passed with compaction ratios exceeding 95%."),
        
        ("<b>COMPLETION</b>", ""),
        ("", "The project was completed on November 30, 2022 within budget and schedule. Total project cost was $125,000 USD."),
        
        ("<b>SAFETY RECORD</b>", ""),
        ("", "Zero accidents were reported during the construction period. All OSHA safety requirements were met or exceeded."),
    ]
    
    for heading, text in content:
        if heading:
            p = Paragraph(heading, styles['Heading3'])
            story.append(p)
            story.append(Spacer(1, 12))
        if text:
            p = Paragraph(text, styles['Normal'])
            story.append(p)
            story.append(Spacer(1, 18))
    
    # Build PDF
    doc.build(story)
    
    print(f"Created test PDF: {output_file}")
    print(f"File size: {output_file.stat().st_size} bytes")

if __name__ == "__main__":
    create_test_pdf()
