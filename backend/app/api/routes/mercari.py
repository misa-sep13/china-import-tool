"""メルカリShopsの注文CSVを、ラベル発行ツールの形に変換する。

これまではスプレッドシートのマクロでやっていたが、使えなくなった。
ファイルを上げると、変換したCSVがそのまま落ちてくる。
"""
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
import io
from datetime import date

from app.services import mercari_shops

router = APIRouter(prefix="/mercari", tags=["mercari"])


@router.post("/preview")
async def preview(file: UploadFile = File(...)):
    """中身を見せるだけ。出す前に内容を確かめられるようにする。"""
    try:
        rows, notes = mercari_shops.convert(await file.read())
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not rows:
        raise HTTPException(400, "注文が見つかりませんでした。"
                                 "メルカリShopsの注文CSVか確認してください。")
    return {"headers": mercari_shops.HEADERS, "rows": rows, "notes": notes}


@router.post("/convert")
async def convert(file: UploadFile = File(...)):
    """変換したCSVを返す。ラベル発行ツールに合わせて Shift_JIS。"""
    try:
        rows, _ = mercari_shops.convert(await file.read())
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not rows:
        raise HTTPException(400, "注文が見つかりませんでした。")
    content = mercari_shops.to_csv(rows)
    name = f"mercari_{date.today().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        io.BytesIO(content),
        media_type="text/csv; charset=shift_jis",
        headers={"Content-Disposition": f"attachment; filename={name}"},
    )
