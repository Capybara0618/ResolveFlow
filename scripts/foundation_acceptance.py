"""Compatibility entry point for the current three-role concentrated acceptance.

The twenty-account implementation and its immutable report remain in Git history.
Adds synthetic test transactions; never resets existing data or calls a paid model.
"""

from merchant_merge_acceptance import main

if __name__ == "__main__":
    main()
