"""Demo model answers for the data buddy (``DEMO_AI`` only).

Step 1 (``[flo:data-sql]``): maps common questions about the three demo datasets (sign-ups by week
and channel, support tickets, Q4 budget lines) to correct SQL, and answers anything else with a safe
``SELECT * ... LIMIT 20``. Step 2 (``[flo:data-chart]``): picks a chart from the real result and
words a short answer from its numbers. Every answer says it is demo output.
"""

import json
import re

from brain.llm.demo_ai import _result

SQL_MARKER = "[flo:data-sql]"
CHART_MARKER = "[flo:data-chart]"
SCHEMA = re.compile(r"<schema>\n(.*)\n</schema>", re.DOTALL)
RESULT = re.compile(r"<result>\n(.*)\n</result>", re.DOTALL)
QUESTION = re.compile(r"Question:\s*(.*)")

SIGNUPS = {
    "vs": "SELECT week, signups FROM (SELECT week, SUM(signups) AS signups FROM data GROUP BY week ORDER BY week DESC LIMIT 2) ORDER BY week",
    "channel": "SELECT channel, SUM(signups) AS signups FROM data GROUP BY channel ORDER BY signups DESC",
    "total": "SELECT SUM(signups) AS total_signups FROM data",
    "trend": "SELECT week, SUM(signups) AS signups FROM data GROUP BY week ORDER BY week",
    "channel_week": "SELECT week, channel, SUM(signups) AS signups FROM data GROUP BY week, channel ORDER BY week, channel",
}
TICKETS = {
    "status": "SELECT status, COUNT(*) AS tickets FROM data GROUP BY status ORDER BY tickets DESC",
    "priority": "SELECT priority, COUNT(*) AS tickets FROM data GROUP BY priority ORDER BY tickets DESC",
    "category": "SELECT category, COUNT(*) AS tickets FROM data GROUP BY category ORDER BY tickets DESC",
    "response": "SELECT priority, ROUND(AVG(first_response_hours), 1) AS avg_first_response_hours FROM data GROUP BY priority ORDER BY avg_first_response_hours",
    "open": "SELECT COUNT(*) AS open_tickets FROM data WHERE status IN ('Open', 'Pending')",
    "trend": "SELECT substr(opened_on, 1, 7) AS month, COUNT(*) AS tickets FROM data GROUP BY month ORDER BY month",
}
BUDGET = {
    "left": "SELECT category, ROUND(SUM(budgeted) - SUM(spent), 2) AS budget_left FROM data GROUP BY category ORDER BY budget_left DESC",
    "over": "SELECT category, line_item, budgeted, spent FROM data WHERE spent > budgeted ORDER BY spent - budgeted DESC",
    "spent": "SELECT category, SUM(budgeted) AS budgeted, SUM(spent) AS spent FROM data GROUP BY category ORDER BY spent DESC",
    "total": "SELECT ROUND(SUM(budgeted) - SUM(spent), 2) AS total_left FROM data",
}


def _has(question, *words):
    return any(w in question for w in words)


def _columns(schema) -> set:
    tables = schema.get("tables") or []
    return {c.get("name") for c in (tables[0].get("columns") or [])} if tables else set()


def pick_sql(schema: dict, question: str) -> str:
    q = question.lower()
    cols = _columns(schema)
    if {"week", "channel", "signups"} <= cols:
        if _has(q, " vs", "versus", "last week", "compare", "this week"):
            return SIGNUPS["vs"]
        if _has(q, "channel", "source") and _has(q, "week", "trend", "over time"):
            return SIGNUPS["channel_week"]
        if _has(q, "channel", "source", "where"):
            return SIGNUPS["channel"]
        if _has(q, "total", "how many", "all time"):
            return SIGNUPS["total"]
        return SIGNUPS["trend"]
    if {"status", "priority", "first_response_hours"} <= cols:
        if _has(q, "response", "how fast", "how long"):
            return TICKETS["response"]
        if _has(q, "priority", "urgent"):
            return TICKETS["priority"]
        if _has(q, "category", "type", "about"):
            return TICKETS["category"]
        if _has(q, "open", "backlog", "waiting") and not _has(q, "status"):
            return TICKETS["open"]
        if _has(q, "month", "trend", "over time"):
            return TICKETS["trend"]
        return TICKETS["status"]
    if {"category", "budgeted", "spent"} <= cols:
        if _has(q, "over budget", "overspent", "over"):
            return BUDGET["over"]
        if _has(q, "total") and not _has(q, "category"):
            return BUDGET["total"]
        if _has(q, "spent", "spend", "used"):
            return BUDGET["spent"]
        return BUDGET["left"]
    tables = schema.get("tables") or []
    name = (tables[0].get("name") if tables else "data") or "data"
    ref = ".".join(f'"{part}"' for part in str(name).split("."))
    if _has(q, "how many", "count"):
        return f"SELECT COUNT(*) AS row_count FROM {ref}"
    return f"SELECT * FROM {ref} LIMIT 20"


def _num(value):
    if isinstance(value, float):
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:,}"
    return str(value)


def chart_and_answer(data: dict, question: str) -> dict:
    from datasets.services import default_chart

    columns, rows = data.get("columns") or [], data.get("rows") or []
    chart = default_chart(columns, rows)
    if chart["type"] == "line" and len(rows) <= 2:
        chart["type"] = "bar"
    if chart["type"] == "line" and len(columns) == 3 and chart["y"] == [columns[2]]:
        chart["series"] = columns[1]  # week, channel, signups: one line per channel
    if not rows:
        answer = "(Demo answer) No rows match that question."
    elif chart["type"] == "number":
        answer = f"(Demo answer) {columns[0].replace('_', ' ').capitalize()}: {_num(rows[0][0])}."
    elif chart["type"] == "bar" and len(rows) == 2 and chart["x"] == "week":
        y = columns.index(chart["y"][0])
        before, now = rows[0][y] or 0, rows[1][y] or 0
        change = f" ({(now - before) / before * 100:+.0f}%)" if before else ""
        answer = f"(Demo answer) This week ({rows[1][0]}): {_num(now)} sign-ups. Last week ({rows[0][0]}): {_num(before)}{change}."
    elif chart["type"] == "bar":
        y = columns.index(chart["y"][0])
        top = rows[0]
        answer = f"(Demo answer) {top[0]} is first with {_num(top[y])} {columns[y].replace('_', ' ')}, out of {len(rows)} groups."
    elif chart["type"] == "line":
        y = columns.index(chart["y"][0])
        answer = (
            f"(Demo answer) {columns[y].replace('_', ' ').capitalize()} went from {_num(rows[0][y])} in {rows[0][0]} "
            f"to {_num(rows[-1][y])} in {rows[-1][0]}."
        )
    else:
        answer = f"(Demo answer) {data.get('total_rows', len(rows))} rows match."
    return {"answer": answer, "chart": chart}


def handle(system, user, messages, tools):
    if SQL_MARKER in (system or ""):
        match = SCHEMA.search(user or "")
        try:
            schema = json.loads(match.group(1)) if match else {}
        except ValueError:
            schema = {}
        question = (QUESTION.findall(user or "") or [""])[-1]
        return _result(json.dumps({"sql": pick_sql(schema, question)}))
    if CHART_MARKER in (system or ""):
        match = RESULT.search(user or "")
        try:
            data = json.loads(match.group(1)) if match else {}
        except ValueError:
            data = {}
        question = (QUESTION.findall(user or "") or [""])[0]
        return _result(json.dumps(chart_and_answer(data, question)))
    return None
