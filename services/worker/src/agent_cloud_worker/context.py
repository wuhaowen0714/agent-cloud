from __future__ import annotations

from agent_cloud_common import ContextDocument, MemoryItem, SkillRef


def _escape_xml(s: str) -> str:
    # & 必须最先替换,否则会二次转义后续插入的实体;防止技能元数据破坏 <skill> XML 结构。
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _render_docs(documents: list[ContextDocument]) -> list[str]:
    # 用户级在前,agent 级在后;各自保持输入顺序
    ordered = [d for d in documents if d.scope == "user"] + [
        d for d in documents if d.scope != "user"
    ]
    return [f"# {d.type} ({d.scope})\n{d.content}" for d in ordered]


def _render_memory(memory: list[MemoryItem]) -> list[str]:
    # 分层渲染:user 块跨该用户全部 agent 共享(里面的"我"不是这个 agent),agent 块才是
    # 它专属。标题措辞与 remember 工具的 scope 语义一一对应——模型读时不会认错主语,
    # 写时也学得到该往哪层记。块内容本身已是 markdown bullets,原样输出
    # (旧版逐条加 "- (scope)" 前缀,对多行块是畸形嵌套)。
    user_blocks = [m.content for m in memory if m.scope == "user" and m.content.strip()]
    agent_blocks = [m.content for m in memory if m.scope != "user" and m.content.strip()]
    out = []
    if user_blocks:
        out.append(
            "# Memory — about the user (shared across all of their agents)\n"
            + "\n".join(user_blocks)
        )
    if agent_blocks:
        out.append(
            "# Memory — this agent (private to you: your given name/persona, conventions, "
            "domain notes)\n" + "\n".join(agent_blocks)
        )
    return out


def _render_skills(skills: list[SkillRef]) -> list[str]:
    if not skills:
        return []
    lines = [
        "The following skills provide specialized instructions for specific tasks.",
        "Read a skill's file (location) when the task matches its description.",
        "<available_skills>",
    ]
    for s in skills:
        lines.append(
            f"  <skill><name>{_escape_xml(s.name)}</name>"
            f"<description>{_escape_xml(s.description)}</description>"
            f"<location>{_escape_xml(s.location)}</location></skill>"
        )
    lines.append("</available_skills>")
    # 适配本沙箱:skill 的指令多按别的环境写,这里纠两处最常踩的偏差——
    # ① 随附脚本/资源在 skill 目录(.skills/<name>/)下,而 bash 的 CWD 是工作区根,SKILL.md
    #    里的相对路径(scripts/x.py)必须加前缀,否则每次先失败再 find(实测)。
    # ② 文档工具链已预装在镜像里,SKILL.md 常叫人 npm/pip install,照做会白装一遍(docx 那份
    #    要现下 22 包 ~2min;require 走 NODE_PATH 本就命中预装的那份)。
    lines.append(
        "Adapting a skill to THIS sandbox (its instructions were written for a different "
        "environment — apply two corrections):"
    )
    lines.append(
        "- A skill's bundled files live under its own directory (the folder of its "
        "location, e.g. `.skills/<name>/`). Your shell starts in the working directory, "
        "NOT inside that folder, so when a SKILL.md cites a bundled file by relative path "
        "(e.g. `scripts/office/pack.py`), run or read it with the full prefix "
        "`.skills/<name>/scripts/office/pack.py`. Documents you create stay in the working "
        "directory."
    )
    lines.append(
        "- The document toolchain is already installed here — do NOT `npm install` or `pip "
        "install` these even if a SKILL.md says to (you would only re-download a second copy "
        "and waste minutes); use them directly: Node `docx` and `pptxgenjs` (via "
        "`require(...)`), Python `docx`/`pptx`/`openpyxl`/`pandas`/`markitdown`/`pdfplumber` "
        "(via `import`), and CLI `soffice`/`libreoffice`, `pandoc`, `pdftoppm`, `gcc`."
    )
    return ["\n".join(lines)]


# 基础系统提示词:无论是否有用户级文档/记忆/技能都先注入,给模型最起码的环境认知
# (沙箱工作目录 + 相对路径约定)。否则空 system 会让模型幻觉 /workspace 之类不存在的
# 绝对路径(实测 DeepSeek 会 `cd /workspace/<id>` 然后失败)。
BASE_SYSTEM_PROMPT = """\
You are an autonomous AI agent running inside an isolated sandbox.

Working directory and files:
- You have a persistent working directory that is shared across all of your sessions — files \
you create remain available in later sessions. The file tools (read_file, write_file) and the \
bash tool all operate inside this working directory.
- Always use relative paths (e.g. `notes.txt`, `src/app.py`, `python3 script.py`). Do not use \
absolute paths and do not assume any specific location such as `/workspace`, `/home`, or `/tmp` \
— they may not exist.
- Each bash call runs in a fresh shell that starts in the working directory. A `cd` affects only \
that single command and does not carry over to the next call, so run files directly (e.g. \
`python3 script.py`) rather than `cd`-ing first.

Installing software and network:
- To add libraries or tools, install them with `pip install --user` (Python) or `npm \
install -g` (Node). These land in your persistent working directory, so they stay available \
in later sessions.
- Outbound internet works: you can fetch URLs and install from PyPI/npm. `curl`, `wget`, \
`git`, and `jq` are preinstalled and ready to use directly. `git` is preconfigured (safe \
directory + a default identity) so it works in your working directory out of the box. You can \
also make HTTP requests from Python (the stdlib `urllib`, or `pip install --user requests` \
first).
- There is NO system package manager: `apt`, `apt-get`, and `sudo` will fail because the \
sandbox runs with Linux capabilities dropped, and system packages would not persist anyway. \
Do not try to install OS packages — use a pip or npm package, or a Python stdlib equivalent, \
instead."""


# 中国大陆网络区域提示(network_region "cn"/"cn-*" 时注入)。模型默认按训练习惯首选 google/
# wikipedia/duckduckgo 搜索,但境内服务器连不通——一路超时/验证码白费回合(实测:agent 反复
# curl google.com / en.wikipedia.org 全 Forbidden)。明确告知所在网络 + 可达入口 + "失败即换"。
# 搜索段按是否有 web_search 工具二选一:有则指向工具(否则 system 指令会和工具描述打架、把模型
# 推回 curl);没有(未配搜索 key)才回退 cn.bing.com 直连(阿里云大陆实测纯 curl 可拿结果)。
_CN_NETWORK_HEADER = "Network location (IMPORTANT — this changes which sites you can reach):"

_CN_UNREACHABLE = (
    "- This sandbox runs on a server in mainland China. Many international sites are unreachable "
    "from here: they time out or hang. Do NOT use these — attempts will fail and waste your "
    "turns: Google (and Google Search), Wikipedia / Wikimedia, DuckDuckGo, YouTube, X / Twitter, "
    "Facebook, Instagram, Reddit, Medium, Hugging Face."
)

# 有 web_search 工具时:搜索段指向工具(与工具描述一致,不把模型推回 curl)。
_CN_SEARCH_WITH_TOOL = (
    "- To search the web, use the web_search tool — it returns ranked results (title, URL, "
    "snippet) from a backend reachable from here. Prefer it over fetching a search engine "
    "yourself. You may then open a result's URL with curl to read the full page. For knowledge "
    "you would normally get from Wikipedia, search with web_search and read a reachable source."
)

# 没有 web_search 工具(未配搜索 key)时:回退 cn.bing.com 直连。
_CN_SEARCH_WITH_CURL = (
    "- To search the web, use an engine reachable from here. Best for the command line: Bing "
    'China — `curl -sL -A "Mozilla/5.0" "https://cn.bing.com/search?q=YOUR+QUERY"` returns real '
    "results directly. Sogou (https://www.sogou.com/web?query=...) also works. Avoid Baidu's "
    "HTML search: it returns a CAPTCHA to scripted clients. For knowledge you would normally get "
    "from Wikipedia, search via Bing and read a reachable source."
)

_CN_NETWORK_TAIL = (
    '- When fetching pages with curl/wget, send a browser User-Agent (`-A "Mozilla/5.0"`) and '
    "follow redirects (`-L`); otherwise many sites return a redirect or a bot-check page.\n"
    "- Most developer resources stay reachable (GitHub, Stack Overflow, PyPI, npm, and most "
    "official language/framework docs) — use them normally. GitHub can be intermittently slow "
    "from here: if a request times out, retry once before switching. If a site is consistently "
    "refused or hangs, assume it is blocked from mainland China and switch to a reachable "
    "alternative instead of retrying the same URL."
)


def _render_network(network_region: str, web_search_available: bool = False) -> list[str]:
    # 仅在已知"受限"区域注入站点可达性提示;其它区域(海外/无限制)留空,保持 prompt 干净。
    # "cn" 或阿里云 region id("cn-hangzhou" 等,运维易这么填)都视为中国大陆。搜索段按是否有
    # web_search 工具二选一,避免 system prompt 与工具描述冲突。
    region = network_region.strip().lower()
    if region != "cn" and not region.startswith("cn-"):
        return []
    search = _CN_SEARCH_WITH_TOOL if web_search_available else _CN_SEARCH_WITH_CURL
    return ["\n".join([_CN_NETWORK_HEADER, _CN_UNREACHABLE, search, _CN_NETWORK_TAIL])]


def _render_date(current_date: str) -> list[str]:
    # 注入"今天日期"(worker 每回合现算,故动态)。模型不知真实日期,查"今天/今年/最近"的时事
    # 会瞎猜;给它当天日期 + 星期作锚。空串(未提供)则不注入,保持 prompt 干净。
    if not current_date.strip():
        return []
    return [
        f"Today's date is {current_date}. When the user refers to relative dates — "
        '"today", "yesterday", "this week", "this month", "this year", "recently" — '
        "interpret them relative to this date. Your training knowledge may be out of date, so "
        "for recent or current events, search for up-to-date information rather than relying on "
        "memory."
    ]


def _render_summary(history_summary: str) -> list[str]:
    # 压缩后此前历史折叠成的摘要。放在末尾(贴近随后的消息历史),并标明这是浓缩的早期对话,
    # 而非用户配置 —— 让模型把它当作上下文延续而不是新指令。
    if not history_summary.strip():
        return []
    return [
        "# 此前对话摘要\n"
        "以下是本次会话早期内容的浓缩摘要(为节省上下文已折叠原始消息)。"
        "把它当作已发生的对话背景,继续后续回合:\n\n"
        f"{history_summary}"
    ]


def build_system_prompt(
    *,
    documents: list[ContextDocument],
    memory: list[MemoryItem],
    skills: list[SkillRef],
    history_summary: str = "",
    network_region: str = "",
    web_search_available: bool = False,
    current_date: str = "",
) -> str:
    """基础环境提示词 + 当前日期 + 网络区域提示 + 配置文档(用户级在前)+ 记忆 + 技能元数据 +
    此前对话摘要,拼成分层 system 文本(spec §5.3 / §6)。"""
    sections = [
        BASE_SYSTEM_PROMPT,
        *_render_date(current_date),
        *_render_network(network_region, web_search_available),
        *_render_docs(documents),
        *_render_memory(memory),
        *_render_skills(skills),
        *_render_summary(history_summary),
    ]
    return "\n\n".join(sections)
