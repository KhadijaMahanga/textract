import cv2
import pandas as pd
import pdfplumber
import time

from paddleocr import PPStructure
from tabulate import tabulate

tabulate.PRESERVE_WHITESPACE = True

def extract_explicit_table(page, bbox):
    t = page.crop(bbox).extract_table(table_settings={"vertical_strategy": "text", 
    "horizontal_strategy": "text"})
    print(t)
    table_str = tabulate(t, tablefmt="grid")
    return table_str



    pass

def run():
    path = "tablextract/sample2.pdf"
    doc = pdfplumber.open(path)  # open document

    page = doc.pages[1]
    pix = page.to_image(resolution=250)
    img_path = f"tablextract/sample2-page-1.png"
    pix.save(img_path)  # store image as a PNG

    time.sleep(1)
    

    table_engine = PPStructure(table=True)
    img = cv2.imread(img_path)
    result = table_engine(img)

    doc_text = ""

    for l in result:
        l.pop('img')
        if l.get("type") == "table_caption":
            c_bbox = l.get("bbox")
        elif l.get("type") == "table":
            html_table = l.get("res").get("html")
            print(html_table)
            html_data = pd.read_html(html_table)
            
            # t_str = extract_explicit_table(page, t_bbox)
            doc_text += tabulate(html_data[0].values.tolist(), tablefmt="grid")

    with open("sampl2e.txt", "w") as output_file:
        output_file.write(doc_text)
    output_file.close
