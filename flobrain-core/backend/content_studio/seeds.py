"""Built-in templates. FLOQ question card (spec 6.16): 1920x1080, exactly 3 s, two plates dissolving,
headline left in Inter Display Medium, blur-to-sharp per line, only the question text changes."""

FLOQ = {
    "slug": "floq-question-card",
    "name": "FLOQ question card",
    "kind": "question_card",
    "spec": {
        "resolution": [1920, 1080],
        "duration_seconds": 3.0,
        "fps": 30,
        "layers": [
            {"type": "plate", "slot": "plate_a", "from": 0.0, "to": 1.8},
            {"type": "plate", "slot": "plate_b", "from": 1.2, "to": 3.0, "transition": "dissolve"},
            {
                "type": "text",
                "field": "question",
                "font": "Inter Display Medium",
                "align": "left",
                "animation": "blur_to_sharp_per_line",
            },
        ],
        "variables": {"question": {"type": "string", "maxLength": 140, "required": True}},
        "fixed": ["plate_a", "plate_b"],
    },
}

BUILTIN_TEMPLATES = [FLOQ]


def ensure_builtin_templates(org):
    from content_studio.models import ContentTemplate

    for spec in BUILTIN_TEMPLATES:
        ContentTemplate.objects.get_or_create(
            org=org,
            slug=spec["slug"],
            defaults={"name": spec["name"], "kind": spec["kind"], "spec": spec["spec"], "is_builtin": True},
        )
