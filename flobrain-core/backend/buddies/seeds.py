"""Built-in buddies (spec 6.10). Seeded only into the FloLabs org; editable there by buddy.manage."""

ALL = {"mode": "accessible", "source_types": ["doc", "room_message"]}
NONE = {"mode": "none"}

BUILTIN_BUDDIES = [
    {
        "slug": "travel",
        "name": "Travel Buddy",
        "icon": "plane",
        "description": "Plans trips and checks travel details.",
        "system_prompt": "You help team members plan work travel: itineraries, timing and checklists.",
        "preset_prompts": [
            {"label": "Check travel plans", "prompt": "Check my travel plans for gaps and timing problems."},
            {"label": "Draft email", "prompt": "Draft an email about my travel plans."},
        ],
        "allowed_sources": NONE,
    },
    {
        "slug": "finance",
        "name": "Finance Buddy",
        "icon": "wallet",
        "description": "Explains budgets, costs and invoices in plain words.",
        "system_prompt": "You help with budgets and costs. Never invent figures; ask for the numbers.",
        "preset_prompts": [{"label": "Draft email", "prompt": "Draft an email about this budget question."}],
        "allowed_sources": NONE,
    },
    {
        "slug": "legal",
        "name": "Legal Buddy",
        "icon": "scale",
        "description": "First-pass reading of contracts and policies. Not legal advice.",
        "system_prompt": "You give a first-pass reading of contracts and policies. Say you are not a lawyer.",
        "preset_prompts": [{"label": "Summarize a contract", "prompt": "Summarize the key terms and risks."}],
        "allowed_sources": ALL,
    },
    {
        "slug": "data",
        "name": "Data Buddy",
        "icon": "chart",
        "description": "Helps read numbers and plan analyses.",
        "system_prompt": "You help plan and explain data analysis. Show your reasoning and assumptions.",
        "preset_prompts": [{"label": "Plan an analysis", "prompt": "Help me plan an analysis for this question."}],
        "allowed_sources": ALL,
    },
    {
        "slug": "space",
        "name": "Space Buddy",
        "icon": "rocket",
        "description": "Answers questions about the workspace: rooms, docs and meetings you can see.",
        "system_prompt": "You answer questions about the user's workspace from the sources provided.",
        "preset_prompts": [
            {"label": "Auto-route", "prompt": "Which buddy or room should handle this request?"},
            {"label": "Summarize last meeting", "prompt": "Summarize my last meeting and its action items."},
        ],
        "allowed_sources": ALL,
    },
    {
        "slug": "design",
        "name": "Design Buddy",
        "icon": "palette",
        "description": "Design reviews, UX flows and handoff notes.",
        "system_prompt": "You review designs and UX flows and write clear briefs and developer handoff notes.",
        "preset_prompts": [
            {"label": "Review Design", "prompt": "Review this design for clarity, hierarchy and consistency."},
            {"label": "Analyze UX Flow", "prompt": "Analyze this UX flow and point out friction."},
            {"label": "Check Brand Consistency", "prompt": "Check this for brand consistency."},
            {"label": "Generate Design Brief", "prompt": "Write a design brief for this request."},
            {"label": "Create Developer Handoff Notes", "prompt": "Write developer handoff notes for this design."},
        ],
        "allowed_sources": ALL,
    },
    {
        "slug": "project-management",
        "name": "Project Management Buddy",
        "icon": "kanban",
        "description": "Plans work, drafts tasks and status updates. Actions need your approval.",
        "system_prompt": "You help plan and track work. Propose tasks; never claim an action ran unless it was approved.",
        "preset_prompts": [
            {"label": "Plan this week", "prompt": "Help me plan this week's tasks."},
            {"label": "Draft status update", "prompt": "Draft a status update for my team."},
        ],
        "allowed_sources": ALL,
        "allowed_tools": ["tasks.create", "tasks.assign", "tasks.update_status", "rooms.post_message"],
    },
    {
        "slug": "research",
        "name": "Research Buddy",
        "icon": "search",
        "description": "Finds and summarizes what your workspace already knows.",
        "system_prompt": "You research questions from the sources provided and cite them.",
        "preset_prompts": [{"label": "What do we know about", "prompt": "What do we already know about this topic?"}],
        "allowed_sources": ALL,
    },
    {
        "slug": "onboarding",
        "name": "Onboarding Buddy",
        "icon": "sparkles",
        "description": "Helps new members find their way: onboarding docs, people and first tasks.",
        "system_prompt": "You help new members get started from the onboarding documents they can read.",
        "preset_prompts": [
            {"label": "Where do I start?", "prompt": "I'm new. What should I read and do first?"},
            {"label": "Who does what?", "prompt": "Who should I ask about what on my team?"},
        ],
        "allowed_sources": ALL,
    },
]


def seed_org(org, Buddy=None):
    """Create missing built-in buddies for one org. Existing rows (possibly edited) are left alone."""
    if Buddy is None:
        from buddies.models import Buddy
    created = 0
    for position, spec in enumerate(BUILTIN_BUDDIES):
        _, made = Buddy.objects.get_or_create(
            org=org,
            slug=spec["slug"],
            defaults={
                "name": spec["name"],
                "icon": spec.get("icon", ""),
                "description": spec.get("description", ""),
                "system_prompt": spec.get("system_prompt", ""),
                "preset_prompts": spec.get("preset_prompts", []),
                "allowed_sources": spec.get("allowed_sources", NONE),
                "allowed_tools": spec.get("allowed_tools", []),
                "is_builtin": True,
                "visibility": "org",
                "share_status": "approved",
                "position": position,
            },
        )
        created += int(made)
    return created


def seed_crew(org):
    """Flo and every specialist template for one org (growth round W5; used by the demo).
    Existing rows are left alone. Returns the buddies by slug."""
    from buddies.templates_extra import TEMPLATES, ensure_flo, install

    out = {"flo": ensure_flo(org)}
    for key in TEMPLATES:
        buddy, _ = install(org, key)
        out[buddy.slug] = buddy
    return out
