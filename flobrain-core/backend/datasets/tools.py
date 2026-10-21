"""The ``data.ask`` buddy tool: any buddy offered it can answer questions from datasets the user can
see. Read-only (risk ``read``, permission ``data.use``); the same pipeline as ``POST data/ask``."""

from actions.registry import READ

KEY = "data.ask"
SPEC = {
    "perm_key": "data.use",
    "flag": "data_buddy",
    "risk": READ,
    "label": "Ask a dataset",
    "description": (
        "Answer a question from one of the organization's datasets (uploaded files, Google Sheets, "
        "databases). Give the dataset id, or its name. Read-only: it runs one checked SELECT."
    ),
    "schema": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "minLength": 1, "maxLength": 500},
            "dataset": {"type": "string", "format": "uuid"},
            "dataset_name": {"type": "string", "minLength": 1, "maxLength": 120},
        },
        "required": ["question"],
        "additionalProperties": False,
    },
}
ROWS = 50


def _dataset(user, org, args):
    from actions.service import ActionDenied
    from datasets import services

    if not services.flag_on(user, org):
        raise ActionDenied("not_available", "the data buddy is not enabled")
    visible = services.visible_datasets(user, org)
    if args.get("dataset"):
        ds = visible.filter(pk=args["dataset"]).first()
    elif args.get("dataset_name"):
        ds = visible.filter(name__iexact=args["dataset_name"].strip()).first()
    else:
        ds = visible.first() if visible.count() == 1 else None
    if ds is None:
        raise ActionDenied("not_found", "dataset not found")
    return ds


def check(user, org, args) -> str:
    ds = _dataset(user, org, args)
    return f"Ask “{args['question'][:80]}” about {ds.name[:60]}"


def execute(user, org, args) -> dict:
    from actions.service import ActionDenied
    from datasets import services

    ds = _dataset(user, org, args)
    try:
        result = services.ask(user, org, ds, args["question"])
    except services.DataError as exc:
        raise ActionDenied("invalid" if exc.status < 500 else "failed", exc.details) from exc
    return {
        "dataset": str(ds.id),
        "answer": result["answer"],
        "sql": result["sql"],
        "columns": result["columns"],
        "rows": result["rows"][:ROWS],
        "truncated": result["truncated"] or len(result["rows"]) > ROWS,
        "chart": result["chart"],
    }


def register():
    from actions.plugins import handler, register_tool

    if handler(KEY) is None:
        register_tool(KEY, SPEC, check=check, execute=execute)
