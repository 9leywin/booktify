"""Общие мелочи для импортёров: пространства имён, чтение zip без учёта регистра."""

from __future__ import annotations

import posixpath
import zipfile

from lxml import etree

XHTML = "http://www.w3.org/1999/xhtml"
OPF = "http://www.idpf.org/2007/opf"
DC = "http://purl.org/dc/elements/1.1/"
CONTAINER = "urn:oasis:names:tc:opendocument:xmlns:container"
EPUB_TYPE = "http://www.idpf.org/2007/ops"
FB2 = "http://www.gribuser.ru/xml/fictionbook/2.0"
XLINK = "http://www.w3.org/1999/xlink"

NS = {
    "x": XHTML,
    "opf": OPF,
    "dc": DC,
    "c": CONTAINER,
    "epub": EPUB_TYPE,
    "fb": FB2,
    "l": XLINK,
}


def localname(tag: object) -> str:
    """`{ns}p` → `p`; комментарии и PI отдают пустую строку."""
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1].lower()


def parse_xml(data: bytes) -> etree._Element:
    parser = etree.XMLParser(
        recover=True, resolve_entities=False, huge_tree=True, remove_blank_text=False
    )
    return etree.fromstring(data, parser=parser)


class EpubArchive:
    """Чтение EPUB: имена внутри архива иногда отличаются регистром."""

    def __init__(self, path: str):
        self.path = path
        self.zf = zipfile.ZipFile(path)
        self._by_lower = {n.lower(): n for n in self.zf.namelist()}

    def __enter__(self) -> "EpubArchive":
        return self

    def __exit__(self, *exc: object) -> None:
        self.zf.close()

    def names(self) -> list[str]:
        return list(self.zf.namelist())

    def resolve(self, name: str) -> str:
        if name in self.zf.namelist():
            return name
        found = self._by_lower.get(name.lower())
        if found is None:
            raise KeyError(f"в архиве нет файла {name!r}")
        return found

    def read(self, name: str) -> bytes:
        return self.zf.read(self.resolve(name))

    def has(self, name: str) -> bool:
        return name.lower() in self._by_lower


def join_href(base: str, href: str) -> str:
    """Путь внутри EPUB: от каталога OPF к файлу, без ведущего слэша."""
    return posixpath.normpath(posixpath.join(posixpath.dirname(base), href)).lstrip("/")
