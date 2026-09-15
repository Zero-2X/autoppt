from __future__ import annotations

from copy import deepcopy
from typing import Any


_COMMON_RULES = {
    "imagegen_route": "fullpage_imagegen_reconstruct",
    "one_question_per_slide": True,
    "one_primary_visual": True,
    "max_supporting_items": 3,
    "action_title_required": True,
    "source_grounded": True,
    "animation_policy": "no_animation",
    "citation_style": "compact_source_footer",
}


PRESENTATION_PROFILES: dict[str, dict[str, Any]] = {
    "innovation_competition_defense": {
        "label": "科创比赛答辩",
        "style_profile": "academic_light",
        "default_slide_range": [8, 12],
        "default_duration_seconds": 45,
        "narrative": [
            "现实问题", "现有方案不足", "项目方案", "核心技术", "技术创新",
            "产品或系统展示", "实验验证", "应用价值", "比赛总结",
        ],
        "required_focus": [
            "现实问题与代价", "现有方案为什么不够", "核心技术创新",
            "原型/实验/应用证据", "落地价值", "团队与后续计划",
        ],
        "forbidden": [
            "无来源指标", "虚构客户/奖项/排名", "纯商业发布会叙事",
            "把概念图当作实测结果",
        ],
        "page_roles": [
            "cover", "problem_with_evidence", "solution_overview", "technical_route",
            "innovation_with_evidence", "prototype_or_system", "result_with_evidence",
            "application_value", "closing_summary",
        ],
    },
    "thesis_defense": {
        "label": "毕业论文答辩",
        "style_profile": "graduate_defense_navy",
        "default_slide_range": [8, 16],
        "default_duration_seconds": 60,
        "narrative": [
            "研究背景", "研究问题", "文献/现有工作", "研究空白", "研究方法",
            "数据或实验设计", "主要结果", "讨论", "本人贡献", "局限性", "未来工作",
        ],
        "required_focus": [
            "研究问题", "研究空白", "方法合理性", "数据来源与实验设计",
            "主要结果", "本人实际贡献", "局限性与结论边界",
        ],
        "forbidden": [
            "按论文章节平均压缩", "装饰性重绘原始图表", "没有证据的因果表述",
            "把共同工作全部写成本人贡献",
        ],
        "page_roles": [
            "cover", "background", "research_question", "gap_with_related_work",
            "method", "experiment_design", "result_with_evidence", "discussion",
            "contribution", "limitations", "future_work", "closing_summary",
        ],
    },
    "nsfc_application_defense": {
        "label": "国自然申请答辩",
        "style_profile": "nsfc_review_light",
        "default_slide_range": [10, 16],
        "default_duration_seconds": 55,
        "narrative": [
            "研究背景与重大需求", "科学问题", "核心假说", "研究目标", "研究内容",
            "技术路线", "关键技术难点", "项目创新点", "前期研究基础", "可行性分析",
            "风险与替代方案", "预期成果", "总结",
        ],
        "required_focus": [
            "科学问题", "核心假说", "目标与内容逻辑", "技术路线", "创新点",
            "前期基础", "可行性", "风险与替代方案", "预期产出",
        ],
        "forbidden": [
            "产品发布式叙事", "夸大应用价值", "把社会意义替代科学问题",
            "把计划写成已完成成果", "伪造前期基础或基金标识",
        ],
        "page_roles": [
            "cover", "major_need", "scientific_question", "core_hypothesis",
            "objectives_and_content", "technical_route", "key_challenge",
            "innovation_with_evidence", "preliminary_basis", "feasibility",
            "risk_and_alternative", "expected_outcomes", "closing_summary",
        ],
    },
    "nsfc_conclusion_defense": {
        "label": "国自然/科研项目结题答辩",
        "style_profile": "nsfc_review_light",
        "default_slide_range": [8, 14],
        "default_duration_seconds": 55,
        "narrative": [
            "项目目标", "研究任务完成情况", "关键研究结果", "技术或理论突破",
            "代表性成果", "应用或转化情况", "未完成内容与原因", "后续研究计划", "项目总结",
        ],
        "required_focus": [
            "原计划", "已完成", "部分完成", "未完成及原因", "新发现",
            "代表性成果来源", "后续计划与完成成果的边界",
        ],
        "forbidden": [
            "未来计划包装为成果", "隐藏未完成任务", "无来源成果数字",
            "把应用设想写成已转化",
        ],
        "page_roles": [
            "cover", "project_objectives", "task_completion_matrix", "key_results",
            "breakthrough", "representative_outputs", "application_or_transfer",
            "unfinished_and_reasons", "next_plan", "closing_summary",
        ],
    },
    "academic_paper_report": {
        "label": "论文解读/学术报告",
        "style_profile": "academic_light",
        "default_slide_range": [7, 14],
        "default_duration_seconds": 70,
        "narrative": [
            "研究问题", "方法", "核心图表", "结果", "解释", "局限", "个人评价", "Takeaways",
        ],
        "required_focus": [
            "Paper", "Figure/Table", "Direct Observation", "Interpretation", "Slide Claim",
        ],
        "forbidden": [
            "重绘或篡改关键实验图", "把解释写成论文原文结论", "省略样本/单位/基线",
            "用 ImageGen 图替代真实图表",
        ],
        "page_roles": [
            "cover", "research_question", "method", "figure_reading", "result",
            "interpretation", "limitations", "personal_evaluation", "takeaways",
        ],
    },
    "research_progress_report": {
        "label": "科研进展/组会报告",
        "style_profile": "science_dark_contrast",
        "default_slide_range": [6, 14],
        "default_duration_seconds": 50,
        "narrative": ["本期问题", "已完成工作", "当前证据", "困难与风险", "下一步计划", "讨论"],
        "required_focus": ["本期完成边界", "证据", "未解决问题", "下一步可验证动作"],
        "forbidden": ["把计划当结果", "隐藏失败实验", "无来源的进展百分比"],
        "page_roles": ["cover", "question", "completed_work", "evidence", "risk", "next_plan", "discussion"],
    },
}


def presentation_profile_choices() -> tuple[str, ...]:
    return tuple(PRESENTATION_PROFILES)


def get_presentation_profile(name: str | None = None) -> dict[str, Any]:
    key = (name or "innovation_competition_defense").strip().lower().replace("-", "_")
    aliases = {
        "competition": "innovation_competition_defense",
        "innovation": "innovation_competition_defense",
        "thesis": "thesis_defense",
        "paper": "academic_paper_report",
        "nsfc_application": "nsfc_application_defense",
        "nsfc_conclusion": "nsfc_conclusion_defense",
        "research_progress": "research_progress_report",
    }
    key = aliases.get(key, key)
    if key not in PRESENTATION_PROFILES:
        choices = ", ".join(presentation_profile_choices())
        raise ValueError(f"unknown presentation profile: {name}; choose from {choices}")
    profile = deepcopy(PRESENTATION_PROFILES[key])
    profile["profile_id"] = key
    merged = dict(_COMMON_RULES)
    merged.update(profile)
    return merged
