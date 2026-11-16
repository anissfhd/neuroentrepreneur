"""Lecture d'une sortie structuree pendant sa generation (D-79).

Le modele produit un objet JSON champ apres champ ; on lit une valeur texte encore
incomplete (la reponse du coach, diffusee a l'interface) ou deja terminee (l'intention, qui
dit aussitot si le message releve d'une route deterministe). Aucune interpretation du
contenu : seulement le decodage du JSON partiel.
"""

from __future__ import annotations

import re

_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}


class StopStreaming(Exception):
    """Levee par le rappel pour arreter la generation (la suite n'est plus utile)."""


def partial_string(buffer: str, key: str) -> tuple[str | None, bool]:
    """Valeur texte du champ ``key`` d'un objet JSON en cours d'ecriture.

    Renvoie ``(None, False)`` tant que la valeur n'a pas commence, puis ``(texte, termine)``.
    Une sequence d'echappement coupee en fin de tampon est ignoree jusqu'au fragment suivant.
    """
    match = re.search(r'"' + re.escape(key) + r'"\s*:\s*"', buffer)
    if match is None:
        return None, False
    out: list[str] = []
    index, end = match.end(), len(buffer)
    while index < end:
        char = buffer[index]
        if char == '"':
            return "".join(out), True
        if char != "\\":
            out.append(char)
            index += 1
            continue
        if index + 1 >= end:
            break
        code = buffer[index + 1]
        if code == "u":
            digits = buffer[index + 2 : index + 6]
            if len(digits) < 4:
                break
            try:
                value = int(digits, 16)
            except ValueError:
                value = 0xFFFD
            if 0xD800 <= value <= 0xDBFF:  # paire de substitution (emoji) : attendre la suite
                low = buffer[index + 6 : index + 12]
                if len(low) < 6:
                    break
                try:
                    second = int(low[2:], 16) if low.startswith("\\u") else -1
                except ValueError:
                    second = -1
                if 0xDC00 <= second <= 0xDFFF:
                    out.append(chr(0x10000 + ((value - 0xD800) << 10) + (second - 0xDC00)))
                    index += 12
                    continue
                value = 0xFFFD
            elif 0xDC00 <= value <= 0xDFFF:
                value = 0xFFFD
            out.append(chr(value))
            index += 6
            continue
        out.append(_ESCAPES.get(code, code))
        index += 2
    return "".join(out), False
