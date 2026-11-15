"""发布决策：基于回归对比结果和验收阈值，给出放行/拦截结论与处理建议。"""
from __future__ import annotations

from typing import Dict, List


class ReleaseDecision:
    """根据回归对比结果和阈值配置，判断是否放行候选模型。"""

    def __init__(self, thresholds: Dict):
        self.thresholds = thresholds
        self.map50_min = thresholds.get('map50_min', 0.75)
        self.per_class_drop_max = thresholds.get('per_class_drop_max', 0.05)
        self.recall_drop_max = thresholds.get('recall_drop_max', 0.10)
        self.critical_classes = thresholds.get('critical_classes', [])

    def decide(self, comparison: Dict) -> Dict:
        """执行决策，返回 verdict / reasons / suggestions / summary。"""
        reasons: List[str] = []
        candidate_map50 = comparison['overall']['candidate']['ap50']
        if candidate_map50 < self.map50_min:
            reasons.append(f'整体 mAP50 {candidate_map50:.4f} 低于下限 {self.map50_min:.4f}')
        else:
            reasons.append(f'整体 mAP50 {candidate_map50:.4f} ≥ 下限 {self.map50_min:.4f}')

        degraded_classes = comparison['degraded_classes']
        critical_degraded = [cls for cls in degraded_classes if cls in self.critical_classes]
        if critical_degraded:
            reasons.append(f'关键类别退化：{", ".join(critical_degraded)}')
        if degraded_classes:
            extra = f' 等 {len(degraded_classes)} 个' if len(degraded_classes) > 5 else ''
            reasons.append(
                f'检测到 {len(degraded_classes)} 个类别 AP50 跌幅超过 {self.per_class_drop_max:.2%}：'
                f'{", ".join(degraded_classes[:5])}{extra}')

        for cls_name, cls_compare in comparison['per_class'].items():
            if not cls_compare['degraded']:
                continue
            drop_ap50 = cls_compare['drop']['ap50']
            drop_recall = cls_compare['drop']['recall']
            if drop_ap50 > self.per_class_drop_max:
                reasons.append(f'{cls_name}：AP50 跌幅 {drop_ap50:+.4f}，超过上限 {self.per_class_drop_max:.4f}')
            if drop_recall > self.recall_drop_max:
                reasons.append(f'{cls_name}：召回率跌幅 {drop_recall:+.4f}，超过上限 {self.recall_drop_max:.4f}')

        suggestions = self._generate_suggestions(comparison)

        if critical_degraded:
            verdict, summary = 'BLOCK', '拦截发布：关键类别出现灾难性遗忘'
        elif candidate_map50 < self.map50_min:
            verdict, summary = 'BLOCK', '拦截发布：整体性能不达标'
        elif degraded_classes:
            verdict, summary = 'WARNING', f'警告：检测到 {len(degraded_classes)} 个类别退化，建议修复后发布'
        else:
            verdict, summary = 'RELEASE', '放行发布：所有检查通过'

        return {'verdict': verdict, 'reasons': reasons, 'suggestions': suggestions, 'summary': summary}

    def _generate_suggestions(self, comparison: Dict) -> List[Dict]:
        """按退化模式生成处理建议（回补数据/调阈值/冻结层/重训练/类别平衡）。"""
        suggestions: List[Dict] = []
        degraded_classes = comparison['degraded_classes']
        if not degraded_classes:
            return suggestions

        high_recall_drop, high_precision_drop = [], []
        for cls_name in degraded_classes:
            cls_compare = comparison['per_class'][cls_name]
            if cls_compare['drop']['recall'] > self.recall_drop_max:
                high_recall_drop.append((cls_name, cls_compare['drop']['recall']))
            if cls_compare['drop']['precision'] > 0.05:
                high_precision_drop.append((cls_name, cls_compare['drop']['precision']))

        if high_recall_drop:
            top = sorted(high_recall_drop, key=lambda x: x[1], reverse=True)[:3]
            detail = ', '.join(f'{cls}（召回率下降 {drop:.1%}）' for cls, drop in top)
            suggestions.append({
                'priority': 'high', 'action': '回补旧数据',
                'detail': f'以下类别漏检严重：{detail}。建议从归档集中采样 500 到 1000 张图片加入训练集，'
                          f'重点关注这些类别的难例（遮挡、光照变化、小目标）。',
                'affected_classes': [cls for cls, _ in top],
            })

        if len(high_recall_drop) > 2:
            suggestions.append({
                'priority': 'medium', 'action': '调整置信度阈值',
                'detail': '多个类别出现漏检，可能是置信度阈值过高。建议尝试降低 conf_thres 至 0.15 到 0.20，'
                          '或对退化类别使用类别特定的阈值。',
                'affected_classes': [cls for cls, _ in high_recall_drop],
            })

        if len(degraded_classes) >= 3:
            suggestions.append({
                'priority': 'medium', 'action': '冻结部分层',
                'detail': f'检测到 {len(degraded_classes)} 个类别同时退化，说明模型可能发生了灾难性遗忘。'
                          f'建议冻结 backbone 前 10 层，只微调 neck 和 head，或使用更小的学习率（如 1e-4）进行增量训练。',
                'affected_classes': degraded_classes,
            })

        critical_degraded = [cls for cls in degraded_classes if cls in self.critical_classes]
        if critical_degraded:
            suggestions.append({
                'priority': 'high', 'action': '重新训练',
                'detail': f'关键类别 {", ".join(critical_degraded)} 出现严重退化。建议：'
                          f'1）检查新数据集是否包含这些类别的足够样本；'
                          f'2）使用旧数据集加新数据集的混合进行重训练；'
                          f'3）考虑使用知识蒸馏保留旧模型能力。',
                'affected_classes': critical_degraded,
            })

        if high_precision_drop:
            top = sorted(high_precision_drop, key=lambda x: x[1], reverse=True)[:2]
            detail = ', '.join(f'{cls}（精确率下降 {drop:.1%}）' for cls, drop in top)
            suggestions.append({
                'priority': 'medium', 'action': '类别平衡',
                'detail': f'以下类别误检增多：{detail}。建议增加负样本（背景图片），'
                          f'或在损失函数中提高这些类别的权重。',
                'affected_classes': [cls for cls, _ in top],
            })

        return suggestions
