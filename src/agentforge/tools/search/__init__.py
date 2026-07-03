"""Search providers for the Web_Search_Tool.

The abstract ``Search_Provider`` seam (``base.py``) is consumed by the Web_Search_Tool;
the keyless default ``Disabled_Search_Provider`` (``disabled.py``) never performs a
network request (Req 5.2, 5.4).
"""

from __future__ import annotations
