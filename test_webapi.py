"""Workflow web API input self-check. Run: python test_webapi.py"""
from omnigent.workflow.adapter import contract_prompt
from omnigent.workflow.webapi import _safe_paths, _validate_tasks


def main():
    tasks = _validate_tasks([{
        "title": "Scoped task", "ownership": ["omnigent/web.py"],
        "do_not_modify": ["omnigent/core.py"], "validation": "python test_workflow.py",
        "priority": 3, "acceptance_criteria": ["works"],
    }])
    task = tasks[0]
    prompt = contract_prompt({**task, "description": "", "acceptance_criteria": task["acceptance_criteria"]})
    assert "omnigent/web.py" in prompt and "omnigent/core.py" in prompt
    assert "python test_workflow.py" in prompt and task["priority"] == 3
    for bad in (["../secret"], ["C:/secret"], ["/etc/passwd"]):
        try:
            _safe_paths(bad, "ownership")
            raise AssertionError(f"unsafe path accepted: {bad}")
        except ValueError:
            pass
    try:
        _validate_tasks([{"title": "bad", "depends_on": [1]}])
        raise AssertionError("future dependency accepted")
    except ValueError:
        pass
    print("webapi input self-check ok")


if __name__ == "__main__":
    main()
