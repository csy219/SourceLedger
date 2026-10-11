import re
from typing import Any

HEADING_PATTERNS = [
    re.compile(r"^第[一二三四五六七八九十百零〇两\d]+章\s+"),
    re.compile(r"^第\s*\d+\s*页\s*[｜|]"),
]

SENTENCE_END_PATTERN = re.compile(r"[。！？!?]$")

# is_heading：判断一行是不是标题
def is_heading(line:str)->bool:
    stripped=line.strip()
    return any(
        pattern.match(stripped)
        for pattern in HEADING_PATTERNS
    )

# is_bullet：判断一行是不是无序列表项
def is_bullet(line:str)->bool:
    return line.strip().startswith("- ")

# 长块切分
def split_long_text(
        text:str,
        max_size:int,
        overlap:int,
)->list[str]:
    if len(text)<=max_size:
        return [text]

    step=max(1,max_size-overlap)
    return[
        text[start:start+max_size]
        for start in range(0,len(text),step)
        if text[start:start+max_size].strip()
    ]

def chunk_structure_aware(
        page_text:str,
        source:str,
        page_number:int,
        max_size:int=400,
        overlap:int=400
)->list[dict[str,Any]]:
    blocks:list[dict[str,str]]=[]
    current_lines:list[str]=[]
    current_type="paragraph"
    heading=""


    # 内部工具函数 `flush_current`
    def flush_current()->None:
        nonlocal current_lines

        content="".join(current_lines).strip()
        current_lines=[]

        if not content:
            return

        blocks.append(
            {
                "content":content,
                "block_type":current_type,
                "heading":heading
            }
        )


    # 第一阶段：逐行遍历，构建语义块 `blocks`
    for raw_line in page_text.splitlines():
        line=raw_line.strip()

        if not line:
            flush_current()
            continue

        if is_heading(line):
            flush_current()
            heading=line
            current_type="paragraph"
            continue

        if is_bullet(line):
            flush_current()
            blocks.append(
                {
                    "content":line,
                    "block_type":"list_item",
                    "heading":heading
                }
            )
            current_type="paragraph"
            continue

        current_lines.append(line)

        if SENTENCE_END_PATTERN.search(line):
            flush_current()
    flush_current()

    # 第二阶段：生成最终分块 `chunks`
    chunks:list[dict[str,Any]]=[]

    for block_index,block in enumerate(blocks):
        content=block["content"]
        block_heading=block["heading"]

        text=(
            f"{block_heading}\n{content}"
            if block_heading
            else content
        )

        pieces=split_long_text(
            text=text,
            max_size=max_size,
            overlap=overlap
        )

        for piece in pieces:
            chunks.append(
                {
                    "text":piece,
                    "metadata":{
                        "source":source,
                        "page":page_number,
                        "heading":block_heading,
                        "block_type":block["block_type"],
                        "block_index":block_index,
                        "chunk_index":len(chunks)
                    },
                }
            )
    return chunks
