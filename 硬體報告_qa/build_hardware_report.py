from pathlib import Path
from docx import Document
from docx.shared import Mm, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "硬體與配電報告.docx"

def set_cell_shading(cell, fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = tcPr.find(qn("w:shd")) or OxmlElement("w:shd")
    shd.set(qn("w:fill"), fill)
    if shd.getparent() is None:
        tcPr.append(shd)

def font_run(run, size=12, bold=False, color=None):
    run.font.name = "Times New Roman"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "標楷體")
    run.font.size = Pt(size)
    run.bold = bold
    if color:
        run.font.color.rgb = RGBColor(*color)

def para(doc, text="", size=12, bold=False, align=None, space_after=4):
    p = doc.add_paragraph()
    p.paragraph_format.line_spacing = Pt(20)
    p.paragraph_format.space_after = Pt(space_after)
    if align is not None:
        p.alignment = align
    r = p.add_run(text)
    font_run(r, size, bold)
    return p

def heading(doc, text, level=1):
    p = doc.add_paragraph(style="Heading 1" if level == 1 else "Heading 2")
    p.paragraph_format.keep_with_next = True
    p.paragraph_format.line_spacing = Pt(22)
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(4)
    r = p.add_run(text)
    font_run(r, 16 if level == 1 else 14, True, (0, 0, 0))
    return p

def picture(doc, path, caption, width=Mm(155)):
    if path and path.exists():
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.keep_with_next = True
        p.add_run().add_picture(str(path), width=width)
    else:
        para(doc, "【照片待補：%s】" % caption, 11, False, WD_ALIGN_PARAGRAPH.CENTER)
        return
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(8)
    font_run(p.add_run(caption), 10)

def table(doc, rows, widths=None):
    t = doc.add_table(rows=0, cols=len(rows[0]))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.style = "Table Grid"
    for ri, row in enumerate(rows):
        cells = t.add_row().cells
        for ci, value in enumerate(row):
            cells[ci].text = ""
            cells[ci].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            r = cells[ci].paragraphs[0].add_run(str(value))
            font_run(r, 10 if ri else 11, ri == 0)
            if ri == 0:
                set_cell_shading(cells[ci], "E7EDF3")
    for row in t.rows:
        for cell in row.cells:
            cell.margin_top = Mm(1)
            cell.margin_bottom = Mm(1)
    return t

def main():
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Mm(210), Mm(297)
    sec.top_margin = sec.bottom_margin = sec.left_margin = sec.right_margin = Mm(12.7)
    normal = doc.styles["Normal"]
    normal.font.name = "標楷體"
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "標楷體")
    normal.font.size = Pt(12)
    footer = sec.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    font_run(footer.add_run("花生智慧辨識與自動分選系統｜硬體與配電報告"), 9)

    imgs = sorted((ROOT / "production_data" / "training_captures").glob("*/images/*.jpg"))
    hero = imgs[0] if imgs else None
    detail = imgs[len(imgs)//2] if imgs else None
    gui = Path(r"C:\Users\user\AppData\Local\Temp\codex-clipboard-08c78d7d-cef2-4da4-951d-0654d98f8149.png")
    editor = Path(r"C:\Users\user\AppData\Local\Temp\codex-clipboard-c968db78-9eba-44d3-a5be-75f1aff5d461.png")
    control_box = Path(r"C:\Users\user\OneDrive - 中原大學\桌面\大學作品集\花生機\決賽繳交資料夾\02_照片\LINE_ALBUM_機器照片_260907_5.jpg")
    cad_front = Path(r"C:\Users\user\OneDrive - 中原大學\桌面\大學作品集\花生機\決賽繳交資料夾\02_照片\花生機2.PNG")
    cad_rear = Path(r"C:\Users\user\OneDrive - 中原大學\桌面\大學作品集\花生機\決賽繳交資料夾\02_照片\花生機.PNG")
    machine_1 = Path(r"C:\Users\user\OneDrive - 中原大學\桌面\大學作品集\花生機\決賽繳交資料夾\02_照片\LINE_ALBUM_機器照片_260907_1.jpg")
    machine_2 = Path(r"C:\Users\user\OneDrive - 中原大學\桌面\大學作品集\花生機\決賽繳交資料夾\02_照片\LINE_ALBUM_機器照片_260907_2.jpg")
    machine_3 = Path(r"C:\Users\user\OneDrive - 中原大學\桌面\大學作品集\花生機\決賽繳交資料夾\02_照片\LINE_ALBUM_機器照片_260907_3.jpg")
    machine_4 = Path(r"C:\Users\user\OneDrive - 中原大學\桌面\大學作品集\花生機\決賽繳交資料夾\02_照片\LINE_ALBUM_機器照片_260907_4.jpg")

    para(doc, "2026 中興大學『AI 賦能與機器人於智慧製造應用』專題實作競賽", 13, False, WD_ALIGN_PARAGRAPH.CENTER, 10)
    para(doc, "硬體與配電系統報告", 24, True, WD_ALIGN_PARAGRAPH.CENTER, 6)
    para(doc, "花生智慧辨識與自動分選系統", 16, False, WD_ALIGN_PARAGRAPH.CENTER, 12)
    picture(doc, hero, "圖 1　花生辨識區與滾筒輸送實景（現有影像資料）", Mm(150))
    para(doc, "本報告聚焦於機構、驅動、分流與配電設計；影像辨識模型與軟體流程另以軟體報告說明。", 11, False, WD_ALIGN_PARAGRAPH.CENTER)
    doc.add_page_break()

    heading(doc, "一、設計目標與系統範圍")
    para(doc, "本系統部署於生產線末端，利用滾筒將花生排列並送入辨識區，再依辨識結果由各通道末端的撥片分流。硬體設計的重點是讓花生在相機視野內保持穩定、讓滾筒能可靠自轉，並讓良品與不良品進入不同收集位置。")
    para(doc, "本報告不描述進料機構；進料採人工投入，後續由滾筒機構形成連續排列。")

    heading(doc, "二、滾筒輸送與驅動機構")
    picture(doc, cad_front, "圖 2　整機 3D 設計圖：滾筒、撥片、漏斗與控制桿配置", Mm(145))
    picture(doc, cad_rear, "圖 3　整機 3D 設計圖：控制箱內部與驅動元件配置", Mm(145))
    table(doc, [["項目", "目前設計"], ["驅動馬達", "17HS4417 步進馬達 2 顆，同軸配置以增加可用扭矩"], ["辨識區", "相機位於辨識區正上方；辨識中心至撥片約 20 cm；無額外照明"], ["模組尺寸", "約高 20 cm、長 40 cm、寬 35 cm"], ["整機尺寸", "含控制桿與機箱約高 120 cm、寬 40 cm、長 60 cm"]])
    para(doc, "機構改版的核心問題是驅動阻力。最初以多組滾筒齒輪、滾筒間小齒輪與下方齒條帶動整圈滾筒；齒輪數量多造成摩擦力增加，馬達出現失步。後續縮短齒條、移除滾筒間小齒輪，並嘗試類似鏈條的八字形連接件，但齒輪進入齒條時容易對齒。最終取消齒條，改在辨識區滾筒下方加裝羽毛球拍握把布，以摩擦力帶動滾筒自轉，降低機構複雜度與驅動負載。")
    picture(doc, detail, "圖 2　滾筒排列與辨識區細節", Mm(155))

    heading(doc, "三、分選機構與物料路徑")
    para(doc, "影像中的觸發線、判定線與通道線是視覺輔助線，用來協助定位與判斷，不是實體結構。每個通道末端設置撥片，花生到達分流位置後由撥片導向：不良花生滑落至撥片後方、機器下方的收集盒；良品則滑向前方漏斗。")
    picture(doc, gui, "圖 3　生產畫面中的通道與輔助線（軟體顯示）", Mm(150))
    picture(doc, editor, "圖 4　影像標註畫面，供辨識資料確認使用", Mm(150))

    heading(doc, "四、控制箱與配電設計")
    para(doc, "控制箱設計參考工業設備的配置方式，將端子台、導軌與配線槽集中放置於機器下方機箱內，讓訊號線與電源線可依端子分區整理。機箱底部加裝輪子，方便移動；必要時可鎖定輪子固定位置。")
    para(doc, "控制桿配置綠、紅、黃三色按鈕、選擇開關與急停開關。綠色按鈕代表啟動／運轉，紅色按鈕代表停止，黃色按鈕用於異常清除或重新嘗試連線；急停開關用於緊急切斷設備動力。選擇開關用於調整運轉方向。")
    table(doc, [["元件", "用途"], ["端子台", "集中分配電源與控制訊號，方便維修與查線"], ["DIN 導軌", "固定端子台及控制元件"], ["配線槽", "整理並保護箱內線材"], ["急停開關", "發生危險時立即停止設備動力"], ["綠／紅／黃按鈕", "運轉、停止、異常清除／重試"], ["選擇開關", "調整運轉方向"]])
    picture(doc, control_box, "圖 5　控制箱內部：端子台、配線槽、導軌、馬達驅動器與電源供應器", Mm(145))
    picture(doc, machine_1, "圖 6　整機實體照片：滾筒、相機支架、機架與下方控制箱", Mm(135))
    picture(doc, machine_2, "圖 7　整機實體照片：控制桿、按鈕與滾筒俯視", Mm(135))
    picture(doc, machine_3, "圖 8　整機實體照片：控制桿與辨識滾筒", Mm(135))
    picture(doc, machine_4, "圖 9　整機實體照片：另一側滾筒與控制桿配置", Mm(135))
    para(doc, "目前確認本機主電源為 12V，使用 100W 電源供應器。急停開關會切斷繼電器，使整機電源停止。斷路器／保險絲規格與接地方式尚未提供，正式版應依箱內實際配置補列。")
    para(doc, "目前仍待補：控制箱正面、急停與控制桿，以及撥片側面分流照片。", 11, False, WD_ALIGN_PARAGRAPH.CENTER)

    heading(doc, "五、安全、維護與操作考量")
    para(doc, "操作前應確認滾筒、撥片與收集盒沒有異物，並確認急停開關已復位。運轉中若相機無法連線、Arduino 失聯或辨識流程發生異常，系統應進入異常狀態，停止輸送並以黃色指示提醒；排除原因後再由操作員清除異常並重試。")
    para(doc, "滾筒下方的摩擦布屬耗材，應定期檢查磨耗、髒污與固定狀況；撥片與漏斗則應檢查位置，避免良品與不良品互相混入。")

    heading(doc, "六、設計成果與待補資料")
    para(doc, "本機構、滾筒配置、分流方式、控制桿與機箱配置皆由團隊自行設計，外購項目包含步進馬達、驅動板、按鈕、選擇開關、急停開關及其他電子元件。設計過程以降低驅動負載、維持分流穩定性與提高維修可及性為主要方向。")
    table(doc, [["待補項目", "建議補充內容"], ["配電規格", "已確認 12V、100W；仍待補斷路器／保險絲與接地方式"], ["急停功能", "已確認切斷繼電器，使整機電源停止"], ["控制箱照片", "已補控制箱內部；仍可補箱體正面照片"], ["分流照片", "撥片、前方漏斗與下方不良品盒同框照片"], ["機構細節", "滾筒直徑、間距、摩擦布尺寸與固定方式"]])
    para(doc, "以上待補資料不影響本初稿的架構；補齊後可直接替換相應段落與照片，形成正式繳交版。")
    doc.save(OUT)
    print(OUT)

if __name__ == "__main__":
    main()
