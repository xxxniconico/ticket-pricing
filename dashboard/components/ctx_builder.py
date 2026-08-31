"""pred_args / rule labels — detect_ctx 与 optimizer 之间的唯一桥接层。"""
from src.classify import DERBY_RIVALS

_CTX_KEYS = (
    "away_winless",
    "away_winless_losses",
    "consecutive_home_losses",
    "poor_home_form",
    "heavy_home_loss",
    "short_rest",
    "midseason_restart",
    "season_opener",
    "top3_form",
)


def ctx_kwargs(ctx):
    """从 detect_ctx 结果提取 rule_engine / optimizer 所需的布尔 flag。"""
    return {k: ctx.get(k, False) for k in _CTX_KEYS}


def build_pred_args(match, ctx, overrides=None):
    """从 match dict + context dict 构建 optimize() 参数字典。"""
    import pandas as pd

    dt = pd.Timestamp(match["date"])
    opp = match["opponent"]
    args = {
        "derby": opp in DERBY_RIVALS,
        "saturday": dt.weekday() == 5,
        "late_season": dt.month >= 11,  # 冬季（11月起北京转冷，上座下降）
        "midweek": dt.weekday() in (1, 2, 3),
        "summer": dt.month in (7, 8),
        "season_opener": ctx.get("season_opener", False),
        "midseason_restart": ctx.get("midseason_restart", False),
        "match_year": match["date"][:4],
        **ctx_kwargs(ctx),
    }
    if overrides:
        args.update(overrides)
    return args


def build_rule_labels(pred_args):
    """从 pred_args 构建人类可读的规则标签列表。"""
    labels = []
    if pred_args.get("derby"):
        labels.append("德比")
    if pred_args.get("season_opener"):
        labels.append("揭幕战")
    if pred_args.get("midseason_restart"):
        labels.append("盛夏重启")
    if pred_args.get("saturday"):
        labels.append("周六")
    if pred_args.get("summer"):
        labels.append("暑假")
    if pred_args.get("top3_form"):
        labels.append("榜首")
    if pred_args.get("late_season"):
        labels.append("冬季")
    if pred_args.get("consecutive_home_losses"):
        labels.append("主场连败")
    elif pred_args.get("poor_home_form"):
        labels.append("主场低迷")
    elif pred_args.get("heavy_home_loss"):
        labels.append("主场惨败")
    if pred_args.get("away_winless_losses"):
        labels.append("客场全败")
    elif pred_args.get("away_winless"):
        labels.append("客场不胜")
    if pred_args.get("midweek"):
        labels.append("工作日")
    if pred_args.get("short_rest"):
        labels.append("双赛周")
    return labels
