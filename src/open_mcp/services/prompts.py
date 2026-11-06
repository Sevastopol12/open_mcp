from open_mcp.contracts.task import TaskSpec


def build_task_prompt(spec: TaskSpec) -> str:
    owned = "\n".join(f"- {path}" for path in spec.owned_paths)
    skill = f"\nRequested skill: {spec.skill}" if spec.skill else ""
    return (
        f"Task: {spec.title}\n\n{spec.prompt}\n\n"
        f"Owned paths (do not modify other paths):\n{owned}\n\n"
        "Read the AGENTS.md instructions for every module you touch. Follow existing "
        "patterns, types, and tests. Do not create files outside the owned paths. "
        "End with a final message of at most 40 lines that states what you changed, "
        "how you verified it, and anything left undone."
        f"{skill}"
    )
