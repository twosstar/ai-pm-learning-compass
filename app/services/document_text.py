import io
import re
import zipfile
import tempfile
from pathlib import Path
from xml.etree import ElementTree

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_EXTRACTED_CHARS = 200_000
SUPPORTED_SUFFIXES = {".txt", ".md", ".csv", ".json", ".docx", ".pdf"}
WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class DocumentTextExtractor:
    @staticmethod
    def _clean(text: str) -> str:
        text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()[:MAX_EXTRACTED_CHARS]

    @staticmethod
    def _plain_text(content: bytes) -> str:
        for encoding in ("utf-8-sig", "utf-16", "gb18030"):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise ValueError("文本编码无法识别，请将文件另存为 UTF-8 后重试。")

    @staticmethod
    def _docx(content: bytes) -> str:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                info = archive.getinfo("word/document.xml")
                if info.file_size > 20 * 1024 * 1024:
                    raise ValueError("Word 文档解压后的正文过大，请拆分后上传。")
                root = ElementTree.fromstring(archive.read(info))
        except (KeyError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
            raise ValueError("无法读取这个 Word 文件，请确认它是有效的 .docx 文档。") from exc
        paragraphs = []
        table_paragraphs = {id(paragraph) for table in root.iter(f"{WORD_NAMESPACE}tbl") for paragraph in table.iter(f"{WORD_NAMESPACE}p")}
        for paragraph in root.iter(f"{WORD_NAMESPACE}p"):
            if id(paragraph) in table_paragraphs:
                continue
            text = "".join(node.text or "" for node in paragraph.iter(f"{WORD_NAMESPACE}t"))
            if text.strip():
                paragraphs.append(text.strip())
        return "\n".join(paragraphs)

    @staticmethod
    def _pdf(content: bytes) -> str:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("PDF 解析组件尚未安装，请重新安装项目依赖后重试。") from exc
        try:
            reader = PdfReader(io.BytesIO(content))
            if reader.is_encrypted:
                try:
                    reader.decrypt("")
                except Exception as exc:
                    raise ValueError("这个 PDF 已加密，暂时无法读取。") from exc
            pages = []
            for page in reader.pages[:500]:
                pages.append(page.extract_text() or "")
                if sum(len(item) for item in pages) >= MAX_EXTRACTED_CHARS:
                    break
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("无法读取这个 PDF，文件可能已损坏或使用了不支持的加密方式。") from exc
        text = "\n\n".join(pages)
        missing = {index + 1 for index, value in enumerate(pages) if len(value.strip()) < 20}
        if len(text.strip()) < 2:
            missing = set(range(1, len(pages) + 1))
        if missing:
            from app.services.pdf_ocr import extract_pdf_ocr
            with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
                handle.write(content)
                handle.flush()
                ocr_pages = dict(extract_pdf_ocr(Path(handle.name), page_numbers=missing))
            pages = [ocr_pages.get(index + 1, value) if index + 1 in missing else value for index, value in enumerate(pages)]
            text = "\n\n".join(pages)
        if len(text.strip()) < 2:
            raise ValueError("这个扫描 PDF 未识别出文字，请确认 OCR 语言包已安装。")
        return text

    def extract(self, filename: str, content: bytes) -> tuple[str, str]:
        suffix = Path(filename).suffix.casefold()
        if suffix not in SUPPORTED_SUFFIXES:
            raise ValueError("仅支持 TXT、Markdown、CSV、JSON、DOCX 和 PDF 文件。")
        if not content:
            raise ValueError("文件内容为空。")
        if len(content) > MAX_UPLOAD_BYTES:
            raise ValueError("单个文件不能超过 10 MB，请拆分后上传。")
        if suffix == ".docx":
            text, input_kind = self._docx(content), "docx_file"
        elif suffix == ".pdf":
            text, input_kind = self._pdf(content), "pdf_file"
        else:
            text, input_kind = self._plain_text(content), "text_file"
        cleaned = self._clean(text)
        if len(cleaned) < 2:
            raise ValueError("文档中没有识别到可导入的文字。")
        return cleaned, input_kind


document_text_extractor = DocumentTextExtractor()
