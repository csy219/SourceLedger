import sys
from pathlib import Path

PROJECT_ROOT=Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0,str(PROJECT_ROOT))

from pdf_rag import load_pdf_pages

TARGETS = {
    "AI应用开发知识手册.pdf": [2, 3, 9],
    "Agent平台需求说明.pdf": [2],
}

def main()->int:
    corpus_dir=Path(__file__).parent / "corpus"

    for source,target_pages in TARGETS.items():
        pdf_path=corpus_dir / source

        if not pdf_path.is_file():
            print(f"文件不存在: {pdf_path}")
            continue

        page_map={
            page_number:page_text
            for page_number,page_text in load_pdf_pages(pdf_path)
        }

        for page_number in target_pages:
            print("\n" + "=" * 80)
            print(f"{source} | 第 {page_number} 页")
            print("=" * 80)

            page_text=page_map.get(page_number,"")

            if not page_text:
                print("没有提取到文字")
                continue

            for line_number,line in enumerate(page_text.splitlines(),start=1):
                print(f"{line_number:03d}:{line}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())


