"""
Code Validator Service for AST-based code security validation.

This service provides pre-execution security validation for generated code:
- Parses code to AST (catches syntax errors)
- Checks for blocked constructs (eval, exec, etc.)
- Validates imports against allowlist
- Detects dangerous patterns (pickle, __import__, etc.)
- Generates fingerprints for deduplication

Flow:
    ToolBuilder generates code -> CodeValidatorService.validate()
    -> Pass: proceed to sandbox execution
    -> Fail: reject code, report blocked constructs
"""
import ast
import hashlib
import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """
    Result of code validation.

    Attributes:
        is_valid: Whether the code passed all validation checks.
        errors: Blocking issues that make the code invalid.
        warnings: Non-blocking issues to be aware of.
        blocked_constructs: List of dangerous constructs found.
        imports_used: Set of module names imported by the code.
    """

    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blocked_constructs: list[str] = field(default_factory=list)
    imports_used: set[str] = field(default_factory=set)


class CodeValidatorService:
    """
    AST-based code validation for safe skill execution.

    Validates generated code before sandbox execution:
    - Parses code to AST (catches syntax errors)
    - Checks for blocked constructs (eval, exec, etc.)
    - Validates imports against allowlist
    - Detects dangerous patterns (pickle, __import__, etc.)
    - Generates fingerprints for deduplication

    Example:
        validator = CodeValidatorService()

        # Validate code
        result = validator.validate(code)
        if result.is_valid:
            # Safe to proceed to sandbox execution
            pass
        else:
            print(f"Blocked: {result.blocked_constructs}")
            print(f"Errors: {result.errors}")

        # Fingerprint for deduplication
        fingerprint = validator.fingerprint(code)
    """

    # Allowed imports - safe standard library modules
    IMPORT_ALLOWLIST: set[str] = {
        # Built-in types (always available)
        "typing",
        # Safe standard library
        "math",
        "json",
        "datetime",
        "re",
        "itertools",
        "functools",
        "collections",
        "decimal",
        "fractions",
        "statistics",
        "string",
        "textwrap",
        "difflib",
        "copy",
        "enum",
        "dataclasses",
        # Testing
        "pytest",
    }

    # Blocked function/attribute names - dangerous constructs
    BLOCKED_NAMES: set[str] = {
        # Code execution
        "eval",
        "exec",
        "compile",
        "__import__",
        # File I/O
        "open",
        "file",
        # System access
        "os",
        "sys",
        "subprocess",
        "shutil",
        # Network
        "socket",
        "urllib",
        "http",
        "requests",
        # Serialization (RCE via __reduce__)
        "pickle",
        "shelve",
        "marshal",
        "dill",
        "cloudpickle",
        # Dynamic imports
        "importlib",
        "imp",
        # Dangerous builtins
        "globals",
        "locals",
        "vars",
        "dir",
        "getattr",
        "setattr",
        "delattr",
        "hasattr",
        "__builtins__",
        "__class__",
        "__bases__",
        "__subclasses__",
        "__mro__",
    }

    def __init__(self) -> None:
        """Initialize the Code Validator service."""
        self.log = log

    def validate(self, code: str) -> ValidationResult:
        """
        Validate code for security issues.

        Parses the code to AST and checks for:
        - Syntax errors
        - Blocked imports (not in IMPORT_ALLOWLIST)
        - Dangerous function names (in BLOCKED_NAMES)
        - Dangerous attribute access (in BLOCKED_NAMES)

        Args:
            code: Python source code to validate.

        Returns:
            ValidationResult with is_valid, errors, warnings, blocked_constructs,
            and imports_used.
        """
        errors: list[str] = []
        warnings: list[str] = []
        blocked_constructs: list[str] = []
        imports_used: set[str] = set()

        self.log.info("Validating code for security issues...")

        # Step 1: Parse code to AST
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            error_msg = f"Syntax error at line {e.lineno}: {e.msg}"
            errors.append(error_msg)
            self.log.warning(f"Code validation failed: {error_msg}")
            return ValidationResult(
                is_valid=False,
                errors=errors,
                warnings=warnings,
                blocked_constructs=blocked_constructs,
                imports_used=imports_used,
            )

        # Step 2: Walk AST and check each node
        for node in ast.walk(tree):
            # Check imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module_name = alias.name.split(".")[0]  # Get top-level module
                    imports_used.add(module_name)
                    is_allowed, name = self._check_import_name(module_name)
                    if not is_allowed:
                        error_msg = f"Blocked import: {name}"
                        errors.append(error_msg)
                        blocked_constructs.append(f"import {name}")
                        self.log.warning(error_msg)

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    module_name = node.module.split(".")[0]  # Get top-level module
                    imports_used.add(module_name)
                    is_allowed, name = self._check_import_name(module_name)
                    if not is_allowed:
                        error_msg = f"Blocked import: {name}"
                        errors.append(error_msg)
                        blocked_constructs.append(f"from {name}")
                        self.log.warning(error_msg)

            # Check Name nodes (function calls, variable references)
            elif isinstance(node, ast.Name):
                is_blocked, name = self._check_name(node)
                if is_blocked:
                    error_msg = f"Blocked name: {name}"
                    errors.append(error_msg)
                    blocked_constructs.append(name)
                    self.log.warning(error_msg)

            # Check Attribute nodes (object.attr access)
            elif isinstance(node, ast.Attribute):
                is_blocked, attr_name = self._check_attribute(node)
                if is_blocked:
                    error_msg = f"Blocked attribute: {attr_name}"
                    errors.append(error_msg)
                    blocked_constructs.append(f".{attr_name}")
                    self.log.warning(error_msg)

        is_valid = len(errors) == 0

        if is_valid:
            self.log.info(f"Code validation passed, imports: {imports_used}")
        else:
            self.log.warning(
                f"Code validation failed with {len(errors)} error(s), "
                f"blocked: {blocked_constructs}"
            )

        return ValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            blocked_constructs=blocked_constructs,
            imports_used=imports_used,
        )

    def validate_structure(self, code: str) -> ValidationResult:
        """Validate that code has the required skill structure.

        Checks:
        - Code parses to valid AST
        - A top-level `def execute(...)` function exists
        - execute() accepts at least one parameter (input_data)
        """
        errors: list[str] = []
        warnings: list[str] = []

        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return ValidationResult(
                is_valid=False,
                errors=[f"Syntax error at line {e.lineno}: {e.msg}"],
            )

        # Find top-level execute function
        execute_funcs = [
            node for node in ast.iter_child_nodes(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "execute"
        ]

        if not execute_funcs:
            errors.append(
                "Missing required `def execute(input_data: dict) -> dict` function"
            )
        else:
            func = execute_funcs[0]
            params = func.args.args
            if len(params) < 1:
                errors.append(
                    "`execute()` must accept at least one parameter (input_data)"
                )

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    def fingerprint(self, code: str) -> str:
        """
        Generate a fingerprint for code deduplication.

        Uses AST normalization to produce stable hashes that ignore
        whitespace and comments. Falls back to raw hash if code has
        syntax errors.

        Args:
            code: Python source code to fingerprint.

        Returns:
            SHA-256 hex digest of normalized code.
        """
        try:
            # Parse to AST
            tree = ast.parse(code)
            # Use ast.unparse() to normalize (removes comments, normalizes whitespace)
            normalized = ast.unparse(tree)
            # Hash the normalized code
            return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        except SyntaxError:
            # Fallback to raw hash if code has syntax errors
            self.log.debug("Fingerprinting with raw hash due to syntax error")
            return hashlib.sha256(code.encode("utf-8")).hexdigest()

    def _check_import_name(self, module_name: str) -> tuple[bool, str]:
        """
        Check if an import is allowed.

        Args:
            module_name: The module name to check.

        Returns:
            Tuple of (is_allowed, module_name).
        """
        # Check if module is in blocklist (takes priority)
        if module_name in self.BLOCKED_NAMES:
            return False, module_name

        # Check if module is in allowlist
        is_allowed = module_name in self.IMPORT_ALLOWLIST
        return is_allowed, module_name

    def _check_name(self, node: ast.Name) -> tuple[bool, str]:
        """
        Check if a Name node references a blocked name.

        Args:
            node: AST Name node.

        Returns:
            Tuple of (is_blocked, name).
        """
        name = node.id
        is_blocked = name in self.BLOCKED_NAMES
        return is_blocked, name

    def _check_attribute(self, node: ast.Attribute) -> tuple[bool, str]:
        """
        Check if an Attribute node accesses a blocked attribute.

        Args:
            node: AST Attribute node.

        Returns:
            Tuple of (is_blocked, attr_name).
        """
        attr_name = node.attr
        is_blocked = attr_name in self.BLOCKED_NAMES
        return is_blocked, attr_name
