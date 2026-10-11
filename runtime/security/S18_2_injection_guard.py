# 这是一个轻量级**提示词注入检测与敏感信息防护工具**，基于正则表达式识别常见的 Prompt 注入攻击类型，同时提供敏感信息脱敏、输出安全校验能力，属于大模型输入输出安全的基础防护组件
import re
from dataclasses import dataclass

# 2. InjectionDetection 检测结果数据类
# 这是一个**只读数据载体类**，用于封装注入检测的结果，作为`detect`方法的返回值。

# - `@dataclass(frozen=True)`：
#   - `dataclass`装饰器将该类标记为数据类，自动生成构造方法等基础方法；
#   - `frozen=True`表示实例**冻结不可变**，创建后无法修改属性值，保证检测结果不可篡改，适合作为只读返回结构。
# - `detected: bool`：布尔属性，标记是否检测到注入行为，`True`为检测到，`False`为未检测到。
# - `category: str`：字符串属性，标记注入攻击的类别（如`ignore_rules`），未检测到时为空字符串。
# - `matched_pattern: str`：字符串属性，存储实际匹配到的文本片段，未检测到时为空字符串。
@dataclass(frozen=True)
class InjectionDetection:
    detected:bool
    category:str
    matched_pattern:str


# 3. DEFAULT_INJECTION_PATTERNS 默认注入规则库
DEFAULT_INJECTION_PATTERNS = [
    # 规则 1：ignore_rules（忽略系统规则类注入）
    (
        "ignore_rules",
        re.compile(
            r"(忽略|无视|绕过).{0,12}"
            r"(之前|以上|所有|系统).{0,8}"
            r"(规则|指令|限制)"
        ),
    ),
    # 规则 2：reveal_secret（窃取密钥类注入）
    (
        "reveal_secret",
        re.compile(
            r"(输出|泄露|显示|告诉我).{0,16}"
            r"(api[_ -]?key|密钥|secret|token|密码)",
            re.IGNORECASE,
        ),
    ),
    # 规则 3：reveal_prompt（窃取系统提示类注入）
    (
        "reveal_prompt",
        re.compile(
            r"(输出|泄露|显示|复述).{0,12}"
            r"(系统提示词|system prompt|隐藏指令)",
            re.IGNORECASE,
        ),
    ),
    # 规则 4：execute_command（执行命令类注入）
    (
        "execute_command",
        re.compile(
            r"(执行|运行).{0,12}"
            r"(shell|命令|脚本|rm\s+-rf)",
            re.IGNORECASE,
        ),
    ),
    # 规则 5：read_secret_file（读取敏感文件类注入）
    (
        "read_secret_file",
        re.compile(
            r"(读取|打开|输出).{0,16}"
            r"\.env",
            re.IGNORECASE,
        ),
    ),
]

# 4. InjectionGuard 核心防护类
class InjectionGuard:
    # - 作用：初始化防护实例，配置检测用的正则模式列表。
    # - 参数：
    # - `patterns`：可选参数，类型为「(类别名，正则对象) 元组组成的列表」，默认值为`None`。
    #     - 传入自定义模式时，使用传入的规则；
    #     - 不传时，使用全局默认规则库`DEFAULT_INJECTION_PATTERNS`。
    # - `self.patterns`：实例属性，存储实际生效的检测模式列表，供`detect`方法遍历使用。
    # - 设计特点：兼顾易用性（默认开箱即用）和扩展性（支持自定义规则）。
    def __init__(
        self,
        patterns:list[tuple[str,re.Pattern[str]]] | None=None,
    )->None:
        self.patterns=(
            patterns
            if patterns is not None
            else DEFAULT_INJECTION_PATTERNS
        )

    # 4.2 detect 注入检测方法
    # - 作用：核心检测方法，输入用户文本，返回检测结果对象。
    # - 参数：
    #   - `text: str`：待检测的用户输入文本。
    # - 内部变量与逻辑：
    #   1. `for category, pattern in self.patterns`：遍历实例的规则列表，依次取出每个规则的类别名和正则对象。
    #   2. `match = pattern.search(text)`：调用正则对象的`search`方法，**在全文任意位置搜索第一个匹配项**；找到返回`Match`对象，没找到返回`None`。
    #      - 这里用`search`而非`match`（只匹配开头），因为注入话术可能出现在文本的任意位置。
    #   3. `if match:`：匹配成功时：
    #      - `match.group(0)`：获取匹配到的完整文本片段（第 0 组代表整个正则匹配的内容）；
    #      - 立即返回`detected=True`的结果对象，包含对应类别和匹配文本。
    #      - 特点：**短路匹配**，找到第一个命中规则就返回，不再检查后续规则，提升检测效率。
    #   4. 遍历完所有规则都未匹配：返回`detected=False`的结果对象，类别和匹配文本为空
    def detect(
        self,
        text:str,
    )->InjectionDetection:
        for category,pattern in self.patterns:
            match=pattern.search(text)
            if match:
                return InjectionDetection(
                    detected=True,
                    category=category,
                    matched_pattern=match.group(0)
                )
        return InjectionDetection(
            detected=False,
            category="",
            matched_pattern="",
        )

    # 4.3 sanitize 敏感信息脱敏方法
    # - 作用：将文本中的已知敏感内容替换为占位符`[REDACTED]`，防止敏感信息泄露。
    # - 参数：
    # - `text: str`：待脱敏的原始文本；
    # - `secrets: tuple[str, ...] = ()`：可变长度字符串元组，存储需要脱敏的敏感内容（如密钥、内部信息），默认是空元组。
    # - 内部变量与逻辑：
    # - `sanitized = text`：基于原始文本创建副本，不修改原字符串；
    # - 遍历每个敏感词，非空时执行字符串替换，将所有出现的敏感词替换为`[REDACTED]`；
    # - 返回值：脱敏后的字符串。
    def sanitize(
        self,
        text:str,
        secrets:tuple[str,...]=()
    )->str:
        sanitized=text
        for secret in secrets:
            if secret:
                sanitized=sanitized.replace(
                    secret,
                    "[REDACTED]",
                )
        return sanitized

    # 4.4 assert_no_secrets 输出安全校验方法
    # - 作用：断言校验文本中不包含敏感信息，若包含则抛出异常，用于模型输出前的最终安全校验。
    # - 参数：
    # - `text: str`：待校验的输出文本；
    # - `secrets: tuple[str, ...]`：敏感信息元组，为必传参数。
    # - 内部逻辑与安全细节：
    # - 遍历每个敏感词，判断非空且存在于文本中；
    # - 若命中则抛出`AssertionError`；
    # - 异常信息只显示敏感词的**前 4 位 +***`，避免异常信息本身泄露完整敏感内容，是安全设计的关键细节。
    # - 返回值：无返回值，校验通过则正常执行，不通过则抛出异常。
    def assert_no_secrets(
        self,
        text:str,
        secrets:tuple[str,...],
    )->None:
        for secret in secrets:
            if secret and secret in text:
                raise AssertionError(
                "输出泄露敏感信息: "
                f"{secret[:4]}***"
            )


### 三、核心总结

# 1. **正则用法核心价值**：通过预编译、容错量词、多选分支、大小写不敏感等特性，实现了高性能、高容错的已知注入模式匹配，是规则型防护的典型实现。
# 2. **InjectionGuard 类设计定位**：提供「输入检测 - 输出脱敏 - 最终校验」三层基础防护，
# 实现简单、性能开销低、可自定义规则；但仅能匹配已知模式，对语义变种、模糊化注入的检测能力有限，属于大模型安全的基础前置防护方案。

    
