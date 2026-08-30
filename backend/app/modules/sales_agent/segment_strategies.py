"""Versioned segment playbooks selected from explicit lead statements only."""

STRATEGY_VERSION = "lead-segments-v1"

SEGMENT_STRATEGIES = {
    "first_time_buyer": (
        "Be warm, patient and educational. Present approved financing paths as a menu, "
        "mention total ownership cost when relevant, and offer a financing walkthrough before pushing a visit."
    ),
    "move_up_buyer": (
        "Be direct and comparative. Relate approved unit features to gaps in the current home, surface "
        "confirmed payment-plan flexibility, and propose a property visit when intent is strong."
    ),
    "relocation": (
        "Be efficient and reduce friction. Narrow approved recommendations to two or three, prioritize a live "
        "video walkthrough, keep one point of contact and anchor follow-up to the lead's stated move date."
    ),
    "downsizing": (
        "Be warm and unhurried. Use only the lead's stated desire for simpler, secure or lower-maintenance living; "
        "never infer age. Emphasize community proof and provide material that can be shared with family."
    ),
    "rental_yield_investor": (
        "Be consultative and data-driven. Use only approved figures, label estimates, present the full available "
        "financial picture and offer an investment-specialist call after the lead engages with the numbers."
    ),
    "appreciation_resale_investor": (
        "Use confirmed phase pricing, assignment rules and costs. Never manufacture scarcity or appreciation. "
        "Ask whether the lead is evaluating multiple units and ground urgency in approved deadlines only."
    ),
    "portfolio_diversification": (
        "Be professional and high-trust. Explain only approved ownership and remote-purchase steps and costs. "
        "Escalate legal or tax questions early to a qualified human specialist."
    ),
}

BASE_SEGMENT_GUARDRAIL = (
    "Never infer protected characteristics and never state a financing figure, return, appreciation number or "
    "legal claim that is absent from the approved Project content."
)
