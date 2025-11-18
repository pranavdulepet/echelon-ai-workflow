import asyncio
import json
import sys
from pathlib import Path

here = Path(__file__).resolve()
root = here.parent.parent
if str(root) not in sys.path:
  sys.path.insert(0, str(root))

from app.agent import FormAgent
from app.db import Database
from app.llm_client import LlmClient


async def run() -> None:
  scenarios_path = here.parent / "scenarios.json"
  data = json.loads(scenarios_path.read_text(encoding="utf-8"))

  db = Database()
  llm = LlmClient()
  agent = FormAgent(db=db, llm=llm)

  for scenario in data:
    name = scenario["name"]
    query = scenario["query"]
    print(f"\n=== Scenario: {name} ===")
    result = await agent.plan_and_resolve(query=query, history=[])
    if result["type"] == "clarification":
      print("Clarification question:", result["question"])
    else:
      change_set = result["change_set"]
      tables = ", ".join(sorted(change_set.keys()))
      print("Change-set tables:", tables)
      print(json.dumps(change_set, indent=2))


if __name__ == "__main__":
  asyncio.run(run())


