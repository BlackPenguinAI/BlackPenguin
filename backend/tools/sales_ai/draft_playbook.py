"""Prepare a local proposal from an exported Sales agent pack. No DB/network."""
import argparse
import json
from pathlib import Path
from app.modules.sales_agent.turn_configuration import draft_configuration


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True,help='JSON Sales agent pack (agent_ventas only).')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.input.resolve()==args.output.resolve():
        parser.error('Use a separate output file; preserve the exported configuration.')
    agent=json.loads(args.input.read_text())
    if not isinstance(agent,dict) or not agent.get('model') or any(k in agent for k in ('openrouter_api_key','agent_ventas','company_id')):
        parser.error('Provide only the Sales agent pack, without credentials or configuration wrapper.')
    with args.output.open('x') as output:
        json.dump(draft_configuration(agent),output,ensure_ascii=False,indent=2)
        output.write('\n')


if __name__=='__main__':main()
