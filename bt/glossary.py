"""Глоссарий: имена и термины, которые обязаны звучать одинаково во всей книге.

Три задачи:
1. дать модели только те записи, которые встречаются в текущем фрагменте;
2. не дать ей придумать второй вариант уже закреплённого имени;
3. проверить после перевода, что закреплённые варианты действительно на месте.

Формат хранения — JSON. Загрузка — из JSON или из markdown-таблицы (в прошлой
книге глоссарий вёлся именно таблицей).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field

TYPE_LABELS = {
    "person": "человек",
    "place": "место",
    "org": "организация",
    "term": "термин",
    "item": "предмет",
    "other": "прочее",
}


@dataclass
class Term:
    en: str
    ru: str
    type: str = "other"
    gender: str = ""
    declinable: bool = True
    note: str = ""
    forbidden: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Term":
        return cls(
            en=data.get("en", "").strip(),
            ru=data.get("ru", "").strip(),
            type=data.get("type", "other"),
            gender=data.get("gender", ""),
            declinable=bool(data.get("declinable", True)),
            note=data.get("note", ""),
            forbidden=list(data.get("forbidden") or []),
        )


class Glossary:
    def __init__(self, terms: list[Term] | None = None):
        self.terms: list[Term] = []
        self._compiled: list[tuple[Term, re.Pattern[str]]] = []
        for term in terms or []:
            self.add(term)

    # ------------------------------------------------------------------ загрузка

    @classmethod
    def from_json(cls, path: str) -> "Glossary":
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            data = data.get("terms", [])
        return cls([Term.from_dict(item) for item in data])

    @classmethod
    def from_markdown(cls, path: str) -> "Glossary":
        """Читает таблицы `| оригинал | русский | примечание |` из glossary.md."""
        terms: list[Term] = []
        seen: set[str] = set()
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                raw = line.strip()
                if not raw.startswith("|") or raw.count("|") < 3:
                    continue
                cells = [c.strip() for c in raw.strip("|").split("|")]
                if len(cells) < 2:
                    continue
                en, ru = cells[0], cells[1]
                if not en or not ru:
                    continue
                if set(en) <= {"-", ":", " "} or set(ru) <= {"-", ":", " "}:
                    continue
                if en.lower() in ("оригинал", "english", "en"):
                    continue
                note = cells[2] if len(cells) > 2 else ""
                key = en.lower()
                if key in seen:
                    continue
                seen.add(key)
                terms.append(
                    Term(
                        en=en,
                        ru=ru,
                        type=_guess_type(note),
                        note=note,
                    )
                )
        return cls(terms)

    @classmethod
    def load(cls, path: str) -> "Glossary":
        if path.lower().endswith(".json"):
            return cls.from_json(path)
        return cls.from_markdown(path)

    def save_json(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"terms": [t.to_dict() for t in self.terms]}, fh, ensure_ascii=False, indent=1)

    # ------------------------------------------------------------------- работа

    def add(self, term: Term) -> None:
        if not term.en or not term.ru:
            return
        existing = next((t for t in self.terms if t.en.lower() == term.en.lower()), None)
        if existing:
            return
        self.terms.append(term)
        pattern = re.compile(rf"(?<![A-Za-z]){re.escape(term.en)}(?![A-Za-z])", re.IGNORECASE)
        self._compiled.append((term, pattern))

    def match(self, text: str) -> list[Term]:
        """Записи, которые встречаются в тексте (в порядке появления)."""
        found: list[tuple[int, Term]] = []
        for term, pattern in self._compiled:
            m = pattern.search(text)
            if m:
                found.append((m.start(), term))
        found.sort(key=lambda pair: pair[0])
        return [t for _, t in found]

    def render(self, terms: list[Term]) -> str:
        lines = []
        for term in terms:
            bits = [TYPE_LABELS.get(term.type, term.type)]
            if term.gender:
                bits.append(f"род: {term.gender}")
            if not term.declinable:
                bits.append("не склоняется")
            note = term.note.strip()
            line = f"- {term.en} → {term.ru} ({', '.join(bits)})"
            if note:
                line += f" — {note}"
            lines.append(line)
        return "\n".join(lines)

    def core(self, limit: int = 15) -> list[Term]:
        """Ядро книги: термины мира, которые полезны в каждом фрагменте."""
        terms = [t for t in self.terms if t.type == "term"]
        return terms[:limit]

    def forbidden_variants(self) -> list[str]:
        out: list[str] = []
        for term in self.terms:
            out.extend(term.forbidden)
        return out

    def violations(self, source: str, translated: str) -> list[str]:
        """Термин был в оригинале, но закреплённого перевода нет (или есть запрещённый)."""
        problems: list[str] = []
        low_ru = translated.lower()
        for term in self.match(source):
            stem = term.ru.lower()[: max(4, min(6, len(term.ru)))]
            if stem and stem not in low_ru:
                problems.append(f"{term.en} → ожидалось «{term.ru}»")
            for bad in term.forbidden:
                if bad.lower() in low_ru:
                    problems.append(f"{term.en}: запрещённый вариант «{bad}»")
        return problems

    def fingerprint(self) -> str:
        payload = json.dumps([t.to_dict() for t in self.terms], ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def __len__(self) -> int:
        return len(self.terms)


def _guess_type(note: str) -> str:
    low = note.lower()
    if any(word in low for word in ("гл.", "рассказчик", "брат", "отец", "мать", "профессор", "студент")):
        return "person"
    if any(word in low for word in ("город", "топоним", "королевств", "академ", "шпиль")):
        return "place"
    if "термин" in low or "магия" in low:
        return "term"
    return "other"
