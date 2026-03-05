"""
Create mock network drive directory structures for development/testing.

Creates fake project directories under data/mock_drives/ so the DirectoryIndex
can be tested without real SMB network mounts.

Run:
    python app/scripts/create_mock_drives.py

After running, update config.yaml to point to the mock drives:

    network_drives:
      db_path: "data/index/directory_index.db"
      drives:
        - name: "S Drive (Mock)"
          mount_path: "data/mock_drives/s_drive"
          drive_letter: "S"
          has_department_level: true
        - name: "P Drive (Mock)"
          mount_path: "data/mock_drives/p_drive"
          drive_letter: "P"
          has_department_level: false
"""

import sys
from pathlib import Path

# Resolve base directory (project root)
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
MOCK_BASE = PROJECT_ROOT / "data" / "mock_drives"

# S Drive: 3-level (Drive > Department > Project)
S_DRIVE_PROJECTS = {
    "Environmental": [
        "Las Vegas Transfer Station (1430152)",
        "NMED Acomita Day School (1A29514)",
        "Albuquerque Wastewater Reclamation (1180023)",
        "Farmington Methane Mitigation (1210056)",
        "Navajo Nation Water Quality Study (1250078)",
        "Los Alamos Groundwater Monitoring (1310099)",
        "Carlsbad Brine Well Remediation (1360034)",
    ],
    "Geotechnical": [
        "I-25 Bridge Replacement (1133234)",
        "Rio Rancho Soil Study (1150001)",
        "Santa Fe Railroad Overpass (1190045)",
        "Bernalillo County Retaining Wall (1220067)",
        "Taos Ski Valley Road Stabilization (1280012)",
        "Las Cruces Dam Foundation (1320089)",
    ],
    "Construction": [
        "Mesa Verde Visitor Center (1270089)",
        "Roswell Industrial Park Phase 2 (1300056)",
        "Gallup Community Center Expansion (1350023)",
        "Silver City Water Treatment Plant (1380045)",
        "Ruidoso Fire Station Rebuild (1410067)",
    ],
    "Water Resources": [
        "Rio Grande Flood Control Study (1160034)",
        "Elephant Butte Reservoir Analysis (1200012)",
        "Pecos River Watershed Assessment (1240089)",
        "San Juan Basin Aquifer Mapping (1290078)",
    ],
    "Transportation": [
        "I-40 Corridor Improvement (1170045)",
        "US-550 Safety Enhancement (1230023)",
        "NM-528 Intersection Redesign (1260056)",
        "Paseo del Norte Extension (1340012)",
    ],
}

# P Drive: 2-level (Drive > Project, no department)
# Some projects intentionally duplicate S drive for testing duplicate detection
P_DRIVE_PROJECTS = [
    "Las Vegas Transfer Station (1430152)",       # DUPLICATE of S drive
    "I-25 Bridge Replacement (1133234)",          # DUPLICATE of S drive
    "Mesa Verde Visitor Center (1270089)",         # DUPLICATE of S drive
    "Albuquerque Airport Terminal B (1290045)",
    "Santa Fe Rail Trail Extension (1340067)",
    "Hobbs Oil Field Reclamation (1370023)",
    "Clovis Municipal Water Upgrade (1400056)",
    "Deming Solar Farm Site Assessment (1420034)",
    "Tucumcari Highway Rest Stop (1440078)",
    "Truth or Consequences Spa District (1450012)",
    "Alamogordo Space Museum Expansion (1460089)",
    "Socorro Bridge Rehabilitation (1470045)",
]

# Placeholder files to put in each project directory
PLACEHOLDER_FILES = [
    "report.pdf",
    "site_photos.zip",
    "field_notes.docx",
]

EXTRA_FILES = [
    "specifications.pdf",
    "cost_estimate.xlsx",
    "correspondence/client_email_01.pdf",
    "correspondence/rfi_response.pdf",
    "drawings/site_plan.dwg",
]


def create_mock_drives():
    """Create the full mock directory structure."""
    print(f"Creating mock drives at: {MOCK_BASE}")

    # Clean up existing mock drives
    if MOCK_BASE.exists():
        import shutil
        shutil.rmtree(MOCK_BASE)

    # --- S Drive (3-level) ---
    s_drive = MOCK_BASE / "s_drive"
    project_count_s = 0
    for department, projects in S_DRIVE_PROJECTS.items():
        for project_name in projects:
            project_dir = s_drive / department / project_name
            project_dir.mkdir(parents=True, exist_ok=True)

            # Add placeholder files
            for f in PLACEHOLDER_FILES:
                (project_dir / f).touch()

            # Add extra files to some projects (every other one)
            if project_count_s % 2 == 0:
                for f in EXTRA_FILES:
                    fp = project_dir / f
                    fp.parent.mkdir(parents=True, exist_ok=True)
                    fp.touch()

            project_count_s += 1

    print(f"  S Drive: {project_count_s} projects across {len(S_DRIVE_PROJECTS)} departments")

    # --- P Drive (2-level) ---
    p_drive = MOCK_BASE / "p_drive"
    for project_name in P_DRIVE_PROJECTS:
        project_dir = p_drive / project_name
        project_dir.mkdir(parents=True, exist_ok=True)

        # Add placeholder files
        for f in PLACEHOLDER_FILES:
            (project_dir / f).touch()

    print(f"  P Drive: {len(P_DRIVE_PROJECTS)} projects (no departments)")

    # Count duplicates
    s_ids = set()
    for projects in S_DRIVE_PROJECTS.values():
        for p in projects:
            import re
            match = re.search(r'\((\w+)\)$', p.strip())
            if match:
                s_ids.add(match.group(1))

    p_ids = set()
    for p in P_DRIVE_PROJECTS:
        import re
        match = re.search(r'\((\w+)\)$', p.strip())
        if match:
            p_ids.add(match.group(1))

    duplicates = s_ids & p_ids
    print(f"  Intentional duplicates across drives: {len(duplicates)} ({', '.join(sorted(duplicates))})")

    # Print config snippet
    print()
    print("Add this to your config.yaml to use mock drives:")
    print("=" * 60)
    print(f"""
network_drives:
  db_path: "data/index/directory_index.db"
  drives:
    - name: "S Drive (Mock)"
      mount_path: "{s_drive}"
      drive_letter: "S"
      has_department_level: true
    - name: "P Drive (Mock)"
      mount_path: "{p_drive}"
      drive_letter: "P"
      has_department_level: false
""".strip())
    print("=" * 60)

    total = project_count_s + len(P_DRIVE_PROJECTS)
    print(f"\nDone. Created {total} project directories across 2 mock drives.")


if __name__ == "__main__":
    create_mock_drives()
