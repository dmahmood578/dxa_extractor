"""
dxa_to_wide_csv.py
==================
Builds a wide per-patient CSV by merging DICOM demographics with OCR-derived
DXA table content from extracted_text/Patient_N/.

This export keeps the OCR evidence, but normalizes table blocks into compact
measurement lines so the CSV stays wide without carrying huge prose blobs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

# ── paths ────────────────────────────────────────────────────────────────────

_SCRIPT_DIR = Path(__file__).parent
DEFAULT_TEXT_DIR = _SCRIPT_DIR / "extracted_text"
TEXT_DIR = DEFAULT_TEXT_DIR
DATA_DIR     = _SCRIPT_DIR / "data"
DEMOGRAPHICS_CSV = DATA_DIR / "patient_cohort_demographics.csv"
OUTPUT_CSV       = DATA_DIR / "patient_wide_measurements.csv"

# ── constants ─────────────────────────────────────────────────────────────────

BMD_MIN, BMD_MAX   = 0.3, 2.5
SCORE_MIN, SCORE_MAX = -6.0, 6.0

# Build the OCR→float correction table programmatically where the pattern is
# systematic (e.g. "O1"→−0.1, "a3"→−1.3) and hard-code only the irregular ones.
def _build_ocr_sign_map() -> dict[str, float]:
    m: dict[str, float] = {}
    # "O1".."O9" / "o1".."o9"  →  −0.1 .. −0.9
    for d in range(1, 10):
        val = -d / 10.0
        for prefix in ("O", "o"):
            m[f"{prefix}{d}"] = val
    # aliased tokens for −0.1
    for tok in ("OT", "ot", "ut", "UT"):
        m[tok] = -0.1
    # "a1".."a9" / "A1".."A9"  →  −1.1 .. −1.9  (except a few specials below)
    for d in range(1, 10):
        val = -(1.0 + d / 10.0)
        for prefix in ("a", "A"):
            m[f"{prefix}{d}"] = val
    # Irregular overrides
    overrides = {
        "Os": -0.5, "os": -0.5,
        "al": -1.2, "AL": -1.2,
        "as": -1.5, "AS": -1.5,
        "AT": -2.1, "aT": -2.1,
        "af": -2.5, "AF": -2.5,
        "Bl": -3.1, "BI": -3.1,
    }
    m.update(overrides)
    return m

_OCR_SIGN_MAP: dict[str, float] = _build_ocr_sign_map()

# ── pre-compiled regexes ──────────────────────────────────────────────────────

_RE_AGE_LABEL   = re.compile(r"\bage\s*:\s*([0-9.]+)", re.IGNORECASE)
_RE_AGE_YEARS   = re.compile(r"(\d{2}\.?\d)\s*years", re.IGNORECASE)
_RE_DOB         = re.compile(r"(?:birth\s*date|dob)\s*[:\s]+([0-9/A-Za-z]+)", re.IGNORECASE)
_RE_DOB_DIGITS  = re.compile(r"(\d{1,2})[\/-](\d{1,2})[\/-](\d{2,4})")
_RE_NAME        = re.compile(r"(?:patient|name)\s*:\s*['\"''""\s]*([A-Za-z][A-Za-z\s,.'\-]{3,60})", re.IGNORECASE)
_RE_SEX_LABEL   = re.compile(r"(?:sex|sexe)\s*[:/]\s*(female|male|f|m)", re.IGNORECASE)
_RE_SEX_WORD    = re.compile(r"\b(Female|Male)\b", re.IGNORECASE)
_RE_HEIGHT_IN   = re.compile(r"(?:height|heigl)\s*[/:\s]+([0-9a-zA-Z.]{3,7})\s*in", re.IGNORECASE)
_RE_HEIGHT_UNIT = re.compile(r"height.*?\(in\)\s*([0-9.]+)", re.IGNORECASE)
_RE_WEIGHT      = re.compile(r"weight\s*[/:\s]+([0-9.]+)\s*(?:lb|kg|Ib|bs)", re.IGNORECASE)
_RE_SCAN_DATE   = re.compile(r"(?:measured|scan\s*date)\s*:\s*([0-9A-Za-z/,\s:.-]+?)(?:\s*\(|\s*AM|\s*PM|\n)", re.IGNORECASE)
_RE_DATE_MDY    = re.compile(r"(\d{1,2}/\d{1,2}/(?:20|19)\d{2})")
_RE_PHYSICIAN   = re.compile(r"referring\s*physician\s*:\s*([A-Za-z\s.,'\-]{4,80})", re.IGNORECASE)
_RE_TBS         = re.compile(r"tbs\s*l1[-–]l4\s*:\s*([0-9.]+)", re.IGNORECASE)
_RE_BMD_NEW     = re.compile(r"^[01]\.\d{2,3}")
_RE_BMD_OLD     = re.compile(r"^[01]\d{3}$")
_RE_MERGED_YA_T = re.compile(r"^(\d{2,3})(-\d{1,3})$")
_RE_ANCILLARY   = re.compile(r"ancillary results", re.IGNORECASE)
_RE_DIGIT_COUNT = re.compile(r"\d")
_RE_WHITESPACE  = re.compile(r"\s+")

# ── data structures ───────────────────────────────────────────────────────────

@dataclass
class BmdResult:
    bmd: Optional[float] = None
    t:   Optional[float] = None
    z:   Optional[float] = None

    def is_valid(self) -> bool:
        return self.bmd is not None and BMD_MIN < self.bmd < BMD_MAX

    def to_dict(self, prefix: str) -> dict[str, Optional[float]]:
        return {f"{prefix}_BMD": self.bmd, f"{prefix}_T": self.t, f"{prefix}_Z": self.z}


@dataclass
class FemurResult:
    neck:  BmdResult = field(default_factory=BmdResult)
    total: BmdResult = field(default_factory=BmdResult)

    def to_dict(self, side_prefix: str) -> dict[str, Optional[float]]:
        return {**self.neck.to_dict(f"{side_prefix}_Neck"), **self.total.to_dict(f"{side_prefix}_Total")}


@dataclass
class SectionSummary:
    text:      Optional[str] = None
    row_count: Optional[int] = None
    rows:      Optional[str] = None

    def to_dict(self, name: str) -> dict[str, object]:
        return {f"{name}_Text": self.text, f"{name}_RowCount": self.row_count, f"{name}_Rows": self.rows}


# Sections: (header_patterns, stop_patterns, preferred_filename_patterns)
SECTIONS: dict[str, tuple[list[str], list[str], list[str]]] = {
    "AP_Spine": (
        [r"ANCILLARY RESULTS[:\[\(\s]*AP Spine", r"AP Spine Bone Density"],
        [r"Densitometry Trend", r"SPINE TBS REPORT", r"COMMENTS", r"FRAX", r"Left Femur", r"Right Femur", r"DualFemur"],
        [r"ap_spine", r"spine"],
    ),
    "Left_Femur": (
        [r"ANCILLARY RESULTS[:\[\(\s]*Left Femur", r"Left Femur Bone Density"],
        [r"Densitometry Trend", r"SPINE TBS REPORT", r"COMMENTS", r"FRAX", r"AP Spine", r"Right Femur", r"DualFemur"],
        [r"left_femur", r"dual_femur", r"femur"],
    ),
    "Right_Femur": (
        [r"ANCILLARY RESULTS[:\[\(\s]*Right Femur", r"Right Femur Bone Density"],
        [r"Densitometry Trend", r"SPINE TBS REPORT", r"COMMENTS", r"FRAX", r"AP Spine", r"Left Femur", r"DualFemur"],
        [r"right_femur", r"dual_femur", r"femur"],
    ),
    "DualFemur": (
        [r"ANCILLARY RESULTS[:\[\(\s]*DualFemur", r"DualFemur Bone Density", r"Dual Femur"],
        [r"Densitometry Trend", r"SPINE TBS REPORT", r"COMMENTS", r"FRAX", r"AP Spine", r"Left Femur", r"Right Femur"],
        [r"dual_femur", r"femur"],
    ),
    "TBS": (
        [r"SPINE TBS REPORT", r"TBS L1-L4"],
        [r"Date of analysis", r"FRAX", r"COMMENTS", r"Page:"],
        [r"tbs"],
    ),
    "Trend": (
        [r"Densitometry Trend", r"Bone Density Trend", r"Trend:"],
        [r"COMMENTS", r"SPINE TBS REPORT", r"FRAX", r"Page:"],
        [r"trend"],
    ),
}

_SECTION_STOP_KEYWORDS = frozenset(["statistical", "comments", "tbs", "trend", "frax", "page:", "hologic", "lunar", "©"])
_NAME_STOPS = ["Referring", "Facility", "Birth", "Date", "Patient", "ID", "Phone", "Height"]

# Region labels that indicate a new data row in loose (Paddle/Surya) mode
_REGION_LABELS_RE = re.compile(
    r'\b(l[1-5]|neck|total|ward|troch|inter|shaft|tbs|mean|diff)\b',
    re.IGNORECASE,
)

_SIDE_ALIASES: dict[str, list[str]] = {
    "left":  ["left", "lett", "let", "lef", "lefe"],
    "right": ["right", "righ"],
}

# ── text helpers ──────────────────────────────────────────────────────────────

def read_folder(patient_dir: Path) -> dict[str, str]:
    """Return {filename: text} for every *.txt in a patient folder."""
    return {
        p.name: p.read_text(encoding="utf-8", errors="replace")
        for p in sorted(patient_dir.glob("*.txt"))
    }


def combined(texts: dict[str, str]) -> str:
    return "\n".join(texts.values())


def _digit_count(s: str) -> int:
    return len(_RE_DIGIT_COUNT.findall(s))


# ── OCR score parser ──────────────────────────────────────────────────────────

def parse_score_token(tok: str) -> Optional[float]:
    """Convert an OCR token to a float score, or None if unreadable."""
    tok = tok.strip("[]|\"'()")
    if not tok or tok in ("N/A", "-", "=", "*", ">", "<"):
        return None
    if tok in _OCR_SIGN_MAP:
        return _OCR_SIGN_MAP[tok]
    cleaned = re.sub(r"[^0-9.\-]", "", tok)
    if not cleaned or cleaned == ".":
        return None
    try:
        val = float(cleaned)
        # Two- or three-digit integers encode tenths: "12" → −1.2
        if tok.isdigit() and 2 <= len(tok) <= 3:
            val = -abs(val / 10.0)
        return val
    except ValueError:
        return None


def _fix_bmd_token(tok: str) -> float:
    """Handle BMD tokens with a missing decimal point: '0873' → 0.873."""
    tok = tok.strip("[]|\"'(),")
    if re.match(r"^[01]\d{3}$", tok):
        return float(f"{tok[0]}.{tok[1:]}")
    return float(tok)


def _split_merged_ya_t(tok: str) -> tuple[Optional[int], Optional[float]]:
    """
    Older GE firmware merges %YA and T-score into one token: '86-10' → (86, −1.0).
    Returns (ya_pct, t_score) or (None, None).
    """
    m = _RE_MERGED_YA_T.match(tok.strip("[]|\"'(),"))
    if m:
        return int(m.group(1)), float(m.group(2)) / 10.0
    return None, None


def extract_bmd_row(row_str: str) -> BmdResult:
    """
    Parse a GE Lunar table row: label BMD %YA T-score %AM Z-score …
    Handles new format (0.873) and old format (0873 or merged 86-10).
    """
    tokens = row_str.split()
    bmd_idx = next(
        (i for i, tok in enumerate(tokens)
         if _RE_BMD_NEW.match(tok.strip("[]|\"'(),")) or _RE_BMD_OLD.match(tok.strip("[]|\"'(),"))),
        -1,
    )
    if bmd_idx == -1:
        return BmdResult()

    try:
        bmd = _fix_bmd_token(tokens[bmd_idx])
    except ValueError:
        return BmdResult()

    def _tok(offset: int) -> Optional[str]:
        idx = bmd_idx + offset
        return tokens[idx] if idx < len(tokens) else None

    t = z = None
    ya_tok = _tok(1)
    if ya_tok:
        merged_ya, merged_t = _split_merged_ya_t(ya_tok)
        if merged_ya is not None:
            t = merged_t
            z = parse_score_token(_tok(3)) if _tok(3) else None
        else:
            t = parse_score_token(_tok(2)) if _tok(2) else None
            z = parse_score_token(_tok(4)) if _tok(4) else None

    def _clamp(v: Optional[float]) -> Optional[float]:
        return v if v is not None and SCORE_MIN <= v <= SCORE_MAX else None

    return BmdResult(bmd=bmd, t=_clamp(t), z=_clamp(z))


# ── GE Lunar section parser ───────────────────────────────────────────────────

def find_ancillary_section(txt: str, keyword: str) -> list[str]:
    """Return data-row strings for the named ancillary section."""
    kw_lower = keyword.lower()
    txt_lower = txt.lower()

    start = next(
        (m.start() for m in _RE_ANCILLARY.finditer(txt_lower)
         if kw_lower in txt_lower[m.start(): m.start() + 80]),
        -1,
    )
    if start == -1:
        return []

    lines = txt[start: start + 4000].split("\n")
    header_idx = next(
        (i for i, line in enumerate(lines)
         if "region" in line.lower() and any(k in line.lower() for k in ("t-score", "(g/cm", "bmd", "z-score"))),
        -1,
    )
    if header_idx == -1:
        return []

    data_rows: list[str] = []
    for line in lines[header_idx + 1:]:
        stripped = line.strip()
        if not stripped:
            continue
        if any(stop in stripped.lower() for stop in _SECTION_STOP_KEYWORDS):
            break
        if _digit_count(stripped) >= 2:
            data_rows.append(stripped)
        if len(data_rows) >= 60:
            break
    return data_rows


def find_ancillary_section_loose(txt: str, keyword: str) -> list[str]:
    """
    Same as find_ancillary_section() but works with clean (Paddle/Surya) text
    where numbers are on separate lines rather than in multi-column rows.

    Strategy: find section, collect all lines, then group consecutive lines
    into pseudo-rows. A new pseudo-row starts when a line contains a region
    label (L1–L5, Neck, Total, Ward, Troch, etc.).
    """
    kw_lower = keyword.lower()
    txt_lower = txt.lower()

    start = next(
        (m.start() for m in _RE_ANCILLARY.finditer(txt_lower)
         if kw_lower in txt_lower[m.start(): m.start() + 80]),
        -1,
    )
    if start == -1:
        return []

    lines = txt[start: start + 4000].split("\n")

    # Collect all lines until a stop keyword
    raw_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if any(stop in stripped.lower() for stop in _SECTION_STOP_KEYWORDS):
            break
        raw_lines.append(stripped)
        if len(raw_lines) >= 200:
            break

    if not raw_lines:
        return []

    # Group into pseudo-rows keyed by region labels
    pseudo_rows: list[str] = []
    current_row: list[str] = []

    for line in raw_lines:
        low = line.lower()
        is_region = bool(_REGION_LABELS_RE.search(low))

        if is_region and current_row:
            # Start a new pseudo-row; flush the previous one
            pseudo_rows.append(" ".join(current_row))
            current_row = [line]
        else:
            current_row.append(line)

    if current_row:
        pseudo_rows.append(" ".join(current_row))

    # Filter to rows that contain at least one digit
    return [r for r in pseudo_rows if _digit_count(r) >= 1]


def _find_section_rows(txt: str, keyword: str) -> list[str]:
    """Try tight (Tesseract) parsing first; fall back to loose if too few rows."""
    rows = find_ancillary_section(txt, keyword)
    if len(rows) < 4:
        loose = find_ancillary_section_loose(txt, keyword)
        if len(loose) > len(rows):
            return loose
    return rows


def ge_spine_l1l4(texts: dict[str, str]) -> BmdResult:
    for txt in texts.values():
        rows = _find_section_rows(txt, "ap spine")
        if len(rows) >= 7:
            result = extract_bmd_row(rows[6])
            if result.is_valid():
                return result

    comb = combined(texts)
    for pattern in (
        r"(?:l1.?l4|spine).*?(\d{1,2}/\d{1,2}/(?:19|20)\d{2})\s+[0-9.]+\s+(0\.[4-9]\d{2}|1\.\d{3})",
        r"(\d{1,2}/\d{1,2}/(?:19|20)\d{2})\s+[0-9.]+\s+(0\.[4-9]\d{2}|1\.\d{3})\s+",
    ):
        m = re.search(pattern, comb, re.IGNORECASE)
        if m:
            bmd = float(m.group(2))
            if BMD_MIN < bmd < BMD_MAX:
                return BmdResult(bmd=bmd)
    return BmdResult()


def ge_spine_vertebrae(texts: dict[str, str]) -> dict[str, Optional[float]]:
    """Return per-vertebra (L1–L4) BMD, T, Z dicts when available."""
    keys = [k for v in range(1, 5) for k in (f"Spine_L{v}_BMD", f"Spine_L{v}_T", f"Spine_L{v}_Z")]
    out: dict[str, Optional[float]] = dict.fromkeys(keys, None)

    for txt in texts.values():
        rows = _find_section_rows(txt, "ap spine")
        if not rows:
            continue
        for line in rows:
            first = line.strip().split()[0].lower().strip(".:)") if line.strip().split() else ""
            if len(first) == 2 and first[0] == "l" and first[1].isdigit():
                v = int(first[1])
            else:
                m = re.match(r"\s*(L?)([1-5])\b", line.strip(), re.IGNORECASE)
                v = int(m.group(2)) if m else 0
            if not 1 <= v <= 4:
                continue
            result = extract_bmd_row(line)
            if result.bmd is not None and BMD_MIN < result.bmd < BMD_MAX:
                out[f"Spine_L{v}_BMD"] = result.bmd
            if result.t is not None:
                out[f"Spine_L{v}_T"] = result.t
            if result.z is not None:
                out[f"Spine_L{v}_Z"] = result.z

        if any(out[f"Spine_L{i}_BMD"] is not None for i in range(1, 5)):
            return out

    # Fallback: regex scan of combined text
    comb = combined(texts)
    for i in range(1, 5):
        m = re.search(rf"\bL{i}\b[^\n]*?(0\.[4-9]\d{{2}}|1\.\d{{3}})", comb, re.IGNORECASE)
        if m:
            try:
                out[f"Spine_L{i}_BMD"] = float(m.group(1))
            except ValueError:
                pass
    return out


def ge_femur(texts: dict[str, str], side: str) -> FemurResult:
    side = side.lower()
    other_side = "right" if side == "left" else "left"
    our_aliases   = _SIDE_ALIASES[side]
    other_aliases = _SIDE_ALIASES[other_side]

    result = FemurResult()
    search_keywords = [f"{side} femur", "dualfemur", "dual femur", "femur"]

    for kw in search_keywords:
        for txt in texts.values():
            rows = _find_section_rows(txt, kw)
            if not rows:
                continue
            for row in rows:
                row_l = row.lower()
                is_dual = kw.lower() in ("dualfemur", "dual femur", "femur")
                if is_dual:
                    has_ours  = any(a in row_l for a in our_aliases)
                    has_other = any(a in row_l for a in other_aliases)
                    if (has_other and not has_ours) or "mean" in row_l or "dif" in row_l:
                        continue
                    if not has_ours:
                        continue
                r = extract_bmd_row(row)
                if not (r.bmd and BMD_MIN < r.bmd < BMD_MAX):
                    continue
                if "total" in row_l and result.total.bmd is None:
                    result.total = r
                elif "neck" in row_l and not any(w in row_l for w in ("upper", "lower", "ward")) and result.neck.bmd is None:
                    result.neck = r

        if result.neck.bmd or result.total.bmd:
            break

    return result


def ge_hologic_fallback(texts: dict[str, str]) -> tuple[BmdResult, FemurResult, FemurResult]:
    """
    Heuristic extractor for Hologic-formatted reports.
    Looks for lines containing 'Neck' or 'Total' with a sequence of numeric tokens
    (Area, BMC, BMD, T-score, ...) and maps the third numeric to BMD and the
    fourth to T-score when available.
    Returns (spine_bmdresult, left_femur_result, right_femur_result).
    """
    comb = combined(texts)

    def _tok_nums(s: str) -> list[str]:
        parts = re.findall(r"[0-9]+\.[0-9]+|[0-9]{3,4}", s)
        return parts

    spine = BmdResult()
    left = FemurResult()
    right = FemurResult()

    # Search for lines mentioning Hip/Neck/Total that contain 3+ numeric tokens
    for line in comb.splitlines():
        ln = line.strip()
        if not ln:
            continue
        low = ln.lower()
        if any(k in low for k in ("neck", "total", "hip", "l1", "l4", "spine")):
            nums = _tok_nums(ln)
            if len(nums) >= 3:
                # third number is likely BMD (or a 4-digit old-format token)
                bmd_tok = nums[2]
                try:
                    bmd_val = _fix_bmd_token(bmd_tok) if re.match(r"^[01]\d{3}$", bmd_tok) else float(bmd_tok)
                except Exception:
                    continue
                if not (BMD_MIN < bmd_val < BMD_MAX):
                    continue

                # attempt T-score from next numeric token if present
                t_val = None
                if len(nums) >= 4:
                    t_tok = nums[3]
                    t_val = parse_score_token(t_tok)

                if "spine" in low or re.search(r"l\s*1|l1|l4|l\s*4", low) or "ap spine" in low:
                    if spine.bmd is None:
                        spine = BmdResult(bmd=bmd_val, t=t_val)
                elif ("left" in low and "femur" in low) or re.search(r"left\s+hip|left femur", low):
                    # set neck or total based on presence of 'neck'/'total'
                    r = BmdResult(bmd=bmd_val, t=t_val)
                    if "neck" in low:
                        left.neck = r
                    else:
                        left.total = r
                elif ("right" in low and "femur" in low) or re.search(r"right\s+hip|right femur", low):
                    r = BmdResult(bmd=bmd_val, t=t_val)
                    if "neck" in low:
                        right.neck = r
                    else:
                        right.total = r

    return spine, left, right


# ── demographics parsers ──────────────────────────────────────────────────────

def _clean_str(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = _RE_WHITESPACE.sub(" ", s).strip()
    s = re.sub(r"^[^A-Za-z]+", "", s).strip()
    return s or None


def parse_age(txt: str) -> Optional[float]:
    m = _RE_AGE_LABEL.search(txt) or _RE_AGE_YEARS.search(txt)
    if not m:
        return None
    raw = m.group(1)
    val = float(raw)
    if val > 150:
        val = float(raw[:2] + "." + raw[2:])
    return round(val, 1)


def parse_dob(txt: str, study_year: Optional[int] = None, age: Optional[float] = None) -> Optional[str]:
    m = _RE_DOB.search(txt)
    if m:
        raw = m.group(1).strip()
        raw = re.sub(r"[oO](?=\d)|(?<=\d)[oO]", "0", raw)
        dm = _RE_DOB_DIGITS.search(raw)
        if dm:
            mo, day, yr = dm.groups()
            if len(yr) == 4 and int(yr) > 2025:
                yr = "19" + yr[2:]
            return f"{mo}/{day}/{yr}"
    if study_year and age:
        return f"1/1/{study_year - int(age)}"
    return None


def parse_name(txt: str) -> Optional[str]:
    m = _RE_NAME.search(txt)
    if not m:
        return None
    candidate = m.group(1)
    for stop in _NAME_STOPS:
        idx = candidate.lower().find(stop.lower())
        if idx != -1:
            candidate = candidate[:idx]
    cand = _clean_str(candidate)
    return None if (not cand or len(cand) < 4 or cand.upper() == cand) else cand


def parse_sex(txt: str) -> Optional[str]:
    m = _RE_SEX_LABEL.search(txt) or _RE_SEX_WORD.search(txt)
    return m.group(1)[0].upper() if m else None


def parse_height(txt: str) -> Optional[float]:
    m = _RE_HEIGHT_IN.search(txt)
    if m:
        raw = (m.group(1).replace(" ", "")
               .replace("s", "5").replace("S", "5")
               .replace("l", "1").replace("L", "1"))
        raw = re.sub(r"[oO](?=\d)|(?<=\d)[oO]", "0", raw)
        raw = re.sub(r"[^0-9.]", "", raw)
        if raw:
            val = float(raw)
            if val > 100:
                val /= 10.0
            if 48.0 <= val <= 84.0:
                return round(val, 1)
    m2 = _RE_HEIGHT_UNIT.search(txt)
    if m2:
        val = float(m2.group(1))
        return round(val / 10.0 if val > 100 else val, 1)
    return None


def parse_weight(txt: str) -> Optional[float]:
    m = _RE_WEIGHT.search(txt)
    if not m:
        return None
    val = float(m.group(1))
    return round(val / 10.0 if val > 500 else val, 1)


def parse_scan_date(txt: str) -> Optional[str]:
    m = _RE_SCAN_DATE.search(txt)
    if m:
        dm = _RE_DATE_MDY.search(m.group(1).strip().rstrip(","))
        return dm.group(1) if dm else m.group(1).strip()[:20]
    return None


def parse_physician(txt: str) -> Optional[str]:
    m = _RE_PHYSICIAN.search(txt)
    if not m:
        return None
    cand = m.group(1)
    for stop in ("Birth", "Date", "Height", "Weight", "Patient", "\n", "Facility"):
        idx = cand.lower().find(stop.lower())
        if idx != -1:
            cand = cand[:idx]
    return _clean_str(cand)


def parse_tbs(txt: str) -> Optional[float]:
    m = _RE_TBS.search(txt)
    return float(m.group(1)) if m else None


# ── section capture ───────────────────────────────────────────────────────────

def _capture_section(txt: str, header_patterns: list[str], stop_patterns: list[str], max_lines: int = 120) -> tuple[str, list[str]]:
    lines = txt.splitlines()
    start = next(
        (i for i, line in enumerate(lines)
         if any(re.search(p, line, re.IGNORECASE) for p in header_patterns)),
        -1,
    )
    if start == -1:
        return "", []

    collected, data_lines, seen_data = [], [], False
    for line in lines[start: start + max_lines]:
        stripped = line.rstrip()
        if not stripped.strip():
            if seen_data:
                collected.append("")
            continue
        if any(re.search(p, stripped, re.IGNORECASE) for p in stop_patterns):
            break
        collected.append(stripped)
        if _digit_count(stripped) >= 2:
            seen_data = True
            data_lines.append(stripped)
    return "\n".join(collected).strip(), data_lines


def section_summary(
    texts: dict[str, str],
    header_patterns: list[str],
    stop_patterns: list[str],
    max_lines: int = 120,
    preferred_name_patterns: Optional[list[str]] = None,
) -> SectionSummary:
    if preferred_name_patterns:
        filtered = {fn: txt for fn, txt in texts.items()
                    if any(re.search(p, fn, re.IGNORECASE) for p in preferred_name_patterns)}
        if filtered:
            texts = filtered

    chunks, data_lines, seen_keys = [], [], set()
    for txt in texts.values():
        section_text, lines = _capture_section(txt, header_patterns, stop_patterns, max_lines)
        if section_text:
            key = _RE_WHITESPACE.sub(" ", section_text).strip()
            if key not in seen_keys:
                seen_keys.add(key)
                chunks.append(section_text)
        for line in lines:
            if line not in data_lines:
                data_lines.append(line)

    compact_rows = [_RE_WHITESPACE.sub(" ", l).strip() for l in data_lines if l.strip()]

    # Fallback: collect any line that has digits or anatomical keywords
    if not compact_rows and texts:
        _ANATOMY_RE = re.compile(r"\b(neck|total|spine|tbs|trend|left|right|l[1-4])\b", re.IGNORECASE)
        seen_fb: set[str] = set()
        for txt in texts.values():
            for line in txt.splitlines():
                stripped = _RE_WHITESPACE.sub(" ", line).strip()
                if not stripped or stripped in seen_fb:
                    continue
                if _digit_count(stripped) >= 1 or _ANATOMY_RE.search(stripped):
                    seen_fb.add(stripped)
                    compact_rows.append(stripped)

    return SectionSummary(
        text=("\n\n".join(chunks).strip() or "\n".join(compact_rows).strip()) or None,
        row_count=len(compact_rows) or None,
        rows=" || ".join(compact_rows) or None,
    )


# ── patient record builder ────────────────────────────────────────────────────

def parse_patient(folder_num: str, demographics_row: Optional[pd.Series] = None) -> Optional[dict]:
    patient_dir = TEXT_DIR / f"Patient_{folder_num}"
    if not patient_dir.is_dir():
        return None

    texts = read_folder(patient_dir)
    if not texts:
        return None

    comb = combined(texts)

    rec: dict = {
        "Folder":           folder_num,
        "OCR_Name":         parse_name(comb),
        "OCR_DOB":          parse_dob(comb),
        "OCR_Age_years":    parse_age(comb),
        "OCR_Sex":          parse_sex(comb),
        "OCR_Height_in":    parse_height(comb),
        "OCR_Weight_lbs":   parse_weight(comb),
        "OCR_Referring_MD": parse_physician(comb),
        "OCR_Scan_Date":    parse_scan_date(comb),
        "OCR_TBS_L1L4":     parse_tbs(comb),
    }

    is_hologic = "hologic" in comb.lower()
    if is_hologic:
        # Try a Hologic-specific heuristic extractor; fall back to empty fields
        # if the heuristic finds nothing usable.
        spine, left_femur, right_femur = ge_hologic_fallback(texts)
        vertebrae = ge_spine_vertebrae(texts)
        rec.update(spine.to_dict("Spine_L1L4"))
        rec.update(vertebrae)
        rec.update(left_femur.to_dict("LFemur"))
        rec.update(right_femur.to_dict("RFemur"))
    else:
        spine      = ge_spine_l1l4(texts)
        vertebrae  = ge_spine_vertebrae(texts)
        left_femur = ge_femur(texts, "left")
        right_femur= ge_femur(texts, "right")
        rec.update(spine.to_dict("Spine_L1L4"))
        rec.update(vertebrae)
        rec.update(left_femur.to_dict("LFemur"))
        rec.update(right_femur.to_dict("RFemur"))

    for section_name, (headers, stops, preferred) in SECTIONS.items():
        summary = section_summary(texts, headers, stops, max_lines=180, preferred_name_patterns=preferred)
        rec.update(summary.to_dict(section_name))

    if demographics_row is not None:
        for key, value in demographics_row.items():
            if key != "Folder":
                rec.setdefault(f"DICOM_{key}", value)

    return rec


# ── output column order ───────────────────────────────────────────────────────

_PREFERRED_COLUMNS = [
    "Folder", "PatientID", "PatientName", "Sex", "DOB", "AccessionNumber",
    "StudyDate", "StudyTime", "Manufacturer", "Model",
    "OCR_Name", "OCR_DOB", "OCR_Age_years", "OCR_Sex", "OCR_Height_in",
    "OCR_Weight_lbs", "OCR_Referring_MD", "OCR_Scan_Date", "OCR_TBS_L1L4",
    "Spine_L1L4_BMD", "Spine_L1L4_T", "Spine_L1L4_Z",
    *(f"Spine_L{i}_{m}" for i in range(1, 5) for m in ("BMD", "T", "Z")),
    "LFemur_Neck_BMD", "LFemur_Neck_T", "LFemur_Neck_Z",
    "LFemur_Total_BMD", "LFemur_Total_T", "LFemur_Total_Z",
    "RFemur_Neck_BMD", "RFemur_Neck_T", "RFemur_Neck_Z",
    "RFemur_Total_BMD", "RFemur_Total_T", "RFemur_Total_Z",
    *(f"{s}_{t}" for s in ("AP_Spine", "Left_Femur", "Right_Femur", "DualFemur", "TBS", "Trend")
      for t in ("RowCount", "Text", "Rows")),
]


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    import sys

    # Parse optional CLI flags
    text_source = DEFAULT_TEXT_DIR
    output_csv = OUTPUT_CSV
    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == '--text-source' and i + 1 < len(sys.argv):
            text_source = Path(sys.argv[i + 1])
            i += 2
        elif sys.argv[i] == '--output' and i + 1 < len(sys.argv):
            output_csv = Path(sys.argv[i + 1])
            i += 2
        else:
            i += 1

    global TEXT_DIR
    TEXT_DIR = Path(text_source)

    demographics_df = (
        pd.read_csv(DEMOGRAPHICS_CSV) if DEMOGRAPHICS_CSV.exists() else pd.DataFrame()
    )

    folders = sorted(
        (d.name.removeprefix("Patient_") for d in TEXT_DIR.iterdir() if d.name.startswith("Patient_")),
        key=lambda v: int(v) if v.isdigit() else 999,
    )

    rows = []
    for folder_num in folders:
        print(f"  Parsing Patient {folder_num} …", flush=True)
        demographics_row = None
        if not demographics_df.empty and "Folder" in demographics_df.columns:
            match = demographics_df[demographics_df["Folder"].astype(str) == folder_num]
            if not match.empty:
                demographics_row = match.iloc[0]
        rec = parse_patient(folder_num, demographics_row)
        if rec:
            rows.append(rec)

    df = pd.DataFrame(rows)

    if not demographics_df.empty and "Folder" in df.columns:
        demographics_df["Folder"] = demographics_df["Folder"].astype(str)
        df["Folder"] = df["Folder"].astype(str)
        df = demographics_df.merge(df, on="Folder", how="outer", suffixes=("", "_OCR"))

    ordered_cols = [c for c in _PREFERRED_COLUMNS if c in df.columns]
    ordered_cols += [c for c in df.columns if c not in ordered_cols]
    df = df[ordered_cols]

    # Coerce and round numeric columns
    bmd_cols   = [c for c in df.columns if c.endswith("_BMD")]
    score_cols = [c for c in df.columns if c.endswith(("_T", "_Z", "_TBS_L1L4"))]
    misc_cols  = [c for c in df.columns if c.endswith(("_Age_years", "_Height_in", "_Weight_lbs"))]
    for col in bmd_cols + score_cols + misc_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if bmd_cols:
        df[bmd_cols] = df[bmd_cols].round(3)
    if score_cols:
        df[score_cols] = df[score_cols].round(1)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_csv, index=False)
    print(f"\nSaved: {output_csv}")
    print(df.head().to_string(index=False))


if __name__ == "__main__":
    main()