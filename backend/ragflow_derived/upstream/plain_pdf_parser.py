# Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
# Licensed under the Apache License, Version 2.0.
# Modified for Chatbot-SaaS: explicit scoped imports; see port manifest.
import logging
from io import BytesIO
from pypdf import PdfReader as pdf2_read
from .parser_utils import extract_pdf_outlines
MAXIMUM_PAGE_NUMBER = 100000

class PlainParser:
    def __call__(self, filename, from_page=0, to_page=MAXIMUM_PAGE_NUMBER, **kwargs):
        lines = []
        try:
            self.pdf = pdf2_read(filename if isinstance(filename, str) else BytesIO(filename))
            for page in self.pdf.pages[from_page:to_page]:
                lines.extend([t for t in page.extract_text().split("\n")])
        except Exception:
            logging.exception("Outlines exception")
        self.outlines = extract_pdf_outlines(filename)

        return [(line, "") for line in lines], []

    def crop(self, ck, need_position):
        raise NotImplementedError

    @staticmethod
    def remove_tag(txt):
        raise NotImplementedError
