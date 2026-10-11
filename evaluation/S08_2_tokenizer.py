import re

# 匹配连续中文字符（Unicode 中文基本区
CHINESE_PATTERN=re.compile(r"[\u4e00-\u9fff]+")
# 匹配标识符：字母/下划线开头，后续允许字母、数字、_ . -
IDENTIFIER_PATTERN=re.compile(r"[a-zA-Z_][a-zA-Z0-9_.-]*")
# 匹配日期格式：yyyy-MM-dd
DATE_PATTERN=re.compile(r"\d{4}-\d{2}-\d{2}")
# 匹配整数、小数和百分比
NUMBER_PATTERN=re.compile(r"\d+(?:\.\d+)?%?")
# 标识符分隔符：_ . - 连续出现都作为切分点
INDENTIFIER_SPLIT_PATTERN=re.compile(r"[_.-]+")



def tokenize(text:str)->list[str]:
    lower=text.lower()
    tokens:list[str]=[]

    for match in CHINESE_PATTERN.finditer(lower):
        sequence=match.group(0)
        tokens.extend(sequence)
        tokens.extend(
            sequence[index:index+2]
            for index in range(len(sequence)-1)
        )

    for match in IDENTIFIER_PATTERN.finditer(lower):
        identifier=match.group(0)
        tokens.append(identifier)
        tokens.extend(
            part
            for part in INDENTIFIER_SPLIT_PATTERN.split(identifier)
            if part and part !=identifier
        )

    for match in DATE_PATTERN.finditer(lower):
        value=match.group(0)
        tokens.append(value)
        tokens.extend(value.split("-"))

    for match in NUMBER_PATTERN.finditer(lower):
        tokens.append(match.group(0))

    return tokens


# 这是**包装函数（wrapper / 别名函数）**
# `tokenize_query` 只是一个简单转发：接收参数 `text`，直接调用 `tokenize(text)`，然后把 `tokenize` 的返回结果原样返回。
def tokenize_query(text:str)->list[str]:
    return tokenize(text)


def main()->int:
    samples = [
        "审计日志字段 user_id、task_id、tool_name",
        "API Token 每 90 天轮换一次",
        "bge-small-zh-v1.5 和 LangSmith",
        "差旅制度 v2 从 2026-10-01 生效",
        "页面请求 p95 延迟目标为 2 秒",
        "失败率超过 5% 时必须触发告警",
    ]

    for text in samples:
        print(f"\n{text}")
        print(tokenize(text))

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
                      

