""" Implements the logic for handling a PDF document """

from typing import Self
from io import BytesIO
from pypdf import PdfReader
from pypdf.errors import PyPdfError

class PDFError(Exception):
    pass


class PDF:
    """ Implements a (virtual) PDF object """

    def __init__(self, content: BytesIO) -> None:
        self.content = content
        self.pdf_reader = PdfReader(content) 
        try:
            self.num_pages = self.pdf_reader.get_num_pages()
        except PyPdfError as ex:
            raise PDFError("")

    def merge_duplex(self, other: Self) -> Self:
        if not isinstance(other, PDF):
            raise ValueError(f"Can not merge with <{type(other)}>")
        
    
    def __del__(self):
