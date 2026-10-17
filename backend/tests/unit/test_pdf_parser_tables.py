from app.rag.parser.pdf_parser import PdfParser


def test_full_page_layout_table_repeating_text_layer_is_suppressed():
    page_text = (
        "第一章 总则\n"
        "第一条 为加强商业银行理财业务监督管理,制定本办法。\n"
        "第二条 本办法适用于境内设立的商业银行。"
    )
    table_text = (
        "【表】\n| | 第一章 总则 | |\n|---|---|---|\n"
        "| | 第一条 为加强商业银行理财业务监督管理,制定本办法。 | |\n"
        "| | 第二条 本办法适用于境内设立的商业银行。 | |"
    )

    assert PdfParser._is_duplicate_page_table(table_text, page_text)


def test_local_table_is_preserved_when_page_has_other_text():
    page_text = (
        "第一章 总则。" * 8
        + "表一：产品类别、最低投资金额、风险等级。"
        + "附注：银行还应当披露产品期限和费用。" * 8
    )
    table_text = "【表】\n| 产品类别 | 最低投资金额 | 风险等级 |\n|---|---|---|\n| 公募 | 1元 | 中低 |"

    assert not PdfParser._is_duplicate_page_table(table_text, page_text)
