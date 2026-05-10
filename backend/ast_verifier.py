"""
ast_verifier.py
Static call-site verification for BlastRadius.

Given the source of a caller file and the name of a callee symbol, returns:
  VERIFIED       — AST/regex confirms the callee is directly invoked in the caller
  INFERRED       — No direct call found; the relationship was inferred by Gemini
  UNVERIFIABLE   — Cannot parse the source (syntax error) or extension unsupported
"""

import ast
import re
from typing import Literal

VerificationStatus = Literal["VERIFIED", "INFERRED", "UNVERIFIABLE"]


def verify_call(
    caller_content: str,
    callee_name: str,
    file_extension: str,
) -> VerificationStatus:
    """Return the verification status of a call edge.

    Args:
        caller_content: Full source text of the caller file.
        callee_name:    The symbol (function/module name) being called.
        file_extension: Extension of the caller file, e.g. '.py', '.js'.
    """
    if not caller_content or not callee_name:
        return "UNVERIFIABLE"

    if file_extension == ".py":
        return _verify_python(caller_content, callee_name)
    if file_extension in (".js", ".ts", ".jsx", ".tsx"):
        return _verify_js(caller_content, callee_name)
    return "UNVERIFIABLE"


def _verify_python(source: str, callee_name: str) -> VerificationStatus:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return "UNVERIFIABLE"

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == callee_name:
                return "VERIFIED"
            if isinstance(func, ast.Attribute) and func.attr == callee_name:
                return "VERIFIED"
    return "INFERRED"


def _verify_js(source: str, callee_name: str) -> VerificationStatus:
    # Match bare call `callee(` or tagged template `callee\`` — word boundary on left
    pattern = r"(?<!\w)" + re.escape(callee_name) + r"(?:\s*\(|\s*`)"
    if re.search(pattern, source):
        return "VERIFIED"
    return "INFERRED"
