"""Deterministic PKR amount parsing for copilot arguments (T11.3).

The model passes amounts exactly as the user said them ("2 million", "20 lakh",
"bees lakh", "۲۰ لاکھ", "PKR 2,000,000"). This module turns them into whole PKR or
raises ``AmountNeedsClarification`` for a foreign or unknown currency/unit, so the
assistant asks one focused question instead of guessing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

FOREIGN = {
    "$": "USD",
    "usd": "USD",
    "dollar": "USD",
    "dollars": "USD",
    "€": "EUR",
    "eur": "EUR",
    "euro": "EUR",
    "euros": "EUR",
    "£": "GBP",
    "gbp": "GBP",
    "pound": "GBP",
    "pounds": "GBP",
    "inr": "INR",
    "₹": "INR",
    "aed": "AED",
    "dirham": "AED",
    "dirhams": "AED",
    "riyal": "SAR",
    "sar": "SAR",
    "yuan": "CNY",
    "rmb": "CNY",
}

MULTIPLIERS = {
    "k": 1e3,
    "thousand": 1e3,
    "thousands": 1e3,
    "hazar": 1e3,
    "hazaar": 1e3,
    "hajar": 1e3,
    "ہزار": 1e3,
    "lakh": 1e5,
    "lakhs": 1e5,
    "lac": 1e5,
    "lacs": 1e5,
    "laakh": 1e5,
    "لاکھ": 1e5,
    "m": 1e6,
    "mn": 1e6,
    "million": 1e6,
    "millions": 1e6,
    "milyan": 1e6,
    "ملین": 1e6,
    "crore": 1e7,
    "crores": 1e7,
    "cr": 1e7,
    "karor": 1e7,
    "karod": 1e7,
    "karore": 1e7,
    "کروڑ": 1e7,
    "b": 1e9,
    "bn": 1e9,
    "billion": 1e9,
    "arab": 1e9,
    "ارب": 1e9,
}

WORDS = {
    # English
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
    "half": 0.5,
    # Roman Urdu
    "ek": 1,
    "aik": 1,
    "do": 2,
    "teen": 3,
    "tin": 3,
    "char": 4,
    "chaar": 4,
    "paanch": 5,
    "panch": 5,
    "chhe": 6,
    "chay": 6,
    "che": 6,
    "chheh": 6,
    "saat": 7,
    "sat": 7,
    "aath": 8,
    "aat": 8,
    "nau": 9,
    "no": 9,
    "das": 10,
    "dus": 10,
    "gyarah": 11,
    "gyara": 11,
    "barah": 12,
    "bara": 12,
    "terah": 13,
    "chaudah": 14,
    "pandrah": 15,
    "solah": 16,
    "satrah": 17,
    "atharah": 18,
    "unees": 19,
    "bees": 20,
    "pachees": 25,
    "pachis": 25,
    "tees": 30,
    "chalees": 40,
    "chalis": 40,
    "pachas": 50,
    "pachaas": 50,
    "pachaas.": 50,
    "sattar": 70,
    "assi": 80,
    "nabbe": 90,
    "dedh": 1.5,
    "derh": 1.5,
    "dhai": 2.5,
    "dhaai": 2.5,
    "aadha": 0.5,
    "adha": 0.5,
    # Urdu script
    "ایک": 1,
    "دو": 2,
    "تین": 3,
    "چار": 4,
    "پانچ": 5,
    "چھ": 6,
    "سات": 7,
    "آٹھ": 8,
    "نو": 9,
    "دس": 10,
    "بیس": 20,
    "پچیس": 25,
    "تیس": 30,
    "چالیس": 40,
    "پچاس": 50,
    "ڈیڑھ": 1.5,
    "ڈھائی": 2.5,
    "آدھا": 0.5,
}
HUNDREDS = {"hundred": 100, "sau": 100, "سو": 100}

FILLER = {
    "pkr",
    "rs",
    "rupee",
    "rupees",
    "rupay",
    "rupaye",
    "rupiya",
    "rupiye",
    "روپے",
    "روپیہ",
    "روپیے",
    "pakistani",
    "only",
    "the",
    "a",
    "an",
    "of",
    "to",
    "and",
    "aur",
    "اور",
    "budget",
    "about",
    "approximately",
    "approx",
    "around",
    "taqreeban",
    "تقریباً",
    "se",
    "ka",
    "ki",
    "ke",
    "کا",
    "کی",
    "کے",
    "tak",
    "تک",
    "capital",
    "operating",
    "kar",
    "do",
    "karo",
    "kardo",
    "کر",
    "دو",
}

# Words that are numbers only directly before a multiplier ("do crore", but "kar do").
AMBIGUOUS = {"do", "no", "sat", "tin", "che", "aat", "دو", "نو"}

_TOKEN = re.compile(r"\d+(?:\.\d+)?|[$€£₹]|[^\W\d_]+", re.UNICODE)


class AmountNeedsClarification(ValueError):
    """The amount cannot be resolved to PKR without asking the user."""


@dataclass(frozen=True)
class ParsedAmount:
    pkr: int
    source_text: str
    display: str


def _group_display(pkr: int) -> str:
    if pkr >= 10_000_000 and pkr % 100_000 == 0:
        crore, lakh = divmod(pkr // 100_000, 100)
        return f"{crore} crore" + (f" {lakh} lakh" if lakh else "")
    if pkr >= 100_000 and pkr % 1_000 == 0:
        lakh = pkr / 100_000
        return f"{lakh:g} lakh"
    return ""


def format_pkr(pkr: int) -> str:
    alt = _group_display(pkr)
    return f"PKR {pkr:,}" + (f" ({alt})" if alt else "")


def parse_pkr(text: str | float) -> ParsedAmount:
    """Parse an amount into whole PKR. Raises AmountNeedsClarification when ambiguous."""
    if isinstance(text, bool):
        raise AmountNeedsClarification("amount must be a number or text, not a boolean")
    if isinstance(text, int | float):
        if text < 0:
            raise AmountNeedsClarification("amount cannot be negative")
        return ParsedAmount(round(text), str(text), format_pkr(round(text)))
    raw = str(text).strip()
    if not raw:
        raise AmountNeedsClarification("empty amount")
    s = raw.translate(_DIGITS).lower().replace(",", "").replace("٬", "").replace("rs.", "rs ")
    s = s.replace("-", " ")
    if s.startswith("minus") or re.match(r"^\s*-\s*\d", raw):
        raise AmountNeedsClarification("amount cannot be negative")
    for tok, code in FOREIGN.items():
        if (len(tok) == 1 and tok in s) or re.search(
            rf"(?<![^\W\d_]){re.escape(tok)}(?![^\W\d_])", s
        ):
            raise AmountNeedsClarification(
                f"the amount '{raw}' is in {code}, not PKR; ask which PKR amount is intended "
                "(no exchange rate is assumed)"
            )
    total = 0.0
    current: float | None = None  # number awaiting a multiplier
    seen_number = False
    toks = _TOKEN.findall(s)
    for i, tok in enumerate(toks):
        nxt = toks[i + 1] if i + 1 < len(toks) else ""
        if tok in AMBIGUOUS and nxt not in MULTIPLIERS and nxt not in HUNDREDS:
            if tok in FILLER:
                continue
            raise AmountNeedsClarification(f"unclear word '{tok}' in amount '{raw}'")
        if re.fullmatch(r"\d+(?:\.\d+)?", tok):
            if current is not None:
                total += current
            current = float(tok)
            seen_number = True
        elif tok in MULTIPLIERS:
            if current is None:
                if not seen_number:
                    current = 1.0  # "lakh" alone is not meaningful; treat "a lakh" as 1 lakh
                else:
                    raise AmountNeedsClarification(f"unclear amount '{raw}'")
            total += current * MULTIPLIERS[tok]
            current = None
        elif tok in HUNDREDS:
            current = (current if current is not None else 1.0) * HUNDREDS[tok]
            seen_number = True
        elif tok in WORDS:
            v = float(WORDS[tok])
            current = v if current is None else current + v
            seen_number = True
        elif tok in FILLER:
            continue
        else:
            raise AmountNeedsClarification(
                f"unknown unit or word '{tok}' in amount '{raw}'; ask the user for a PKR amount"
            )
    if current is not None:
        total += current
    if not seen_number:
        raise AmountNeedsClarification(f"no number found in amount '{raw}'")
    pkr = round(total)
    return ParsedAmount(pkr, raw, format_pkr(pkr))
