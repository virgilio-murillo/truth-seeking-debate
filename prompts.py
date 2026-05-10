from models import ContentionNode


def opening_prompt(topic: str, team: str) -> str:
    side = "in favor of" if team == "a" else "against"
    return (
        f"You are Team {team.upper()} in a truth-seeking debate.\n"
        f"Topic: {topic}\n\n"
        f"Write your opening statement {side} the topic. "
        "Be thorough, cite evidence. Your goal is TRUTH, not winning.\n"
        "Output ONLY your opening statement."
    )


def contention_identification_prompt(opening_a: str, opening_b: str) -> str:
    return (
        "Identify specific points of disagreement between these openings.\n\n"
        f"TEAM A:\n{opening_a}\n\nTEAM B:\n{opening_b}\n\n"
        "Output ONLY a JSON array:\n"
        '[{"claim": "...", "team_a_position": "...", "team_b_position": "..."}]'
    )


def debate_round_prompt(node: ContentionNode, team: str, truths_ctx: str) -> str:
    my_pos = node.team_a_position if team == "a" else node.team_b_position
    opp_pos = node.team_b_position if team == "a" else node.team_a_position

    # Full exchange history for this contention
    history = ""
    if node.exchanges:
        history = "EXCHANGE HISTORY:\n" + "\n".join(
            f"  [R{e.round} Team {e.team.upper()}]: {e.content}" for e in node.exchanges
        ) + "\n\n"

    # Child truths if any
    child_ctx = ""
    if node.children:
        child_ctx = "RESOLVED SUB-DISPUTES:\n"
        # Note: we can't access state.tree here, so children truths are in the exchanges

    return (
        f"You are Team {team.upper()} in a truth-seeking debate. Round {node.current_round}/7.\n\n"
        f"CONTENTION: {node.claim}\n"
        f"Your position: {my_pos}\n"
        f"Opponent's position: {opp_pos}\n\n"
        f"{history}"
        f"ESTABLISHED TRUTHS:\n{truths_ctx}\n\n"
        "RULES:\n"
        "- Goal is TRUTH. If opponent is right, agree with evidence.\n"
        "- To agree: AGREEMENT: {\"reason\": \"...\", \"evidence\": \"...\", \"revised_position\": \"...\"}\n"
        "- If a factual sub-dispute must be resolved first:\n"
        "  CHILD_CONTENTION: {\"claim\": \"...\", \"your_position\": \"...\", \"opponent_position\": \"...\"}\n"
        "- Otherwise present your argument with evidence.\n\n"
        "Your response:"
    )


def judge_prompt(node: ContentionNode) -> str:
    history = "\n".join(f"[R{e.round} {e.team.upper()}]: {e.content}" for e in node.exchanges)
    return (
        f"Judge this contention after {node.current_round} rounds:\n\n"
        f"CLAIM: {node.claim}\n"
        f"Team A: {node.team_a_position}\nTeam B: {node.team_b_position}\n\n"
        f"EXCHANGES:\n{history}\n\n"
        "Score: evidence(0.30), logic(0.25), consistency(0.20), sources(0.15), concessions(0.10)\n\n"
        "Output ONLY JSON:\n"
        "{\"winner\": \"team_a|team_b|both_correct\", \"truth\": \"what is true\", \"confidence\": 0.0-1.0}"
    )


def relevance_gate_prompt(parent: ContentionNode, child_claim: str) -> str:
    return (
        f"Is this sub-dispute MATERIAL?\nPARENT: {parent.claim}\nCHILD: {child_claim}\n\n"
        "Output ONLY JSON: {\"relevant\": true/false, \"score\": 0.0-1.0, \"reason\": \"...\"}"
    )


def agreement_validation_prompt(node: ContentionNode, agreement: dict, team: str) -> str:
    return (
        f"Validate agreement:\nCONTENTION: {node.claim}\n"
        f"Team {team.upper()} agrees. Reason: {agreement.get('reason', '')}\n"
        f"Evidence: {agreement.get('evidence', '')}\n\n"
        "Genuine (with evidence) or sycophantic?\n"
        "Output ONLY JSON: {\"valid\": true/false, \"truth\": \"agreed truth\", \"confidence\": 0.0-1.0}"
    )
