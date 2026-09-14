"""Kubernetes-owned daily preparation/reporting entry point; fixed local owner and destination."""
import argparse,json,sys
from scripts.email_report import state_directory
from src.applications.daily import run

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    try:print(json.dumps(run(state_directory(),check=args.check)))
    except Exception as error:
        print('Daily workflow stopped; error_class='+type(error).__name__+'; inspect authenticated workflow status.',file=sys.stderr)
        return 1
    return 0

if __name__=='__main__':raise SystemExit(main())
