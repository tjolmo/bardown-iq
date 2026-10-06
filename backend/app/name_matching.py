import re
import unicodedata


def normalize_name(name: str) -> str:
    """Casefolded, accent-free, punctuation-free form of a team or player name.

    "Montréal Canadiens" -> "montreal canadiens", "St. Louis Blues" -> "st louis blues"
    """
    decomposed = unicodedata.normalize("NFKD", name)
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    letters_and_spaces = re.sub(r"[^a-z0-9\s]", "", without_accents.casefold().replace("-", " "))
    return " ".join(letters_and_spaces.split())
