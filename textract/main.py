import argparse
import fitz
import os
import pdfplumber
import time

from loguru import logger
from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextContainer, LTChar
from tabulate import tabulate

tabulate.PRESERVE_WHITESPACE = True

def obj_in_bbox(obj, _bbox, page_height):
    objx0, y0, objx1, y1 = obj
    x0, top, x1, bottom = _bbox
    return (objx0 >= x0) and (objx1 <= x1) and (page_height - y1 >= top) and (page_height - y0 <= bottom)

def clean_string(str):
    m = str.split("\n")
    cleaned_m = filter(lambda x: len(x) > 1, m)
    return "\n".join(cleaned_m)


def recoverpix(doc, item):
    xref = item[0]  # xref of PDF image
    smask = item[1]  # xref of its /SMask

    # special case: /SMask or /Mask exists
    if smask > 0:
        pix0 = fitz.Pixmap(doc.extract_image(xref)["image"])
        if pix0.alpha:  # catch irregular situation
            pix0 = fitz.Pixmap(pix0, 0)  # remove alpha channel
        mask = fitz.Pixmap(doc.extract_image(smask)["image"])

        try:
            pix = fitz.Pixmap(pix0, mask)
        except:  # fallback to original base image in case of problems
            pix = fitz.Pixmap(doc.extract_image(xref)["image"])

        if pix0.n > 3:
            ext = "pam"
        else:
            ext = "png"

        return {  # create dictionary expected by caller
            "ext": ext,
            "colorspace": pix.colorspace.n,
            "image": pix.tobytes(ext),
        }

    # special case: /ColorSpace definition exists
    # to be sure, we convert these cases to RGB PNG images
    if "/ColorSpace" in doc.xref_object(xref, compressed=True):
        pix = fitz.Pixmap(doc, xref)
        pix = fitz.Pixmap(fitz.csRGB, pix)
        return {  # create dictionary expected by caller
            "ext": "png",
            "colorspace": 3,
            "image": pix.tobytes("png"),
        }
    return doc.extract_image(xref)


def check_for_image(pdf_path, file_):
    """
    This function checkes for images from PDF file and save them to local folder
    """
    pictogram_str_list = []

    pdf_document = fitz.open(pdf_path)
    xreflist = []

    page_num = 0
    il = pdf_document.get_page_images(page_num)
    logger.info(f"Found {len(il)} images")
    for img in il:
        xref = img[0]
        if xref in xreflist:
            continue
        width = img[2]
        height = img[3]
        if min(width, height) <= 5:
            continue
        image = recoverpix(pdf_document, img)
        n = image["colorspace"]
        imgdata = image["image"]

        # if len(imgdata) <= 2048: #ignore less than 2KB
        #     continue
        # if len(imgdata) / (width * height * n) <= 0.05: #image size ration must be larger than 5%
        #     continue

        imgfile = os.path.join(f"data/processed/images/{file_}-img-{xref}-{page_num + 1}.{image['ext']}")
        fout = open(imgfile, "wb")
        fout.write(imgdata)
        fout.close()
        xreflist.append(xref)
        
        # for my specific problem, I went further to check comparison with a number of pictogram that I had

def check_for_drawings(pdf_path, file_):
    """
    This function checkes for drawings from PDF files, perform filters, and save them to local folder
    """
    pictogram_str_list = []
    pdf_document = fitz.open(pdf_path)

    for page_num in range(pdf_document.page_count):
        page = pdf_document[page_num]

        d = page.get_drawings()
        new_rects = []
        for p in d:
            if p["rect"].is_empty:
                continue
            w = p["width"]
            if w:
                r = p["rect"] + (-w, -w, w, w)  # enlarge each rectangle by width value
                for i in range(len(new_rects)):
                    if abs(r & new_rects[i]) > 0:  # touching one of the new rects?
                        new_rects[i] |= r  # enlarge it
                        break

                # now look if contained in one of the new rects
                remainder = [s for s in new_rects if r in s]
                if remainder == []:  # no ==> add this rect to new rects
                    new_rects.append(r)

        new_rects = list(set(new_rects))  # remove any duplicates (eg:.if a smaller drwaing is within another drawing, etc)
        new_rects.sort(key=lambda r: abs(r), reverse=True)
        remove = []
        for j in range(len(new_rects)):
            for i in range(len(new_rects)):
                if new_rects[j] in new_rects[i] and i != j:
                    remove.append(j)
        remove = list(set(remove))
        for i in reversed(remove):
            del new_rects[i]
        new_rects.sort(key=lambda r: (r.tl.y, r.tl.x))  # sort by location


        mat = fitz.Matrix(5, 5)  # high resolution matrix
        for i, r in enumerate(new_rects):
            if r.width is None or r.height <= 15 or r.width <= 15:
                continue  # skip lines and empty rects
            pix = page.get_pixmap(matrix=mat, clip=r)
            hayPath = f"data/processed/images/{file_}-drawing-{page_num}-{i}.png"
            if pix.n - pix.alpha >= 4:      # can be saved as PNG
                pix = fitz.Pixmap(fitz.csRGB, pix)
            pix.save(hayPath)
            pix = None                     # free Pixmap resources
        
            
    pdf_document.close() 


def parse_figure_layout(layout):
    res = ""
    for lobj in layout:
        if isinstance(lobj, LTChar):
            res += lobj.get_text()
        
        elif isinstance(lobj, LTFigure):
            res += parse_figure_layout(lobj)

    return res

    
def miner_extract_page(page_layout, tables):
    output_str = ""
    page_height = page_layout.height
    printedTables = []

    for element in page_layout:
        if isinstance(element, LTTextContainer):
            tabBox = []
            for t in tables:
                is_obj_n_box = obj_in_bbox(element.bbox, t.bbox, page_height)
                if is_obj_n_box:
                    tabBox.append(t)

            if not len(tabBox):
                if isinstance(element, LTTextContainer):
                    elementText = element.get_text()
                else:
                    logger.info("I am here")
                    elementText = parse_figure_layout(element)
                
                output_str += elementText 

            else:
                if not tabBox[0] in printedTables:
                    table_str = tabulate(tabBox[0].extract(), tablefmt="grid")
                    output_str += "\n" + table_str
                    output_str += "\n"
                    printedTables.append(tabBox[0])


    if len(tables) != len(printedTables):
        missed_tables = filter(lambda x: x not in printedTables, tables)
        for m_t in missed_tables:
            table_str = tabulate(m_t.extract(), tablefmt="grid") + "\n"
            output_str += table_str


    clean_str = output_str
    return clean_str
    

def pdf_process(path):

    # start text and table extraction
    plumberObj = pdfplumber.open(path)
    minerPages = extract_pages(path)

    doc_text =  ""
    for i, page_layout in enumerate(minerPages):
        plumberPage = plumberObj.pages[i]

        tables = plumberPage.find_tables(table_settings={"text_vertical_ttb": False, "snap_tolerance": 2, "join_tolerance": 2})
        page_text = miner_extract_page(page_layout, tables)

        doc_text += page_text


    file_ = path.replace(".pdf", "").split("/")[-1]
    file_name = file_.lower().replace(" ", "_").replace("-", "_").replace(",", "_")

    result_file = f"data/processed/text/"  # make sure you have data > processed folder at the root of the project
    result_file += f"{file_name}.txt"
    with open(result_file, "w") as output_file:
        output_file.write(doc_text)
    output_file.close


    ## Extract Images
    # Check pdf images
    check_for_image(path, file_name)
    # Sometimes, images are not detected(i.e svg)..so check for drawings
    check_for_drawings(path, file_name)

        

def run():

    parser = argparse.ArgumentParser()
    parser.add_argument("directory", help="pass directory path where your .pdfs are located", type=str, default="data/")
    args = parser.parse_args()

    directory = args.directory
    logger.info(f"List directory {directory}")

    for filename in os.listdir(directory):
        if filename.endswith(".pdf"):
            logger.info(f"Starting extraction for filename - {filename}")
            path = os.path.join(directory, filename)

            pdf_process(path)
            logger.info(f"Finish extraction for filename - {filename}")
