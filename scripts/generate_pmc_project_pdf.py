from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "output" / "pdf"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PDF_PATH = OUT_DIR / "PMC库存供应链智能体三期建设立项书.pdf"
REF_IMAGE = Path(
    r"C:\Users\guoqing.yang\AppData\Roaming\LarkShell\sdk_storage\dcefcb46541e0b06cce0c2f2277f7c01\resources\images\img_v3_02123_afda40d6-91cd-41a8-839c-a10126ac747g.jpg"
)

PAGE_W, PAGE_H = landscape(A4)
M = 34

NAVY = colors.HexColor("#0B1F55")
BLUE = colors.HexColor("#0B4AA2")
GREEN = colors.HexColor("#057A3F")
ORANGE = colors.HexColor("#D8580A")
LIGHT_BLUE = colors.HexColor("#EEF5FF")
LIGHT_GREEN = colors.HexColor("#EEF9F2")
LIGHT_ORANGE = colors.HexColor("#FFF4EC")
GRAY = colors.HexColor("#667085")
LIGHT_GRAY = colors.HexColor("#F4F6F8")
TEXT = colors.HexColor("#101828")


def register_fonts() -> None:
    pdfmetrics.registerFont(TTFont("SC", r"C:\Windows\Fonts\msyh.ttc"))
    pdfmetrics.registerFont(TTFont("SC-Bold", r"C:\Windows\Fonts\msyhbd.ttc"))


def wrap_text(text: str, font: str, size: int, max_width: float) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        current = ""
        for ch in para:
            trial = current + ch
            if pdfmetrics.stringWidth(trial, font, size) <= max_width:
                current = trial
            else:
                if current:
                    lines.append(current)
                current = ch
        if current:
            lines.append(current)
    return lines


def draw_footer(c: canvas.Canvas, page_no: int) -> None:
    c.setStrokeColor(colors.HexColor("#D0D5DD"))
    c.line(M, 28, PAGE_W - M, 28)
    c.setFont("SC", 8)
    c.setFillColor(GRAY)
    c.drawString(M, 15, "凌昂科技 PMC库存供应链智能体项目")
    c.drawRightString(PAGE_W - M, 15, f"{page_no}")


def title(c: canvas.Canvas, text: str, subtitle: str = "") -> None:
    c.setFillColor(NAVY)
    c.setFont("SC-Bold", 22)
    c.drawString(M, PAGE_H - 44, text)
    if subtitle:
        c.setFillColor(GRAY)
        c.setFont("SC", 10)
        c.drawString(M, PAGE_H - 62, subtitle)


def pill(c: canvas.Canvas, x: float, y: float, w: float, h: float, label: str, color: colors.Color) -> None:
    c.setFillColor(color)
    c.roundRect(x, y, w, h, 10, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("SC-Bold", 10)
    c.drawCentredString(x + w / 2, y + h / 2 - 4, label)


def bullet_block(c: canvas.Canvas, x: float, y: float, w: float, items: list[str], size: int = 10, leading: int = 16) -> float:
    c.setFont("SC", size)
    c.setFillColor(TEXT)
    yy = y
    for item in items:
        lines = wrap_text(item, "SC", size, w - 14)
        c.setFillColor(NAVY)
        c.circle(x + 4, yy - 4, 2, fill=1, stroke=0)
        c.setFillColor(TEXT)
        for idx, line in enumerate(lines):
            c.drawString(x + 14, yy - idx * leading, line)
        yy -= max(1, len(lines)) * leading + 3
    return yy


def card(c: canvas.Canvas, x: float, y: float, w: float, h: float, heading: str, body: list[str], color: colors.Color, bg: colors.Color) -> None:
    c.setFillColor(bg)
    c.setStrokeColor(color)
    c.roundRect(x, y, w, h, 8, stroke=1, fill=1)
    c.setFillColor(color)
    c.rect(x, y + h - 34, w, 34, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("SC-Bold", 13)
    c.drawString(x + 14, y + h - 23, heading)
    bullet_block(c, x + 14, y + h - 52, w - 28, body, size=9, leading=14)


def page_cover(c: canvas.Canvas) -> None:
    c.setFillColor(colors.white)
    c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
    c.setFillColor(NAVY)
    c.setFont("SC-Bold", 28)
    c.drawCentredString(PAGE_W / 2, PAGE_H - 92, "凌昂科技 PMC库存供应链智能体立项书")
    c.setFont("SC", 16)
    c.drawCentredString(PAGE_W / 2, PAGE_H - 122, "三期建设架构：结构化数据 + 规则计算 + Agent 编排 + 人工确认闭环")

    x0, y0, w, h = 72, 110, PAGE_W - 144, 250
    c.setFillColor(LIGHT_GRAY)
    c.roundRect(x0, y0, w, h, 14, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.roundRect(x0 + 16, y0 + 16, w - 32, h - 32, 12, stroke=0, fill=1)

    cols = [
        ("一期｜库存控制塔 MVP", "看见风险、解释原因、人工确认", BLUE, LIGHT_BLUE),
        ("二期｜计划与预测增强", "复算建议、周度计划、预测偏差", GREEN, LIGHT_GREEN),
        ("三期｜协同自动化与智能体群", "审批流、有限写回、跨系统闭环", ORANGE, LIGHT_ORANGE),
    ]
    cw = (w - 64) / 3
    for i, (h1, h2, col, bg) in enumerate(cols):
        x = x0 + 32 + i * cw
        c.setFillColor(bg)
        c.setStrokeColor(col)
        c.roundRect(x, y0 + 52, cw - 12, 158, 10, stroke=1, fill=1)
        pill(c, x + 16, y0 + 166, cw - 44, 26, h1, col)
        c.setFillColor(TEXT)
        c.setFont("SC", 11)
        for j, line in enumerate(wrap_text(h2, "SC", 11, cw - 46)):
            c.drawCentredString(x + (cw - 12) / 2, y0 + 132 - j * 18, line)

    c.setFillColor(NAVY)
    c.setFont("SC-Bold", 14)
    c.drawCentredString(PAGE_W / 2, 74, "一期看见风险，二期提升计划，三期协同闭环")
    draw_footer(c, 1)


def page_reference(c: canvas.Canvas) -> None:
    title(c, "建设架构参考图", "依据用户提供的三期建设架构图整理")
    if REF_IMAGE.exists():
        img = ImageReader(str(REF_IMAGE))
        iw, ih = img.getSize()
        max_w, max_h = PAGE_W - 70, PAGE_H - 115
        scale = min(max_w / iw, max_h / ih)
        dw, dh = iw * scale, ih * scale
        c.drawImage(img, (PAGE_W - dw) / 2, 48, dw, dh, preserveAspectRatio=True, mask="auto")
    draw_footer(c, 2)


def page_overview(c: canvas.Canvas) -> None:
    title(c, "项目定位与总体方案", "目标：建设可信、可解释、可复算、可闭环的 PMC 库存供应链智能体")
    left = M
    top = PAGE_H - 95
    card(
        c,
        left,
        top - 150,
        250,
        150,
        "项目目标",
        [
            "把库存、预测、采购、发货、物流和规则统一到智能体工作台。",
            "让模型负责理解目标、选择动作和解释原因，让规则工具负责数量、日期和差异计算。",
            "关键动作保留人工确认，先生成建议和草稿，不直接修改正式业务系统。",
        ],
        BLUE,
        LIGHT_BLUE,
    )
    card(
        c,
        left + 270,
        top - 150,
        250,
        150,
        "核心方法",
        [
            "结构化数据：统一 SKU/MSKU/FNSKU/ASIN、仓库、国家、店铺、PMC 口径。",
            "规则计算：库存健康、可覆盖天数、Lead Time、MOQ/箱规、发货和采购复算。",
            "Agent 编排：模型先判断下一步，再调用工具，观察结果后继续决策。",
        ],
        GREEN,
        LIGHT_GREEN,
    )
    card(
        c,
        left + 540,
        top - 150,
        250,
        150,
        "边界原则",
        [
            "不编造库存、销量、在途、采购和金额数据。",
            "不自动创建采购单，不自动改 ERP/WMS/OMS，不自动变更安全库存规则。",
            "所有建议需展示数据来源、计算口径、原因链和人工确认点。",
        ],
        ORANGE,
        LIGHT_ORANGE,
    )

    c.setFillColor(NAVY)
    c.setFont("SC-Bold", 15)
    c.drawString(M, 255, "总体流程")
    steps = [
        "用户问题/业务触发",
        "Agent 判断目标和上下文",
        "查询表池与规则工具",
        "返回观察结果",
        "模型继续决策或输出",
        "人工确认与反馈沉淀",
    ]
    x = M
    y = 185
    for i, s in enumerate(steps):
        col = [BLUE, GREEN, ORANGE, BLUE, GREEN, ORANGE][i]
        pill(c, x, y, 112, 32, s, col)
        if i < len(steps) - 1:
            c.setStrokeColor(NAVY)
            c.line(x + 112, y + 16, x + 133, y + 16)
            c.line(x + 128, y + 21, x + 133, y + 16)
            c.line(x + 128, y + 11, x + 133, y + 16)
        x += 133
    draw_footer(c, 3)


def page_phase1(c: canvas.Canvas) -> None:
    title(c, "一期建设：库存控制塔 MVP", "周期建议：第 1-3 周；目标是先看见风险、解释原因、形成人工确认闭环")
    card(
        c,
        M,
        330,
        252,
        155,
        "数据接入",
        [
            "只读接入领星 ERP、Amazon FBA、国内仓/WMS、采购物流、销售/广告。",
            "主库为 dw_leang，主查询表 ads_lingxing_all_warehouse_new。",
            "补充预测表、销售日报、FBA 库存、国内仓库存。",
        ],
        BLUE,
        LIGHT_BLUE,
    )
    card(
        c,
        M + 270,
        330,
        252,
        155,
        "确定性计算",
        [
            "库存健康计算：断货、冗余、异常。",
            "可售天数和 Lead Time 计算。",
            "库存核对，简版发货/采购复算。",
        ],
        BLUE,
        LIGHT_BLUE,
    )
    card(
        c,
        M + 540,
        330,
        252,
        155,
        "Agent 编排",
        [
            "查数工具、追因工具、风险解释工具。",
            "模型决定查单品还是查组合，程序执行数据库查询和规则计算。",
            "模型拿到 observation 后判断是否继续追问、追因或最终回答。",
        ],
        BLUE,
        LIGHT_BLUE,
    )
    card(
        c,
        M,
        140,
        386,
        145,
        "业务应用",
        [
            "库存控制塔：风险列表、断货追因、高风险 SKU 清单、库存损耗明细。",
            "支持按风险等级、PMC、店铺、国家、MSKU、FNSKU 过滤。",
            "单 SKU/FNSKU 可进入库存路径拆解：FBA、海外仓、国内仓、在途、待分配。",
        ],
        BLUE,
        LIGHT_BLUE,
    )
    card(
        c,
        M + 406,
        140,
        386,
        145,
        "一期验收",
        [
            "能展示库存控制塔和风险列表。",
            "能解释某个 SKU/FNSKU 的风险来源和数据路径。",
            "能记录人工确认结果和复盘意见，形成后续规则优化输入。",
        ],
        BLUE,
        LIGHT_BLUE,
    )
    draw_footer(c, 4)


def page_phase2(c: canvas.Canvas) -> None:
    title(c, "二期建设：计划与预测增强", "周期建议：第 4-6 周；目标是从看风险升级为给出可复算的计划建议")
    card(
        c,
        M,
        320,
        250,
        165,
        "新增数据",
        [
            "各类规则 Excel：MOQ、箱规、供应商、渠道时效、安全库存。",
            "促销计划、广告变化、品牌/产品等级、利润贡献。",
            "周度采购计划、周度发货计划、预测偏差样本。",
        ],
        GREEN,
        LIGHT_GREEN,
    )
    card(
        c,
        M + 270,
        320,
        250,
        165,
        "规则复算",
        [
            "发货复算：基础发货量、修正量、参考量。",
            "采购复算：基础采购量、修正量、参考量。",
            "MOQ/箱规、库存核对、预测偏差计算。",
        ],
        GREEN,
        LIGHT_GREEN,
    )
    card(
        c,
        M + 540,
        320,
        250,
        165,
        "Agent 工具",
        [
            "计划生成工具、物流建议工具、异常 Case 工具。",
            "RAG 知识库完善：字段定义、SOP、备货规则、复算口径。",
            "权限控制和审计留痕开始纳入日常流程。",
        ],
        GREEN,
        LIGHT_GREEN,
    )
    card(
        c,
        M,
        135,
        386,
        145,
        "业务应用",
        [
            "发货验证、采购验证、周度发货计划。",
            "品牌/产品分层策略，支持优先级和资源倾斜。",
            "销售预估反馈进入计划复盘，形成预测偏差闭环。",
        ],
        GREEN,
        LIGHT_GREEN,
    )
    card(
        c,
        M + 406,
        135,
        386,
        145,
        "二期验收",
        [
            "能生成发货验证表、采购验证表，并解释差异。",
            "能生成周度发货计划草稿。",
            "能追踪采纳率、命中率、预测偏差和复盘循环。",
        ],
        GREEN,
        LIGHT_GREEN,
    )
    draw_footer(c, 5)


def page_phase3(c: canvas.Canvas) -> None:
    title(c, "三期建设：协同自动化与智能体群", "周期建议：第 6-9 周；目标是审批流、有限写回和跨系统协同闭环")
    card(
        c,
        M,
        320,
        250,
        165,
        "系统协同",
        [
            "接入采购系统、物流系统，建立 ERP/WMS 写回接口。",
            "只开放受控写回：草稿、状态、审批结果、反馈记录。",
            "正式采购、发货、库存修改仍需审批和权限校验。",
        ],
        ORANGE,
        LIGHT_ORANGE,
    )
    card(
        c,
        M + 270,
        320,
        250,
        165,
        "闭环数据",
        [
            "动作日志、审批流、异常 Case、建议版本、写回结果表。",
            "写回前后校验：库存差异、采购差异、发货差异。",
            "沉淀规则优化、计划修正、复盘记录。",
        ],
        ORANGE,
        LIGHT_ORANGE,
    )
    card(
        c,
        M + 540,
        320,
        250,
        165,
        "智能体群",
        [
            "主 Agent 控制进度和边界。",
            "采购 Agent、物流 Agent、库存 Agent 分工协作。",
            "多仓备发集成调度，支持异常升级和责任追踪。",
        ],
        ORANGE,
        LIGHT_ORANGE,
    )
    card(
        c,
        M,
        135,
        386,
        145,
        "业务应用",
        [
            "采购协同、物流协同、异常 Case 闭环。",
            "从建议生成、审批、执行、写回、复盘形成完整工作流。",
            "对关键动作进行有限回写和全链路审计。",
        ],
        ORANGE,
        LIGHT_ORANGE,
    )
    card(
        c,
        M + 406,
        135,
        386,
        145,
        "三期验收",
        [
            "写回成功率、协同处理时长、异常关闭率、审批完整率可统计。",
            "计划修正、规则优化、复盘沉淀形成闭环。",
            "跨系统协同不突破权限边界。",
        ],
        ORANGE,
        LIGHT_ORANGE,
    )
    draw_footer(c, 6)


def page_tables(c: canvas.Canvas) -> None:
    title(c, "数据表池与风险控制", "首期先用高价值表跑通链路，逐步扩展到明细、预测、计划和写回数据")
    c.setFont("SC-Bold", 13)
    c.setFillColor(NAVY)
    c.drawString(M, 456, "核心表池")
    rows = [
        ("ads_lingxing_all_warehouse_new", "库存控制塔主宽表，作为月度基准快照和主查询入口"),
        ("dim_inventory_forecast_v1", "采购侧未来库存预测，用于缺口测算和采购验证"),
        ("dim_inventory_forecast_v1_fh", "发货侧未来库存预测，用于发货窗口和发货验证"),
        ("ads_lingxing_sc_sales_daily_new", "销售日报，用于真实销量、需求判断和预测偏差核对"),
        ("dwd_lingxing_fba_warehouse_detail", "FBA 库存明细，用于可售、不可售、预留、在途核对"),
        ("dwd_lingxing_inventory_details", "国内仓库存明细，用于本地仓可用、锁定、质检和不良品库存"),
        ("temp_lingxing_stocking_rules", "现行备货规则，用于安全库存、时效、补货频率等口径"),
    ]
    x, y = M, 428
    col1, col2 = 250, PAGE_W - 2 * M - 250
    c.setFillColor(LIGHT_GRAY)
    c.rect(x, y, col1 + col2, 24, stroke=0, fill=1)
    c.setFillColor(TEXT)
    c.setFont("SC-Bold", 9)
    c.drawString(x + 8, y + 8, "数据表")
    c.drawString(x + col1 + 8, y + 8, "用途")
    y -= 24
    c.setFont("SC", 8)
    for i, (name, use) in enumerate(rows):
        c.setFillColor(colors.white if i % 2 == 0 else colors.HexColor("#FAFBFC"))
        c.rect(x, y, col1 + col2, 24, stroke=0, fill=1)
        c.setFillColor(TEXT)
        c.drawString(x + 8, y + 8, name)
        c.drawString(x + col1 + 8, y + 8, use)
        c.setStrokeColor(colors.HexColor("#EAECF0"))
        c.line(x, y, x + col1 + col2, y)
        y -= 24

    card(
        c,
        M,
        88,
        386,
        135,
        "主要风险",
        [
            "数据口径不一致：每个答案必须展示来源、字段路径和计算口径。",
            "规则复杂度高：优先固化高频规则，低频场景进入人工确认。",
            "模型幻觉：库存、日期、金额、采购量和发货量只由规则工具计算。",
        ],
        NAVY,
        colors.HexColor("#F8FAFC"),
    )
    card(
        c,
        M + 406,
        88,
        386,
        135,
        "治理机制",
        [
            "权限边界：按 PMC、采购、物流、运营和管理层控制可见数据和动作。",
            "人工确认：高风险动作必须审批，首期只输出草稿和建议。",
            "审计留痕：保留建议、修改、导出、确认、写回和关闭记录。",
        ],
        NAVY,
        colors.HexColor("#F8FAFC"),
    )
    draw_footer(c, 7)


def page_acceptance(c: canvas.Canvas) -> None:
    title(c, "里程碑与验收标准", "以能用、可信、可复算、可闭环为交付原则")
    milestones = [
        ("一期 1-3 周", "库存控制塔 MVP", "风险列表、单 SKU 追因、库存路径拆解、人工确认结果"),
        ("二期 4-6 周", "计划与预测增强", "发货验证、采购验证、周度发货计划、预测偏差反馈"),
        ("三期 6-9 周", "协同自动化与智能体群", "审批流、有限写回、异常 Case 闭环、多 Agent 协作"),
    ]
    x, y = M, 385
    widths = [130, 210, PAGE_W - 2 * M - 340]
    c.setFillColor(NAVY)
    c.rect(x, y + 30, sum(widths), 30, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("SC-Bold", 10)
    c.drawString(x + 10, y + 40, "阶段")
    c.drawString(x + widths[0] + 10, y + 40, "主题")
    c.drawString(x + widths[0] + widths[1] + 10, y + 40, "交付物")
    c.setFont("SC", 10)
    for i, row in enumerate(milestones):
        yy = y - i * 42
        c.setFillColor(colors.white if i % 2 == 0 else colors.HexColor("#FAFBFC"))
        c.rect(x, yy, sum(widths), 42, stroke=0, fill=1)
        c.setFillColor(TEXT)
        c.drawString(x + 10, yy + 16, row[0])
        c.drawString(x + widths[0] + 10, yy + 16, row[1])
        c.drawString(x + widths[0] + widths[1] + 10, yy + 16, row[2])
        c.setStrokeColor(colors.HexColor("#EAECF0"))
        c.line(x, yy, x + sum(widths), yy)

    c.setFillColor(NAVY)
    c.setFont("SC-Bold", 14)
    c.drawString(M, 210, "验收标准")
    acceptance = [
        "能展示库存控制塔，并按风险等级、PMC、店铺、国家、MSKU、FNSKU 过滤。",
        "能按单 SKU/FNSKU 追溯断货原因，并清楚区分 FBA、海外仓、国内仓、在途、待分配路径。",
        "能生成发货验证表、采购验证表和周度计划草稿，并解释差异来源。",
        "能回答字段口径、SOP、备货规则、发货/采购计算规则等知识问题。",
        "能记录人工确认、手工修改、异常原因、处理结果和复盘意见。",
        "能识别缺失 M3、预测、FBA 明细等数据问题，并明确提示不可编造。",
    ]
    bullet_block(c, M + 6, 180, PAGE_W - 2 * M - 12, acceptance, size=10, leading=16)
    draw_footer(c, 8)


def build() -> None:
    register_fonts()
    c = canvas.Canvas(str(PDF_PATH), pagesize=landscape(A4))
    pages = [page_cover, page_reference, page_overview, page_phase1, page_phase2, page_phase3, page_tables, page_acceptance]
    for page in pages:
        page(c)
        c.showPage()
    c.save()
    print(PDF_PATH)


if __name__ == "__main__":
    build()
