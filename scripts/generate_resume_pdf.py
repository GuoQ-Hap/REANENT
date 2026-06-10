from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "output" / "pdf"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PHOTO = ROOT / "tmp" / "pdfs" / "extracted_images" / "img-000.png"
OUTPUT = OUT_DIR / "彭梅萍_AI应用工程师_优化版.pdf"

FONT_REGULAR = r"C:\Windows\Fonts\Deng.ttf"
FONT_BOLD = r"C:\Windows\Fonts\Dengb.ttf"
pdfmetrics.registerFont(TTFont("CN", FONT_REGULAR))
pdfmetrics.registerFont(TTFont("CN-Bold", FONT_BOLD))


styles = getSampleStyleSheet()
BASE = dict(fontName="CN", fontSize=8.4, leading=12.4, textColor=colors.HexColor("#1f2933"))

styles.add(
    ParagraphStyle(
        "NameCN",
        fontName="CN-Bold",
        fontSize=22,
        leading=26,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#111827"),
        spaceAfter=4,
        wordWrap="CJK",
    )
)
styles.add(
    ParagraphStyle(
        "Target",
        fontName="CN",
        fontSize=9.5,
        leading=12,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#374151"),
        wordWrap="CJK",
    )
)
styles.add(
    ParagraphStyle(
        "Contact",
        fontName="CN",
        fontSize=8.2,
        leading=10,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#4b5563"),
        wordWrap="CJK",
    )
)
styles.add(
    ParagraphStyle(
        "Section",
        fontName="CN-Bold",
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#0f766e"),
        spaceBefore=5,
        spaceAfter=3,
        wordWrap="CJK",
    )
)
styles.add(ParagraphStyle("Body", **BASE, wordWrap="CJK", alignment=TA_LEFT))
styles.add(
    ParagraphStyle(
        "Small",
        fontName="CN",
        fontSize=7.6,
        leading=10.5,
        textColor=colors.HexColor("#374151"),
        wordWrap="CJK",
    )
)
styles.add(
    ParagraphStyle(
        "Role",
        fontName="CN-Bold",
        fontSize=9.2,
        leading=12,
        textColor=colors.HexColor("#111827"),
        wordWrap="CJK",
    )
)
styles.add(
    ParagraphStyle(
        "Right",
        fontName="CN",
        fontSize=8.2,
        leading=10.5,
        alignment=TA_RIGHT,
        textColor=colors.HexColor("#4b5563"),
        wordWrap="CJK",
    )
)
styles.add(
    ParagraphStyle(
        "ResumeBullet",
        fontName="CN",
        fontSize=8.15,
        leading=11.8,
        firstLineIndent=-9,
        leftIndent=9,
        bulletIndent=0,
        textColor=colors.HexColor("#1f2933"),
        spaceAfter=1.4,
        wordWrap="CJK",
    )
)
styles.add(
    ParagraphStyle(
        "ResumeSubBullet",
        fontName="CN",
        fontSize=7.9,
        leading=11.4,
        firstLineIndent=-8,
        leftIndent=8,
        bulletIndent=0,
        textColor=colors.HexColor("#374151"),
        spaceAfter=1.2,
        wordWrap="CJK",
    )
)


def p(text, style="Body"):
    return Paragraph(text, styles[style])


def bullet(text, style="ResumeBullet"):
    return Paragraph(text, styles[style], bulletText="•")


def section(title):
    return [
        p(title, "Section"),
        HRFlowable(width="100%", thickness=0.7, color=colors.HexColor("#0f766e"), spaceAfter=4),
    ]


def chips(items, cols=3):
    rows = []
    row = []
    for item in items:
        row.append(p(item, "Small"))
        if len(row) == cols:
            rows.append(row)
            row = []
    if row:
        row += [""] * (cols - len(row))
        rows.append(row)
    table = Table(rows, colWidths=[(176 / cols) * mm] * cols, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "CN"),
                ("BOX", (0, 0), (-1, -1), 0, colors.white),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f3f4f6")),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("INNERGRID", (0, 0), (-1, -1), 1.5, colors.white),
            ]
        )
    )
    return table


def project_header(name, role, stack):
    t = Table(
        [[p(name, "Role"), p(role, "Right")], [p(f"<font color='#4b5563'>技术栈：</font>{stack}", "Small"), ""]],
        colWidths=[132 * mm, 44 * mm],
    )
    t.setStyle(
        TableStyle(
            [
                ("SPAN", (0, 1), (1, 1)),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ]
        )
    )
    return t


def header():
    info = [
        p("彭梅萍", "NameCN"),
        p("AI 应用开发工程师 | RAG / Multi-Agent / AI 工作流 / 跨境电商业务智能化", "Target"),
        p("18407966157 | meipingpeng94@gmail.com | 女 | 24 岁 | 现居深圳", "Contact"),
    ]
    if PHOTO.exists():
        img = Image(str(PHOTO), width=24 * mm, height=30 * mm)
        table = Table([[info, img]], colWidths=[143 * mm, 30 * mm])
        table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                    ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ]
            )
        )
        return [table, Spacer(1, 3)]
    return info + [Spacer(1, 3)]


def build():
    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
    )
    story = []
    story.extend(header())

    story.extend(section("个人优势"))
    story.extend(
        [
            bullet("理解跨境电商从选品、Listing 生成、合规审核、利润测算到客服售后的核心链路，能把 AI 能力拆进真实业务流程。"),
            bullet("具备 RAG、多 Agent、Dify 工作流、Prompt 策略、模型调用链路、异步任务与容器化部署的 AI 应用落地经验。"),
            bullet("关注大模型幻觉、知识召回、长任务稳定性、合规边界和人工兜底，能围绕业务闭环设计可上线的 AI 系统。"),
        ]
    )

    story.extend(section("AI 与技术能力"))
    story.append(
        chips(
            [
                "<b>AI 应用开发</b>：LangChain、LangGraph、Dify、Ollama、本地模型部署",
                "<b>Agent 编排</b>：主控 Agent、专项 Agent、任务拆解、工具调用、状态流转",
                "<b>RAG 能力</b>：知识库构建、文档解析分块、Embedding、Milvus、Chroma",
                "<b>检索优化</b>：语义向量、BM25、混合检索、召回优化、上下文注入",
                "<b>Prompt 工程</b>：角色设定、安全边界、投诉闭环、多语言会话、输出约束",
                "<b>模型工程</b>：服务降级、缓存问答、联网搜索、LoRA、Transformer 基础",
                "<b>后端工程</b>：Python、SQL、FastAPI、SQLAlchemy、异步任务、接口设计",
                "<b>数据与部署</b>：MySQL、Redis、MinIO、Docker、Nginx、任务恢复",
            ],
            cols=2,
        )
    )
    story.append(Spacer(1, 4))

    story.extend(section("项目经历"))
    story.append(
        project_header(
            "跨境电商多 AI Agent 智能运营工作台",
            "AI 应用开发工程师",
            "Python, FastAPI, SQLAlchemy, LangChain, LangGraph, Redis, Milvus, MinIO, Ollama, Docker",
        )
    )
    story.extend(
        [
            bullet("深入拆解跨境卖家日常运营链路：选品需要判断市场机会，Listing 需要稳定生成多语言文案，合规需要提前识别侵权/敏感词，利润测算需要结合成本、物流、平台费形成决策依据。"),
            bullet("围绕“运营 Copilot”思路设计多 Agent 工作台，将内容生成、合规检测、利润测算、选品辅助等分散工具收敛到统一后端服务，减少人工在多系统之间反复切换。"),
            bullet("设计主控 Agent + 专项 Agent 架构：主控 Agent 负责理解用户意图、拆解任务和编排流程，文案、合规、利润、选品等 Agent 负责各自业务动作，形成可扩展的 AI 任务协作模式。"),
            bullet("基于 LangGraph 构建合规闭环：生成内容后进入规则/知识库/模型检测，发现风险后将问题反馈重新注入上下文，驱动二次生成，降低文案违规、幻觉和不符合平台规则的风险。"),
            bullet("构建语义向量 + BM25 混合检索 RAG，将平台政策、类目规范、禁限售规则、运营知识等沉淀为可检索知识库，兼顾语义理解和品牌词、类目词等精确匹配。"),
            bullet("针对 AI 长任务耗时不可控的问题，使用 Python 异步编程与 Redis 消息队列实现任务异步化，API 层即时返回，后台服务并发消费，支持任务状态追踪和进度展示。"),
            bullet("设计失败暂存区、递增重试、MySQL 状态持久化与任务恢复机制，避免异常任务阻塞后续流程，并支持 Redis 重启后的任务补录和人工排查。"),
            bullet("利用 LangChain 封装大模型调用链路，设计第三方 API、本地模型、本地缓存、联网搜索等多级降级策略，保障 AI 服务在模型不可用或接口异常时仍可兜底。"),
        ]
    )

    story.append(PageBreak())
    story.extend(header())
    story.extend(section("项目经历"))

    story.append(
        project_header(
            "跨境独立站 AI 智能客服平台",
            "AI 应用开发工程师",
            "Python, FastAPI, Dify, MySQL, Docker, RAG",
        )
    )
    story.extend(
        [
            bullet("理解独立站客服的核心痛点：海外用户时差导致响应不及时，订单/物流类问题重复率高，多语言沟通成本高，售后政策复杂且容易回复不一致。"),
            bullet("基于 Dify 搭建客服 AI 工作流，覆盖意图识别、知识库问答、订单查询、物流追踪、投诉处理、转人工等节点，让 AI 不只是聊天，而是能执行具体客服流程。"),
            bullet("针对大模型容易编造订单状态的问题，将 Dify 工作流与 FastAPI 业务接口打通；识别到订单、物流、售后诉求时直接查询真实结构化数据，再由模型组织自然语言回复。"),
            bullet("围绕退换货、物流延迟、赔付、投诉等高频售后场景设计 Prompt 和流程边界，形成情绪安抚、诉求提取、政策匹配、工单/转人工/补偿建议的闭环。"),
            bullet("在 Dify 知识库中配置语义向量 + BM25 混合检索，将店铺政策、物流条款、售后规则、行业规范等多语言资料沉淀为 RAG 知识库，提升政策类问答稳定性。"),
            bullet("使用 MySQL 存储业务数据并通过 Docker 部署服务，使 AI 客服能承接常见咨询，复杂问题再交给人工处理，降低客服培训和重复答复成本。"),
        ]
    )

    story.extend(section("工作经历"))
    exp_table = Table(
        [
            [
                p("2023.07 - 2026.02", "Body"),
                p("杭州汇聚智美网络科技有限公司", "Body"),
                p("AI 应用开发工程师", "Right"),
            ]
        ],
        colWidths=[43 * mm, 86 * mm, 47 * mm],
    )
    exp_table.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(exp_table)
    story.extend(
        [
            bullet("负责跨境电商 AI 应用落地，参与运营、客服、合规等场景的业务流程拆解、AI 方案设计、后端开发、知识库配置、部署与问题排查。"),
            bullet("重点建设多 Agent 运营工作台、Dify 智能客服、RAG 知识库、合规检测、异步任务调度、模型调用降级和文件流转链路。"),
        ]
    )

    story.extend(section("教育经历"))
    edu_table = Table(
        [[p("2018.09 - 2023.06", "Body"), p("吉安职业技术学院", "Body"), p("大专/本科", "Right")]],
        colWidths=[43 * mm, 86 * mm, 47 * mm],
    )
    edu_table.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    story.append(edu_table)

    story.extend(section("自我评价"))
    story.extend(
        [
            bullet("对 AI 应用的理解不止停留在模型调用，更关注业务流程、知识来源、风险边界、人工兜底和上线后的稳定性。"),
            bullet("能主动和业务、前端、测试沟通，把模糊需求拆成可执行的工作流、接口、知识库和异常处理方案。"),
            bullet("持续关注 MCP、A2A、多 Agent、RAG 评估、模型微调和 AI 工作流编排等方向，愿意在业务中快速验证新方案。"),
        ]
    )

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("CN", 7)
        canvas.setFillColor(colors.HexColor("#6b7280"))
        canvas.drawRightString(195 * mm, 8 * mm, f"{doc.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print(OUTPUT)


if __name__ == "__main__":
    build()
