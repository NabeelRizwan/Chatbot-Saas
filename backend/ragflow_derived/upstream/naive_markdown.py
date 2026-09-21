# Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
# Licensed under the Apache License, Version 2.0.
# Modified for Chatbot-SaaS: explicit scoped imports; see port manifest.
import re
from functools import reduce
from markdown import markdown
from .codecs import decode_text
from .markdown_parser import RAGFlowMarkdownParser as MarkdownParser, MarkdownElementExtractor
from .image_utils import concat_img
from .runtime import num_tokens_from_string

def _is_short_header(text, max_tokens=50):
    """
    Check if text is a short markdown header.

    Args:
        text: The text to check
        max_tokens: Maximum tokens for a header to be considered "short"

    Returns:
        bool: True if text is a short markdown header, False otherwise
    """
    if not text or not text.strip():
        return False

    # Check if it matches markdown header pattern: 1-6 # followed by space
    if not re.match(r"^#{1,6}\s+", text.strip()):
        return False

    # Check if token count is below threshold
    return num_tokens_from_string(text) < max_tokens


class Markdown(MarkdownParser):
    def md_to_html(self, sections):
        if not sections:
            return []
        if isinstance(sections, type("")):
            text = sections
        elif isinstance(sections[0], type("")):
            text = sections[0]
        else:
            return []

        from bs4 import BeautifulSoup

        html_content = markdown(text)
        soup = BeautifulSoup(html_content, "html.parser")
        return soup

    def get_hyperlink_urls(self, soup):
        if soup:
            return set([a.get("href") for a in soup.find_all("a") if a.get("href")])
        return []

    def extract_image_urls_with_lines(self, text):
        md_img_re = re.compile(r"!\[[^\]]*\]\(([^)\s]+)")
        html_img_re = re.compile(r'src=["\\\']([^"\\\'>\\s]+)', re.IGNORECASE)
        urls = []
        seen = set()
        lines = text.splitlines()
        for idx, line in enumerate(lines):
            for url in md_img_re.findall(line):
                if (url, idx) not in seen:
                    urls.append({"url": url, "line": idx})
                    seen.add((url, idx))
            for url in html_img_re.findall(line):
                if (url, idx) not in seen:
                    urls.append({"url": url, "line": idx})
                    seen.add((url, idx))

        # cross-line
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(text, "html.parser")
            newline_offsets = [m.start() for m in re.finditer(r"\n", text)] + [len(text)]
            for img_tag in soup.find_all("img"):
                src = img_tag.get("src")
                if not src:
                    continue

                tag_str = str(img_tag)
                pos = text.find(tag_str)
                if pos == -1:
                    # fallback
                    pos = max(text.find(src), 0)
                line_no = 0
                for i, off in enumerate(newline_offsets):
                    if pos <= off:
                        line_no = i
                        break
                if (src, line_no) not in seen:
                    urls.append({"url": src, "line": line_no})
                    seen.add((src, line_no))
        except Exception as e:
            logging.error("Failed to extract image urls: {}".format(e))
            pass

        return urls

    def load_images_from_urls(self, urls, cache=None):
        # Uploaded references never authorize network/filesystem reads.
        return [], cache or {}

    def __call__(self, filename, binary=None, separate_tables=True, delimiter=None, return_section_images=False):
        """Parse markdown into text sections and optional standalone table chunks."""
        if binary is not None:
            txt, _ = decode_text(binary, document_type="Markdown document")
        else:
            with open(filename, "r") as f:
                txt = f.read()

        remainder, tables = self.extract_tables_and_remainder(f"{txt}\n", separate_tables=separate_tables)
        parsing_text = remainder
        extractor = MarkdownElementExtractor(parsing_text)
        image_refs = self.extract_image_urls_with_lines(parsing_text)
        element_sections = extractor.extract_elements(delimiter, include_meta=True)

        sections = []
        section_images = []
        image_cache = {}
        for element in element_sections:
            content = element["content"]
            start_line = element["start_line"]
            end_line = element["end_line"]
            urls_in_section = [ref["url"] for ref in image_refs if start_line <= ref["line"] <= end_line]
            imgs = []
            if urls_in_section:
                imgs, image_cache = self.load_images_from_urls(urls_in_section, image_cache)
            combined_image = None
            if imgs:
                combined_image = reduce(concat_img, imgs) if len(imgs) > 1 else imgs[0]
            sections.append((content, ""))
            section_images.append(combined_image)

        tbls = []
        if separate_tables:
            for table in tables:
                tbls.append(((None, markdown(table, extensions=["markdown.extensions.tables"])), ""))
        if return_section_images:
            return sections, tbls, section_images
        return sections, tbls


def merge_markdown_sections(sections, section_images, chunk_limit, overlapped_percent=0):
    merged_chunks = []
    merged_images = []
    chunk_limit = max(0, int(chunk_limit))

    current_text = ""
    current_tokens = 0
    current_image = None

    for idx, sec in enumerate(sections):
        text = sec[0] if isinstance(sec, tuple) else sec
        sec_tokens = num_tokens_from_string(text)
        sec_image = section_images[idx] if section_images and idx < len(section_images) else None

        # Don't finalize chunk if current_text is a short header (force merge with next section)
        if current_text and not _is_short_header(current_text) and current_tokens + sec_tokens > chunk_limit:
            merged_chunks.append(current_text)
            merged_images.append(current_image)
            overlap_part = ""
            if overlapped_percent > 0:
                overlap_len = int(len(current_text) * overlapped_percent / 100)
                if overlap_len > 0:
                    overlap_part = current_text[-overlap_len:]
            current_text = overlap_part
            current_tokens = num_tokens_from_string(current_text)
            current_image = current_image if overlap_part else None

        if current_text:
            current_text += "\n" + text
        else:
            current_text = text
        current_tokens += sec_tokens

        if sec_image:
            current_image = concat_img(current_image, sec_image) if current_image else sec_image

    if current_text:
        merged_chunks.append(current_text)
        merged_images.append(current_image)
    return merged_chunks, merged_images
