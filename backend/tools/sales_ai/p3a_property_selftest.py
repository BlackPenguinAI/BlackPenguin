"""Offline regression gate for the P3-A property identity and continuation patch."""
import subprocess
import sys


def main():
    return subprocess.call([sys.executable,'-m','pytest','-q',
        'tests/test_sales_p3a_property_continuity.py',
        'tests/test_sales_live_conversation_p0.py',
        'tests/test_sales_active_integration.py'])


if __name__=='__main__':
    raise SystemExit(main())
