"""PCBA defect taxonomy, transcribed from
"PCBA Defect Classification Table" v1.0 (27 April 2026).

Used for labeling uploaded NG samples, for the defect-type column in result
tables, and for severity-based verdicts (Critical/Major -> NG, Minor -> Warning).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DefectType:
    name: str
    category: str
    severity: str  # Critical | Major | Minor
    detection: str  # detection method in the source table
    description: str


_T = DefectType
DEFECT_TYPES: list[DefectType] = [
    # 3.1 Solder-related
    _T("Solder Bridge", "Solder", "Critical", "AOI / Visual", "Adjacent pads/leads shorted by solder"),
    _T("Insufficient Solder", "Solder", "Major", "AOI / 3D", "Not enough solder to form a proper joint"),
    _T("Excess Solder", "Solder", "Major", "AOI", "Too much solder, risk of bridging"),
    _T("Cold Joint", "Solder", "Major", "Visual", "Dull, grainy joint due to insufficient heat"),
    _T("Poor Wetting", "Solder", "Major", "AOI", "Solder does not spread on pad/lead"),
    _T("Solder Crack", "Solder", "Major", "Visual", "Cracks in solder joint"),
    _T("Solder Ball", "Solder", "Minor", "AOI", "Small solder spheres around joint"),
    _T("Fillet Shape Defect", "Solder", "Minor", "AOI", "Incorrect solder fillet geometry"),
    # 3.2 Component-related
    _T("Missing Component", "Component", "Critical", "AOI", "Component not placed"),
    _T("Misalignment", "Component", "Major", "AOI", "Component shifted from pad center"),
    _T("Tombstone", "Component", "Major", "AOI", "One side lifted due to uneven wetting"),
    _T("Polarity Error", "Component", "Critical", "AOI / Visual", "Incorrect orientation of polarized parts"),
    _T("Rotation Error", "Component", "Major", "AOI", "Component rotated 90/180 deg"),
    _T("Bent Lead", "Component", "Major", "AOI / Visual", "IC lead bent or not contacting pad"),
    _T("Damaged Component", "Component", "Major", "Visual", "Cracked or chipped package"),
    # 3.3 Solder paste printing
    _T("Paste Misalignment", "Paste", "Major", "SPI / AOI", "Paste offset from pad"),
    _T("Paste Insufficient", "Paste", "Major", "SPI", "Not enough paste deposited"),
    _T("Paste Excess", "Paste", "Major", "SPI", "Too much paste"),
    _T("Paste Slump", "Paste", "Major", "SPI", "Paste spreads beyond stencil area"),
    _T("Paste Void", "Paste", "Minor", "X-ray", "Air pockets inside paste"),
    # 3.4 PCB / pad / surface
    _T("Pad Lift", "PCB Surface", "Critical", "Visual", "Pad lifted from PCB"),
    _T("Contamination", "PCB Surface", "Major", "AOI / Visual", "Dust, oil, flux residue"),
    _T("Scratch", "PCB Surface", "Minor", "Visual", "Surface scratch or abrasion"),
    _T("Silkscreen Error", "PCB Surface", "Minor", "Visual", "Incorrect or missing marking"),
    _T("Copper Exposure", "PCB Surface", "Major", "Visual", "Exposed copper due to mask issue"),
    # 3.5 Electrical / circuit
    _T("Open Circuit", "Electrical", "Critical", "ICT / AOI", "Broken trace or connection"),
    _T("Short Circuit", "Electrical", "Critical", "AOI", "Unintended electrical connection"),
    _T("Trace Damage", "Electrical", "Major", "Visual", "Scratched or broken copper trace"),
    _T("Via Defect", "Electrical", "Major", "X-ray", "Poor plating or non-conductive via"),
    # 3.6 Connector / mechanical
    _T("Bent Pin", "Connector", "Major", "AOI / Visual", "Deformed connector pin"),
    _T("Pin Height Error", "Connector", "Major", "3D AOI", "Incorrect pin height"),
    _T("Partial Insertion", "Connector", "Critical", "AOI / Visual", "Connector not fully seated"),
    _T("Shield Can Gap", "Connector", "Major", "Side-View AOI", "Gap between shield can and PCB"),
]

# Generic label for regions the unsupervised model flags before a type is known.
ANOMALY = DefectType("Anomaly", "Unclassified", "Major", "AI", "Deviation from learned good boards")

BY_NAME = {d.name: d for d in DEFECT_TYPES + [ANOMALY]}

# Section 4: must be present in every AOI recipe.
MANDATORY_AOI_SET = [
    "Missing Component",
    "Misalignment",
    "Polarity Error",
    "Solder Bridge",
    "Tombstone",
    "Cold Joint",
    "Shield Can Gap",
    "Connector Pin Height",
    "3D Coplanarity",
    "Solder Volume",
]

# Checks that need Stage 2 hardware (3D / side-view cameras).
REQUIRES_3D_OR_SIDE = {
    "Shield Can Gap",
    "Connector Pin Height",
    "3D Coplanarity",
    "Solder Volume",
    "Pin Height Error",
    "Insufficient Solder",
}

SEVERITY_COLOR = {"Critical": "#e53935", "Major": "#fb8c00", "Minor": "#fdd835"}


def names() -> list[str]:
    return [d.name for d in DEFECT_TYPES]


def categories() -> list[str]:
    seen: list[str] = []
    for d in DEFECT_TYPES:
        if d.category not in seen:
            seen.append(d.category)
    return seen
