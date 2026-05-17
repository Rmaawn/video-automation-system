"""Script processor — raw Persian text → natural spoken script."""

import re

from config.settings import settings
from utils.logger import setup_logger

logger = setup_logger(__name__)


class ScriptProcessor:
    """Converts written Persian into conversational speech text."""

    def __init__(self):
        self._max_len = settings.get("script.max_sentence_length", 120)
        self._pause = settings.get("script.pause_marker", "...")
        self._prefixes = settings.get("script.conversational_prefixes", [])

    def process(self, raw_text: str) -> str:
        text = self._clean(raw_text)
        text = self._split_long(text)
        text = self._conversationalize(text)
        text = self._add_pauses(text)
        return self._normalize(text)

    def _clean(self, text: str) -> str:
        text = re.sub(r"\*\*|__|~~|`", "", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        lines = [line.strip() for line in text.split("\n")]
        text = "\n".join(filter(None, lines))
        text = text.replace("\u0643", "\u06a9")
        text = text.replace("\u064a", "\u06cc")
        text = text.replace("\u0649", "\u06cc")
        return text.strip()

    def _split_long(self, text: str) -> str:
        sentences = re.split(r"([.!?؟]+)", text)
        result = []
        current = ""

        for part in sentences:
            if re.match(r"^[.!?؟]+$", part):
                current += part
                if len(current) <= self._max_len:
                    result.append(current)
                    current = ""
                else:
                    result.extend(self._split_by_conjunctions(current))
                    current = ""
            else:
                current += part

        if current.strip():
            if len(current) > self._max_len:
                result.extend(self._split_by_conjunctions(current))
            else:
                result.append(current)

        return "".join(result)

    def _split_by_conjunctions(self, text: str) -> list[str]:
        conjunctions = [
            r"\sو\s", r"\sاما\s", r"\sولی\s", r"\sبنابراین\s",
            r"\sپس\s", r"\sیعنی\s", r"\sبه علاوه\s", r"\sچون\s",
            r"\sزیرا\s", r"\sهمچنین\s",
        ]
        parts = [text]
        for conj in conjunctions:
            new_parts = []
            for part in parts:
                if len(part) <= self._max_len:
                    new_parts.append(part)
                else:
                    splits = re.split(f"({conj})", part)
                    buffer = ""
                    for sp in splits:
                        if re.match(conj, sp):
                            buffer += sp
                        else:
                            if buffer:
                                new_parts.append(buffer.strip())
                                buffer = sp
                            else:
                                buffer += sp
                    if buffer.strip():
                        new_parts.append(buffer.strip())
            parts = new_parts

        final = []
        for part in parts:
            if len(part) <= self._max_len:
                final.append(part)
            else:
                subs = part.split("،")
                buf = ""
                for s in subs:
                    if len(buf + s) < self._max_len:
                        buf += ("،" if buf else "") + s
                    else:
                        if buf:
                            final.append(buf + "۔")
                        buf = s
                if buf:
                    final.append(buf)

        result = []
        for i, part in enumerate(final):
            part = part.strip()
            if part and not re.search(r"[.!?؟۔]$", part):
                part += "۔" if i < len(final) - 1 else "."
            result.append(part)

        return result

    def _conversationalize(self, text: str) -> str:
        sentences = re.split(r"([.!?؟۔]+)", text)
        result = []
        used = 0
        max_use = 2

        i = 0
        while i < len(sentences) - 1:
            sentence = sentences[i]
            punct = sentences[i + 1] if i + 1 < len(sentences) else ""

            if (len(sentence) > 50
                    and used < max_use
                    and not any(sentence.startswith(p) for p in self._prefixes)):
                prefix = self._prefixes[used % len(self._prefixes)]
                result.append(f"{prefix}، {sentence}")
                used += 1
            else:
                result.append(sentence)

            result.append(punct)
            i += 2

        if i < len(sentences):
            result.append(sentences[-1])

        return "".join(result)

    def _add_pauses(self, text: str) -> str:
        transitions = [
            ("اما", f"\n{self._pause} "),
            ("ولی", f"\n{self._pause} "),
            ("و نکته مهمتر", f"\n{self._pause} "),
            ("جالب اینجاست", f"\n{self._pause} "),
            ("در نتیجه", f"\n{self._pause} "),
        ]
        for trigger, replacement in transitions:
            text = text.replace(trigger, replacement + trigger)
        return text

    def _normalize(self, text: str) -> str:
        text = re.sub(r"\s+([.!?؟،:;])", r"\1", text)
        text = re.sub(r" {2,}", " ", text)
        lines = [line.strip() for line in text.split("\n")]
        return "\n".join(filter(None, lines)).strip()
