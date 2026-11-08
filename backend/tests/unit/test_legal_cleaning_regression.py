from app.rag.cleaner import cleaner
from app.rag.chunker import chunker
from app.rag.chunker import ARTICLE_RE
from app.rag.types import PageContent, ParsedDocument, TextBlock


def test_ocr_article_heading_without_space_is_recognized():
    match = ARTICLE_RE.match("第三十九条净稳定资金比例应当不低于100%。")
    assert match is not None
    assert match.group(1) == "第三十九条"


def test_chapter_and_section_do_not_swallow_following_article():
    text = "第一章 总则\n第一条 商业银行应当建立风险管理制度。\n第一节 管理职责\n第二条 董事会承担管理职责。"
    doc = ParsedDocument(file_name="test.pdf", file_ext=".pdf", parse_method="text", meta={}, pages=[
        PageContent(page_no=1, blocks=[TextBlock(type="text", text=text, page_no=1)], char_count=len(text), used_ocr=False)
    ])
    chunks = chunker.split(cleaner.clean_parsed(doc))
    body = "\n".join(chunk.raw_content for chunk in chunks)
    assert "第一条 商业银行应当建立风险管理制度。" in body
    assert "第二条 董事会承担管理职责。" in body


def test_repeated_headers_inside_page_block_are_removed():
    pages = []
    for number in range(1, 4):
        text = f"监管机构发布\n第{number}条 商业银行应当保留本页不同的制度内容。\n页脚机构"
        pages.append(PageContent(page_no=number, blocks=[TextBlock(type="text", text=text, page_no=number)], char_count=len(text), used_ocr=False))
    doc = ParsedDocument(file_name="test.pdf", file_ext=".pdf", parse_method="text", meta={}, pages=pages)
    cleaned = cleaner.clean_parsed(doc)
    body = "\n".join(block.text for page in cleaned.pages for block in page.blocks)
    assert "监管机构发布" not in body
    assert "页脚机构" not in body
    assert all(f"第{number}条" in body for number in range(1, 4))
