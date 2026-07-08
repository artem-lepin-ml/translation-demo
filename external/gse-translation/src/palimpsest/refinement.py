from __future__ import annotations

import json
from pathlib import Path

from tqdm.asyncio import tqdm

from .config import load_refinement, load_models
from .paths import PROMPTS
from .llm.client import LLMClient, LLMConfig, EmptyContentError


_REFINEMENT_MSG_TEMPLATE = (
    "**Source text (Russian)**:\n{}\n\n"
    "**Translation (English)**:\n{}\n\n"
    "The following translation issues were found. Please fix the translation accordingly:\n\n{}"
)


def _build_edit_message(json_line: dict, criterias: list[str]) -> str:
    lines = []

    for criteria in criterias:
        if not (json_line[criteria] and json_line[criteria].get('identified_issues')):
            continue

        criteria_issues = json_line[criteria]['identified_issues']

        lines.append(f"### {criteria.title()} issues")

        for i, issue in enumerate(criteria_issues, start=1):
            lines.append(f"Issue {i}:")

            if issue.get("source_fragment"):
                lines.append(f"- Source fragment: {issue['source_fragment']}")
            if issue.get("problematic_fragment"):
                lines.append(f"- Problematic fragment: {issue['problematic_fragment']}")
            if issue.get("explanation"):
                lines.append(f"- Explanation: {issue['explanation']}")
            if issue.get("suggestion"):
                lines.append(f"- Suggestion: {issue['suggestion']}")

        lines.append("")

    if not lines:
        return ""

    issues = "\n".join(lines).strip()
    edit_message = _REFINEMENT_MSG_TEMPLATE.format(
        json_line['source'],
        json_line['translated'],
        issues
    )

    return edit_message


async def run_refinement(
    scores_jsonl: Path,
    output: Path,
    max_concurrency: int
):
    models = load_models()
    cfg = load_refinement()

    llm = LLMClient(
        LLMConfig.from_model_config(models[cfg.editor_model]),
        max_concurrency=max_concurrency
    )

    system = (PROMPTS / cfg.system_prompt).read_text(encoding='utf-8')


    async def refine_one(json_line: dict):
        user = _build_edit_message(json_line, cfg.refinement_criterias)
        if not user:
            return json_line['translated']

        try:
            translation = (await llm.complete(system, user)).content
        except EmptyContentError as e:
            print(f'Cannot refine paragraph with id={json_line['id']}. Exception: {e}')
            translation = json_line['translated']
        
        if output.suffix != '.json':
            translation = translation.replace('\n', ' ')
        
        return translation.strip()


    def tasks(json_path: Path):
        with json_path.open(encoding='utf-8') as file:
            for line in file:
                yield refine_one(json.loads(line))


    results = await tqdm.gather(*tasks(scores_jsonl))

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix == '.json':
        output.write_text(
            json.dumps(results, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    else:
        output.write_text('\n'.join(results), encoding='utf-8')