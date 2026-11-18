"""Run the isolated P0 live-conversation regression gate without provider calls."""
import subprocess
import sys


def main():
    return subprocess.call([sys.executable,'-m','pytest','-q',
                            'tests/test_sales_live_conversation_p0.py',
                            'tests/test_sales_composer_http.py',
                            'tests/test_sales_delivery3_contact_closing.py'])


if __name__=='__main__':
    raise SystemExit(main())
