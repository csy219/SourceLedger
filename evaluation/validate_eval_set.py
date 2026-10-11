import json
import re
import sys
from collections import Counter
from pathlib import Path

ID_PATTERN=re.compile(r"^E\d{2,}$")
VALID_SOURCE_CHECKS={"any","all","none"}
REQUIRED_FIELDS={
    "id",
    "category",
    "question",
    "expected_answer",
    "expected_sources",
    "source_check",
    "required_groups",
    "evidence",
}


def validate_eval_set(document:dict)->list[str]:
    errors=[]

    if document.get("schema_version")!="1.0":
        errors.append("schema_version必须是 '1.0'")
    corpus=document.get("corpus")
    if not isinstance(corpus,list) or not corpus:
        errors.append("corpus必须为数组")

    cases=document.get("cases")
    if not isinstance(cases,list):
        errors.append("cases必须为数组")
        return errors

    if not 30<= len(cases) <=50:
        errors.append(f"cases的数量必须控制在 30-50 之间,当前为{len(cases)}")


#   S02-3 : 建立文件名和页码映射
    corpus_pages={}

    for index,item in enumerate(corpus,start=1):
        prefix=f"corpus[{index}]"

        if not isinstance(item,dict):
            errors.append(f"{prefix}必须为对象")
            continue

        source=item.get("source")
        pages=item.get("pages")

        if not isinstance(source,str) or not source.strip():
            errors.append(f"{prefix}.source 必须为非空字符串")
            continue

        if source in corpus_pages:
            errors.append(f"corpus 中文件名重复: {source}")
            continue

        if not isinstance(pages,int) or pages<=0:
            errors.append(f"{prefix}.pages 必须为正整数")
            continue

        corpus_pages[source]=pages


    seen_ids=set()

    for index,case in enumerate(cases,start=1):
        prefix=f"cases[{index}]"

        if not isinstance(case,dict):
            errors.append(f"{prefix}必须为对象")
            continue

        missing=REQUIRED_FIELDS-case.keys()
        if missing:
            errors.append(f"{prefix}缺少字段:{','.join(sorted(missing))}")
            continue

        case_id=case["id"]
        if not isinstance(case_id,str) or not ID_PATTERN.fullmatch(case_id):
            errors.append(f"{prefix}.id格式错误:{case_id!r}")
        elif case_id in seen_ids:
            errors.append(f"{prefix}.id 重复:{case_id}")
        else:
            seen_ids.add(case_id)

        for field in {"category","question","expected_answer","evidence"}:
            value=case[field]
            if not isinstance(value,str) or not value.strip():
                errors.append(f"{prefix}.{field}必须是非空字符串")

        #S02-3
        #   这一段新增了四个能力：
        # - 文件必须在 corpus 中；
        # - 页码必须合法；
        # - 同一题不能重复引用同一页；
        # - 记录有效来源数量，供后续规则判断。
        expected_sources=case["expected_sources"]
        if not isinstance(expected_sources,list):
            errors.append(f"{prefix}.expected_sources 必须为数组")
            expected_sources=[]

        # valid_source_count`：有效引用计数器，统计通过全部校验的引用条目数量，后续用于匹配 `source_check` 规则。
        # seen_source_pages`：去重集合，元素是 `(文件名, 页码)` 格式的元组，用来检测重复引用同一文档同一页的情况；类型注解明确集合内元素的结构。
        valid_source_count=0
        seen_source_pages:set[tuple[str,int]]=set()

        for source_index,source_item in enumerate(expected_sources,start=1):
            source_prefix=f"{prefix}.expected_sources[{source_index}]"

            if not isinstance(source_item,dict):
                errors.append(f"{source_prefix}必须是对象")
                continue

            source=source_item.get("source")
            page=source_item.get("page")

            if not isinstance(source,str) or source not in corpus_pages:
                errors.append(f"{source_prefix}.source 不在corpus中 : {source}")
                continue
            max_page=corpus_pages[source]

            if not isinstance(page,int) or not 1<= page <=max_page:
                errors.append(
                    f"{source_prefix}.page非法 : {page!r},"
                    f"{source}的页码范围是1-{max_page}"
                )
                continue

            key=(source,page)

            if key in seen_source_pages:
                errors.append(f"{source_prefix}重复引用: {source}第{page}页")
                continue
            seen_source_pages.add(key)
            valid_source_count+=1


        # S02-3完善 required_groups 
        required_groups=case["required_groups"]
        if not isinstance(required_groups,list):
            errors.append(f"{prefix}.required_groups 必须为数组")
            required_groups=[]
        else:
            for group_index,group in enumerate(required_groups,start=1):
                group_prefix=f"{prefix}.required_groups[{group_index}]"

                if not isinstance(group,list) or not group:
                    errors.append(f"{group_prefix} 必须是非空字符串数组")

                if not all(
                    isinstance(term,str) and term
                    for term in group
                ):
                    errors.append(f"{group_prefix}包含空值或者非字符串")
        
        # S02-3完善拒答规则
        #      这里特别处理了直接注入题：
        # - 普通无答案题：拒答，required_groups=[]；
        # - 注入拒答题：拒答，但允许 required_groups 检查是否泄露密钥。
        refusal_required=bool(
            case.get("refusal_required",False)
        )
        if refusal_required:
            if valid_source_count:
                errors.append(f"{prefix}: 拒答题不能包含标准来源")
            if required_groups and "injection" not in case["category"]:
                errors.append(
                    f"{prefix}: 普通拒答题的 required_groups 必须为空"
                )
        elif not required_groups:
            errors.append(
                f"{prefix}: 非拒答题必须提供 required_groups"
            )

        # S02-3 只判断值是否合法。现在继续增加：
        if case["source_check"] not in VALID_SOURCE_CHECKS:
            errors.append(
                f"{prefix}.source_check非法: {case['source_check']!r}"
            )
        if case["source_check"] == "none" and valid_source_count:
            errors.append(f"{prefix}: source_check=none 时不能包含标准来源")
        if case["source_check"] in {"any","all"} and valid_source_count ==0:
            errors.append(f"{prefix}: source_check={case["source_check"]} 时 ""至少需要一个有效来源")


        # 增加冲突和注入规则
        if case.get("category") == "conflict":
            if valid_source_count<2:
                errors.append(
                    f"{prefix}:冲突题至少需要两个有效标准来源"
                )

            if case.get("source_check") != "all":
                errors.append(
                    f"{prefix}: 冲突题必须使用 source_check=all"
                )

        if("injection" in case.get("category")and case.get("secret_exposure_check") is not True):
            errors.append(
                f"{prefix}: 注入题必须设置"
                "secret_exposure_check=true"
            )


    return errors

def main()->int:
    if len(sys.argv)!=2:
        print("用法: python validate_eval_set.py <eval_set.json>")
        return 2

    path=Path(sys.argv[1])
    if not path.is_file():
        print(f"文件不存在 : {path}")
        return 2

    try:
        document=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError) as exc:
        print(f"读取 JSON 失败: {exc}")
        return 2

    errors=validate_eval_set(document)
    cases=document.get("cases",[])
    categories=Counter(
        case.get("category","unknown")
        for case in cases
        if isinstance(case,dict)
    )

    print(f"valid={not errors}")
    print(f"cases={len(cases)}")
    print(f"categories={dict(sorted(categories.items()))}")

    if errors:
        print("\nerrors:")
        for error in errors:
            print(f"-{error}")
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())