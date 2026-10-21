"""Demo model answers for buddy evals (``DEMO_AI`` only).

- ``sandbox_answer``: called by the eval sandbox (``evals.sandbox``) in demo mode for a buddy's answer to
  a demo case. It returns the scripted answer for that case (``evals.demo_data``) and, when the case
  expects an action and the buddy is offered it, the same tool call. Anything else returns None and the
  regular demo model answers.
- ``handle``: the judge (``[flo:eval-judge]``) returns the scripted verdict for a demo case, or a neutral
  4/5 for anything else; "Suggest cases" (``[flo:eval-suggest]``) drafts cases from the starter prompts
  and not-helpful reasons in the request. Every output says it is demo output.
"""

import json
import re

from brain.llm.demo_ai import _result

JUDGE_MARK = "[flo:eval-judge]"
SUGGEST_MARK = "[flo:eval-suggest]"
QUESTION = re.compile(r"<question>\n(.*?)\n</question>", re.DOTALL)
ANSWER = re.compile(r"<answer>\n(.*?)\n</answer>", re.DOTALL)
PRESET = re.compile(r"^- [^:\n]{1,40}: (.+)$", re.MULTILINE)
REASON = re.compile(r"^- (wrong|incomplete|off_topic|no_sources|too_long|unsafe|other): (\d+)$", re.MULTILINE)
NAME = re.compile(r"^Name: (.+)$", re.MULTILINE)


def _function(tools, key):
    wanted = key.replace(".", "__")
    for tool in tools or []:
        if tool.get("function", {}).get("name") == wanted:
            return wanted
    return None


def sandbox_answer(config, question, tools):
    from evals import demo_data

    case = demo_data.find(config.get("slug", ""), question)
    if case is None:
        return None
    text, calls, _ = case["good"]
    tool_calls = []
    for call in calls:
        name = _function(tools, call["tool"])
        if name:
            tool_calls.append({"name": name, "arguments": json.dumps(call["args"])})
    return _result(text, tool_calls)


def _verdict(user):
    from evals import demo_data

    question = (QUESTION.findall(user or "") or [""])[0]
    answer = (ANSWER.findall(user or "") or [""])[0].strip()
    case = demo_data.find_any(question)
    if case is not None:
        weak_text, _, weak = case["weak"]
        good = case["good"][2]
        verdict = weak if answer == weak_text.strip() else good
        return {"score": verdict["score"], "reason": f"{verdict['reason']} (Demo judge.)"[:300]}
    return {"score": 4, "reason": "Demo judge: the answer meets the rubric."}


def _suggest(user):
    name = (NAME.findall(user or "") or ["this buddy"])[0].strip()
    cases = []
    starters = (user or "").split("Starter prompts:\n", 1)[-1].split("\nNot helpful reasons", 1)[0]
    for prompt in PRESET.findall(starters)[:3]:
        cases.append({
            "name": prompt[:60],
            "input": prompt,
            "must_include": [],
            "must_not_include": [],
            "must_cite": False,
            "expected_tool": "",
            "max_words": 200,
            "language": "any",
            "rubric": f"{name} answers the request directly and says what it could not check. (Demo suggestion.)",
        })
    reasons = {r for r, _ in REASON.findall(user or "")}
    if "no_sources" in reasons or not reasons:
        cases.append({
            "name": "Cites its sources", "input": "Where does that number come from?", "must_cite": True,
            "language": "any", "rubric": "Points to the document it used with a [n] citation. (Demo suggestion.)",
        })
    if "wrong" in reasons or "incomplete" in reasons or not reasons:
        cases.append({
            "name": "Doesn't guess", "input": "What was the exact figure for last March?", "must_include": ["don't have"],
            "language": "any", "rubric": "Says it doesn't have the figure instead of inventing one. (Demo suggestion.)",
        })
    if "too_long" in reasons:
        cases.append({
            "name": "Short answer", "input": "Give me the short version.", "max_words": 60, "language": "any",
            "rubric": "Answers in a few sentences. (Demo suggestion.)",
        })
    cases.append({
        "name": "Arabic question", "input": "لخص لي أهم النقاط باختصار", "language": "ar",
        "rubric": "Answers in Arabic. (Demo suggestion.)",
    })
    return {"cases": cases[:8]}


def handle(system, user, messages, tools):
    system = system or ""
    if JUDGE_MARK in system:
        return _result(json.dumps(_verdict(user)))
    if SUGGEST_MARK in system:
        return _result(json.dumps(_suggest(user)))
    return None
