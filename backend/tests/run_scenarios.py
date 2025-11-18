import asyncio
import json
from pathlib import Path

from app.agent import FormAgent
from app.db import Database
from app.llm_client import LlmClient


async def run() -> None:
  here = Path(__file__).resolve().parent
  scenarios_path = here / "scenarios.json"
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


