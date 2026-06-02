import io
from typing import List, Dict
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

def build_taotaro_excel(items: List[Dict]) -> bytes:
    """TAO太郎テンプレート形式のExcelを生成してbytesで返す"""
    wb = Workbook()
    ws = wb.active
    ws.title = "銀行振込"

    # ヘッダ
    headers = [
        "リパック", "セット", "SKU", "商品名", "AmazonURL", "No",
        "発注先URL", "画像URL", "色", "サイズ/規格", "数量", "単価(元)", "小計(元)",
        "", "", "", "", "", "", "", "", "", "", "備考"
    ]
    header_fill = PatternFill("solid", fgColor="CFE2F3")
    header_font = Font(bold=True)
    thin = Side(style="thin")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border

    # データ行（10行目から、TAO太郎テンプレに合わせる）
    DATA_START = 10
    # 行9まで空行
    for data_row, item in enumerate(items, DATA_START):
        row_num = data_row
        values = {
            1:  item.get("repack", ""),
            2:  item.get("set_size", 1),
            3:  item.get("sku", ""),
            4:  item.get("name", ""),
            5:  item.get("amazon_url", ""),
            6:  data_row - DATA_START + 1,
            7:  item.get("buy_url", ""),
            8:  item.get("photo_url", ""),
            9:  item.get("color", ""),
            10: item.get("size", ""),
            11: item.get("qty", 0),
            12: item.get("price", 0),
            13: f"=K{row_num}*L{row_num}",
            24: item.get("note", ""),
        }
        for col, val in values.items():
            cell = ws.cell(row=row_num, column=col, value=val)
            cell.border = border
            cell.alignment = Alignment(vertical="center", wrap_text=True)

    # 列幅調整
    col_widths = {
        1: 8, 2: 6, 3: 18, 4: 30, 5: 35, 6: 5,
        7: 35, 8: 35, 9: 12, 10: 12, 11: 8, 12: 8, 13: 10, 24: 20
    }
    for col, width in col_widths.items():
        ws.column_dimensions[get_column_letter(col)].width = width

    ws.row_dimensions[1].height = 30

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
