"""Middleware for providing filesystem tools to an agent."""
# ruff: noqa: E501

import os
import re
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Any, Literal, NotRequired

if TYPE_CHECKING:
    from langgraph.runtime import Runtime

from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ModelRequest,
    ModelResponse,
)
from langchain.tools import ToolRuntime
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, tool
from langgraph.config import get_config
from langgraph.runtime import Runtime
from langgraph.store.base import BaseStore, Item
from langgraph.types import Command
from typing_extensions import TypedDict

# Re-export type here for backwards compatibility
from deepagents.backends.protocol import BACKEND_TYPES as BACKEND_TYPES
from deepagents.backends.utils import (
    truncate_if_too_long,
)

MEMORIES_PREFIX = "/memories/"
EMPTY_CONTENT_WARNING = "System reminder: File exists but has empty contents"
MAX_LINE_LENGTH = 2000
LINE_NUMBER_WIDTH = 6
DEFAULT_READ_OFFSET = 0
DEFAULT_READ_LIMIT = 500


class FileData(TypedDict):
    """Data structure for storing file contents with metadata."""

    content: list[str]
    """Lines of the file."""

    created_at: str
    """ISO 8601 timestamp of file creation."""

    modified_at: str
    """ISO 8601 timestamp of last modification."""


def _file_data_reducer(left: dict[str, FileData] | None, right: dict[str, FileData | None]) -> dict[str, FileData]:
    """Merge file updates with support for deletions.

    This reducer enables file deletion by treating `None` values in the right
    dictionary as deletion markers. It's designed to work with LangGraph's
    state management where annotated reducers control how state updates merge.

    Args:
        left: Existing files dictionary. May be `None` during initialization.
        right: New files dictionary to merge. Files with `None` values are
            treated as deletion markers and removed from the result.

    Returns:
        Merged dictionary where right overwrites left for matching keys,
        and `None` values in right trigger deletions.

    Example:
        ```python
        existing = {"/file1.txt": FileData(...), "/file2.txt": FileData(...)}
        updates = {"/file2.txt": None, "/file3.txt": FileData(...)}
        result = file_data_reducer(existing, updates)
        # Result: {"/file1.txt": FileData(...), "/file3.txt": FileData(...)}
        ```
    """
    if left is None:
        # Filter out None values when initializing
        return {k: v for k, v in right.items() if v is not None}

    # Merge, filtering out None values (deletions)
    result = {**left}
    for key, value in right.items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = value
    return result


def _validate_path(path: str, *, allowed_prefixes: Sequence[str] | None = None) -> str:
    r"""Validate and normalize file path for security.

    Ensures paths are safe to use by preventing directory traversal attacks
    and enforcing consistent formatting. All paths are normalized to use
    forward slashes and start with a leading slash.

    This function is designed for virtual filesystem paths and rejects
    Windows absolute paths (e.g., C:/..., F:/...) to maintain consistency
    and prevent path format ambiguity.

    Args:
        path: The path to validate and normalize.
        allowed_prefixes: Optional list of allowed path prefixes. If provided,
            the normalized path must start with one of these prefixes.

    Returns:
        Normalized canonical path starting with `/` and using forward slashes.

    Raises:
        ValueError: If path contains traversal sequences (`..` or `~`), is a
            Windows absolute path (e.g., C:/...), or does not start with an
            allowed prefix when `allowed_prefixes` is specified.

    Example:
        ```python
        validate_path("foo/bar")  # Returns: "/foo/bar"
        validate_path("/./foo//bar")  # Returns: "/foo/bar"
        validate_path("../etc/passwd")  # Raises ValueError
        validate_path(r"C:\\Users\\file.txt")  # Raises ValueError
        validate_path("/data/file.txt", allowed_prefixes=["/data/"])  # OK
        validate_path("/etc/file.txt", allowed_prefixes=["/data/"])  # Raises ValueError
        ```
    """
    # Reject paths with traversal attempts
    if ".." in path or path.startswith("~"):
        msg = f"Path traversal not allowed: {path}"
        raise ValueError(msg)

    # Reject Windows absolute paths (e.g., C:\..., D:/...)
    # This maintains consistency in virtual filesystem paths
    if re.match(r"^[a-zA-Z]:", path):
        msg = f"Windows absolute paths are not supported: {path}. Please use virtual paths starting with / (e.g., /workspace/file.txt)"
        raise ValueError(msg)

    normalized = os.path.normpath(path)

    # Convert to forward slashes for consistency
    normalized = normalized.replace("\\", "/")

    # Ensure path starts with /
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"

    # Check allowed prefixes if specified
    if allowed_prefixes is not None and not any(normalized.startswith(prefix) for prefix in allowed_prefixes):
        msg = f"Path must start with one of {allowed_prefixes}: {path}"
        raise ValueError(msg)

    return normalized


def _format_content_with_line_numbers(
    content: str | list[str],
    *,
    format_style: Literal["pipe", "tab"] = "pipe",
    start_line: int = 1,
) -> str:
    r"""Format file content with line numbers for display.

    Converts file content to a numbered format similar to `cat -n` output,
    with support for two different formatting styles.

    Args:
        content: File content as a string or list of lines.
        format_style: Format style for line numbers:
            - `"pipe"`: Compact format like `"1|content"`
            - `"tab"`: Right-aligned format like `"     1\tcontent"` (lines truncated at 2000 chars)
        start_line: Starting line number (default: 1).

    Returns:
        Formatted content with line numbers prepended to each line.

    Example:
        ```python
        content = "Hello\nWorld"
        format_content_with_line_numbers(content, format_style="pipe")
        # Returns: "1|Hello\n2|World"

        format_content_with_line_numbers(content, format_style="tab", start_line=10)
        # Returns: "    10\tHello\n    11\tWorld"
        ```
    """
    if isinstance(content, str):
        lines = content.split("\n")
        # Remove trailing empty line from split
        if lines and lines[-1] == "":
            lines = lines[:-1]
    else:
        lines = content

    if format_style == "pipe":
        return "\n".join(f"{i + start_line}|{line}" for i, line in enumerate(lines))

    # Tab format with defined width and line truncation
    return "\n".join(f"{i + start_line:{LINE_NUMBER_WIDTH}d}\t{line[:MAX_LINE_LENGTH]}" for i, line in enumerate(lines))


def _create_file_data(
    content: str | list[str],
    *,
    created_at: str | None = None,
) -> FileData:
    r"""Create a FileData object with automatic timestamp generation.

    Args:
        content: File content as a string or list of lines.
        created_at: Optional creation timestamp in ISO 8601 format.
            If `None`, uses the current UTC time.

    Returns:
        FileData object with content and timestamps.

    Example:
        ```python
        file_data = create_file_data("Hello\nWorld")
        # Returns: {"content": ["Hello", "World"], "created_at": "2024-...",
        #           "modified_at": "2024-..."}
        ```
    """
    lines = content.split("\n") if isinstance(content, str) else content
    now = datetime.now(UTC).isoformat()

    return {
        "content": lines,
        "created_at": created_at or now,
        "modified_at": now,
    }


def _update_file_data(
    file_data: FileData,
    content: str | list[str],
) -> FileData:
    """Update FileData with new content while preserving creation timestamp.

    Args:
        file_data: Existing FileData object to update.
        content: New file content as a string or list of lines.

    Returns:
        Updated FileData object with new content and updated `modified_at`
        timestamp. The `created_at` timestamp is preserved from the original.

    Example:
        ```python
        original = create_file_data("Hello")
        updated = update_file_data(original, "Hello World")
        # updated["created_at"] == original["created_at"]
        # updated["modified_at"] > original["modified_at"]
        ```
    """
    lines = content.split("\n") if isinstance(content, str) else content
    now = datetime.now(UTC).isoformat()

    return {
        "content": lines,
        "created_at": file_data["created_at"],
        "modified_at": now,
    }


def _file_data_to_string(file_data: FileData) -> str:
    r"""Convert FileData to plain string content.

    Joins the lines stored in FileData with newline characters to produce
    a single string representation of the file content.

    Args:
        file_data: FileData object containing lines of content.

    Returns:
        File content as a single string with lines joined by newlines.

    Example:
        ```python
        file_data = {
            "content": ["Hello", "World"],
            "created_at": "...",
            "modified_at": "...",
        }
        file_data_to_string(file_data)  # Returns: "Hello\nWorld"
        ```
    """
    return "\n".join(file_data["content"])


def _check_empty_content(content: str) -> str | None:
    """Check if file content is empty and return a warning message.

    Args:
        content: File content to check.

    Returns:
        Warning message string if content is empty or contains only whitespace,
        `None` otherwise.

    Example:
        ```python
        check_empty_content("")  # Returns: "System reminder: File exists but has empty contents"
        check_empty_content("   ")  # Returns: "System reminder: File exists but has empty contents"
        check_empty_content("Hello")  # Returns: None
        ```
    """
    if not content or content.strip() == "":
        return EMPTY_CONTENT_WARNING
    return None


def _has_memories_prefix(file_path: str) -> bool:
    """Check if a file path is in the longterm memory filesystem.

    Longterm memory files are distinguished by the `/memories/` path prefix.

    Args:
        file_path: File path to check.

    Returns:
        `True` if the file path starts with `/memories/`, `False` otherwise.

    Example:
        ```python
        has_memories_prefix("/memories/notes.txt")  # Returns: True
        has_memories_prefix("/temp/file.txt")  # Returns: False
        ```
    """
    return file_path.startswith(MEMORIES_PREFIX)


def _append_memories_prefix(file_path: str) -> str:
    """Add the longterm memory prefix to a file path.

    Args:
        file_path: File path to prefix.

    Returns:
        File path with `/memories` prepended.

    Example:
        ```python
        append_memories_prefix("/notes.txt")  # Returns: "/memories/notes.txt"
        ```
    """
    return f"/memories{file_path}"


def _strip_memories_prefix(file_path: str) -> str:
    """Remove the longterm memory prefix from a file path.

    Args:
        file_path: File path potentially containing the memories prefix.

    Returns:
        File path with `/memories` removed if present at the start.

    Example:
        ```python
        strip_memories_prefix("/memories/notes.txt")  # Returns: "/notes.txt"
        strip_memories_prefix("/notes.txt")  # Returns: "/notes.txt"
        ```
    """
    if file_path.startswith(MEMORIES_PREFIX):
        return file_path[len(MEMORIES_PREFIX) - 1 :]  # Keep the leading slash
    return file_path


class FilesystemState(AgentState):
    """State for the filesystem middleware."""

    files: Annotated[NotRequired[dict[str, FileData]], _file_data_reducer]
    """Files in the filesystem."""


LIST_FILES_TOOL_DESCRIPTION = """Lists all files in the filesystem, optionally filtering by directory.

Usage:
- The list_files tool will return a list of all files in the filesystem.
- You can optionally provide a path parameter to list files in a specific directory.
- This is very useful for exploring the file system and finding the right file to read or edit.
- You should almost ALWAYS use this tool before using the Read or Edit tools."""
LIST_FILES_TOOL_DESCRIPTION_LONGTERM_SUPPLEMENT = f"\n- Files from the longterm filesystem will be prefixed with the {MEMORIES_PREFIX} path."

READ_FILE_TOOL_DESCRIPTION = """Reads a file from the filesystem. You can access any file directly by using this tool.
Assume this tool is able to read all files on the machine. If the User provides a path to a file assume that path is valid. It is okay to read a file that does not exist; an error will be returned.

Usage:
- The file_path parameter must be an absolute path, not a relative path
- By default, it reads up to 2000 lines starting from the beginning of the file
- You can optionally specify a line offset and limit (especially handy for long files), but it's recommended to read the whole file by not providing these parameters
- Any lines longer than 2000 characters will be truncated
- Results are returned using cat -n format, with line numbers starting at 1
- You have the capability to call multiple tools in a single response. It is always better to speculatively read multiple files as a batch that are potentially useful.
- If you read a file that exists but has empty contents you will receive a system reminder warning in place of file contents.
- You should ALWAYS make sure a file has been read before editing it."""
READ_FILE_TOOL_DESCRIPTION_LONGTERM_SUPPLEMENT = f"\n- file_paths prefixed with the {MEMORIES_PREFIX} path will be read from the longterm filesystem."

EDIT_FILE_TOOL_DESCRIPTION = """Performs exact string replacements in files.

Usage:
- You must use your `Read` tool at least once in the conversation before editing. This tool will error if you attempt an edit without reading the file.
- When editing text from Read tool output, ensure you preserve the exact indentation (tabs/spaces) as it appears AFTER the line number prefix. The line number prefix format is: spaces + line number + tab. Everything after that tab is the actual file content to match. Never include any part of the line number prefix in the old_string or new_string.
- ALWAYS prefer editing existing files. NEVER write new files unless explicitly required.
- Only use emojis if the user explicitly requests it. Avoid adding emojis to files unless asked.
- The edit will FAIL if `old_string` is not unique in the file. Either provide a larger string with more surrounding context to make it unique or use `replace_all` to change every instance of `old_string`.
- Use `replace_all` for replacing and renaming strings across the file. This parameter is useful if you want to rename a variable for instance."""
EDIT_FILE_TOOL_DESCRIPTION_LONGTERM_SUPPLEMENT = (
    f"\n- You can edit files in the longterm filesystem by prefixing the filename with the {MEMORIES_PREFIX} path."
)

WRITE_FILE_TOOL_DESCRIPTION = """Writes to a new file in the filesystem.

Usage:
- The file_path parameter must be an absolute path, not a relative path
- The content parameter must be a string
- The write_file tool will create the a new file.
- Prefer to edit existing files over creating new ones when possible.
- file_paths prefixed with the /memories/ path will be written to the longterm filesystem."""
WRITE_FILE_TOOL_DESCRIPTION_LONGTERM_SUPPLEMENT = (
    f"\n- file_paths prefixed with the {MEMORIES_PREFIX} path will be written to the longterm filesystem."
)

GLOB_TOOL_DESCRIPTION = """Find files matching a glob pattern.

Usage:
- The glob tool finds files by matching patterns with wildcards
- Supports standard glob patterns: `*` (any characters), `**` (any directories), `?` (single character)
- Patterns can be absolute (starting with `/`) or relative
- Returns a list of absolute file paths that match the pattern

Examples:
- `**/*.py` - Find all Python files
- `*.txt` - Find all text files in root
- `/subdir/**/*.md` - Find all markdown files under /subdir"""

GREP_TOOL_DESCRIPTION = """Search for a pattern in files.

Usage:
- The grep tool searches for text patterns across files
- The pattern parameter is the text to search for (literal string, not regex)
- The path parameter filters which directory to search in (default is the current working directory)
- The glob parameter accepts a glob pattern to filter which files to search (e.g., `*.py`)
- The output_mode parameter controls the output format:
  - `files_with_matches`: List only file paths containing matches (default)
  - `content`: Show matching lines with file path and line numbers
  - `count`: Show count of matches per file

Examples:
- Search all files: `grep(pattern="TODO")`
- Search Python files only: `grep(pattern="import", glob="*.py")`
- Show matching lines: `grep(pattern="error", output_mode="content")`"""

EXECUTE_TOOL_DESCRIPTION = """Executes a given command in the sandbox environment with proper handling and security measures.

Before executing the command, please follow these steps:

1. Directory Verification:
   - If the command will create new directories or files, first use the ls tool to verify the parent directory exists and is the correct location
   - For example, before running "mkdir foo/bar", first use ls to check that "foo" exists and is the intended parent directory

2. Command Execution:
   - Always quote file paths that contain spaces with double quotes (e.g., cd "path with spaces/file.txt")
   - Examples of proper quoting:
     - cd "/Users/name/My Documents" (correct)
     - cd /Users/name/My Documents (incorrect - will fail)
     - python "/path/with spaces/script.py" (correct)
     - python /path/with spaces/script.py (incorrect - will fail)
   - After ensuring proper quoting, execute the command
   - Capture the output of the command

Usage notes:
  - The command parameter is required
  - Commands run in an isolated sandbox environment
  - Returns combined stdout/stderr output with exit code
  - If the output is very large, it may be truncated
  - VERY IMPORTANT: You MUST avoid using search commands like find and grep. Instead use the grep, glob tools to search. You MUST avoid read tools like cat, head, tail, and use read_file to read files.
  - When issuing multiple commands, use the ';' or '&&' operator to separate them. DO NOT use newlines (newlines are ok in quoted strings)
    - Use '&&' when commands depend on each other (e.g., "mkdir dir && cd dir")
    - Use ';' only when you need to run commands sequentially but don't care if earlier commands fail
  - Try to maintain your current working directory throughout the session by using absolute paths and avoiding usage of cd

Examples:
  Good examples:
    - execute(command="pytest /foo/bar/tests")
    - execute(command="python /path/to/script.py")
    - execute(command="npm install && npm test")

  Bad examples (avoid these):
    - execute(command="cd /foo/bar && pytest tests")  # Use absolute path instead
    - execute(command="cat file.txt")  # Use read_file tool instead
    - execute(command="find . -name '*.py'")  # Use glob tool instead
    - execute(command="grep -r 'pattern' .")  # Use grep tool instead

Note: This tool is only available if the backend supports execution (SandboxBackendProtocol).
If execution is not supported, the tool will return an error message."""

FILESYSTEM_SYSTEM_PROMPT = """## Filesystem Tools `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`

You have access to a filesystem which you can interact with using these tools.
All file paths must start with a /.

- ls: list all files in the filesystem
- read_file: read a file from the filesystem
- write_file: write to a file in the filesystem
- edit_file: edit a file in the filesystem"""
FILESYSTEM_SYSTEM_PROMPT_LONGTERM_SUPPLEMENT = f"""

You also have access to a longterm filesystem in which you can store files that you want to keep around for longer than the current conversation.
In order to interact with the longterm filesystem, you can use those same tools, but filenames must be prefixed with the {MEMORIES_PREFIX} path.
Remember, to interact with the longterm filesystem, you must prefix the filename with the {MEMORIES_PREFIX} path."""

EXECUTION_SYSTEM_PROMPT = """## Execute Tool `execute`

You have access to an `execute` tool for running shell commands in a sandboxed environment.
Use this tool to run commands, scripts, tests, builds, and other shell operations.

- execute: run a shell command in the sandbox (returns output and exit code)"""


def _get_namespace() -> tuple[str] | tuple[str, str]:
    """Get the namespace for longterm filesystem storage.

    Returns a tuple for organizing files in the store. If an assistant_id is available
    in the config metadata, returns a 2-tuple of (assistant_id, "filesystem") to provide
    per-assistant isolation. Otherwise, returns a 1-tuple of ("filesystem",) for shared storage.

    Returns:
        Namespace tuple for store operations, either `(assistant_id, "filesystem")` or `("filesystem",)`.
    """
    namespace = "filesystem"
    config = get_config()
    if config is None:
        return (namespace,)
    assistant_id = config.get("metadata", {}).get("assistant_id")
    if assistant_id is None:
        return (namespace,)
    return (assistant_id, "filesystem")


def _get_store(runtime: ToolRuntime[None, FilesystemState]) -> BaseStore:
    """Get the store from the runtime, raising an error if unavailable.

    Args:
        runtime: The LangGraph runtime containing the store.

    Returns:
        The BaseStore instance for longterm file storage.

    Raises:
        ValueError: If longterm memory is enabled but no store is available in runtime.
    """
    if runtime.store is None:
        msg = "Longterm memory is enabled, but no store is available"
        raise ValueError(msg)
    return runtime.store


def _convert_store_item_to_file_data(store_item: Item) -> FileData:
    """Convert a store Item to FileData format.

    Args:
        store_item: The store Item containing file data.

    Returns:
        FileData with content, created_at, and modified_at fields.

    Raises:
        ValueError: If required fields are missing or have incorrect types.
    """
    if "content" not in store_item.value or not isinstance(store_item.value["content"], list):
        msg = f"Store item does not contain valid content field. Got: {store_item.value.keys()}"
        raise ValueError(msg)
    if "created_at" not in store_item.value or not isinstance(store_item.value["created_at"], str):
        msg = f"Store item does not contain valid created_at field. Got: {store_item.value.keys()}"
        raise ValueError(msg)
    if "modified_at" not in store_item.value or not isinstance(store_item.value["modified_at"], str):
        msg = f"Store item does not contain valid modified_at field. Got: {store_item.value.keys()}"
        raise ValueError(msg)
    return FileData(
        content=store_item.value["content"],
        created_at=store_item.value["created_at"],
        modified_at=store_item.value["modified_at"],
    )


def _convert_file_data_to_store_item(file_data: FileData) -> dict[str, Any]:
    """Convert FileData to a dict suitable for store.put().

    Args:
        file_data: The FileData to convert.

    Returns:
        Dictionary with content, created_at, and modified_at fields.
    """
    return {
        "content": file_data["content"],
        "created_at": file_data["created_at"],
        "modified_at": file_data["modified_at"],
    }


def _get_file_data_from_state(state: FilesystemState, file_path: str) -> FileData:
    """Retrieve file data from the agent's state.

    Args:
        state: The current filesystem state.
        file_path: The path of the file to retrieve.

    Returns:
        The FileData for the requested file.

    Raises:
        ValueError: If the file is not found in state.
    """
    mock_filesystem = state.get("files", {})
    if file_path not in mock_filesystem:
        msg = f"File '{file_path}' not found"
        raise ValueError(msg)
    return mock_filesystem[file_path]


# ---------------------------------------------------------------------------
# Backend helpers
# ---------------------------------------------------------------------------


def _get_backend(
    backend: "BACKEND_TYPES | None",  # noqa: F821
    runtime: "ToolRuntime[Any, Any]",
) -> "BackendProtocol":
    """Resolve a backend from a factory/instance or fall back to StateBackend.

    Args:
        backend: Either a BackendProtocol instance, a callable factory
            ``(runtime) -> BackendProtocol``, or ``None`` to use StateBackend.
        runtime: The current tool runtime providing state and store.

    Returns:
        A concrete BackendProtocol instance ready for use.
    """
    from deepagents.backends.state import StateBackend

    if backend is None:
        return StateBackend(runtime)
    if callable(backend):
        return backend(runtime)
    return backend


def _supports_execution(backend: Any) -> bool:
    """Return True if *backend* implements SandboxBackendProtocol.

    For CompositeBackend, checks whether the *default* backend supports
    execution, since execution is not path-routed.

    Args:
        backend: Any backend object to check.

    Returns:
        True if the backend (or its default, for CompositeBackend) has an
        ``execute`` method consistent with SandboxBackendProtocol.
    """
    from deepagents.backends.protocol import SandboxBackendProtocol

    # CompositeBackend delegates execute() to its default backend
    default = getattr(backend, "default", None)
    if default is not None:
        return isinstance(default, SandboxBackendProtocol)
    return isinstance(backend, SandboxBackendProtocol)


# ---------------------------------------------------------------------------
# Tool generators — each generator captures *backend* in its closure so all
# generated tools resolve the backend at call-time via _get_backend().
# ---------------------------------------------------------------------------


def _ls_tool_generator(
    custom_description: str | None = None,
    *,
    long_term_memory: bool,  # noqa: ARG001
    backend: "BACKEND_TYPES | None" = None,
) -> BaseTool:
    """Generate the ls (list files) tool.

    Args:
        custom_description: Optional custom description for the tool.
        long_term_memory: Unused; retained for call-site compatibility.
        backend: Optional backend instance or factory.

    Returns:
        Configured ls tool that lists files from the resolved backend.
    """
    tool_description = custom_description or LIST_FILES_TOOL_DESCRIPTION

    @tool(description=tool_description)
    def ls(runtime: ToolRuntime[None, FilesystemState], path: str) -> str:
        resolved_backend = _get_backend(backend, runtime)
        validated_path = _validate_path(path)
        infos = resolved_backend.ls_info(validated_path)
        paths = [fi.get("path", "") for fi in infos]
        result = truncate_if_too_long(paths)
        return str(result)

    return ls


def _read_file_tool_generator(
    custom_description: str | None = None,
    *,
    long_term_memory: bool,  # noqa: ARG001
    backend: "BACKEND_TYPES | None" = None,
) -> BaseTool:
    """Generate the read_file tool.

    Args:
        custom_description: Optional custom description for the tool.
        long_term_memory: Unused; retained for call-site compatibility.
        backend: Optional backend instance or factory.

    Returns:
        Configured read_file tool that reads files from the resolved backend.
    """
    tool_description = custom_description or READ_FILE_TOOL_DESCRIPTION

    @tool(description=tool_description)
    def read_file(
        file_path: str,
        runtime: ToolRuntime[None, FilesystemState],
        offset: int = DEFAULT_READ_OFFSET,
        limit: int = DEFAULT_READ_LIMIT,
    ) -> str:
        file_path = _validate_path(file_path)
        resolved_backend = _get_backend(backend, runtime)
        return resolved_backend.read(file_path, offset=offset, limit=limit)

    return read_file


def _write_file_tool_generator(
    custom_description: str | None = None,
    *,
    long_term_memory: bool,  # noqa: ARG001
    backend: "BACKEND_TYPES | None" = None,
) -> BaseTool:
    """Generate the write_file tool.

    Args:
        custom_description: Optional custom description for the tool.
        long_term_memory: Unused; retained for call-site compatibility.
        backend: Optional backend instance or factory.

    Returns:
        Configured write_file tool that creates new files via the resolved backend.
    """
    tool_description = custom_description or WRITE_FILE_TOOL_DESCRIPTION

    @tool(description=tool_description)
    def write_file(
        file_path: str,
        content: str,
        runtime: ToolRuntime[None, FilesystemState],
    ) -> "Command | str":
        file_path = _validate_path(file_path)
        if not runtime.tool_call_id:
            raise ValueError("Tool call ID is required for write_file invocation")
        resolved_backend = _get_backend(backend, runtime)
        result = resolved_backend.write(file_path, content)
        if result.error:
            return result.error
        if result.files_update:
            return Command(
                update={
                    "files": result.files_update,
                    "messages": [ToolMessage(f"Updated file {file_path}", tool_call_id=runtime.tool_call_id)],
                }
            )
        return f"Updated file {file_path}"

    return write_file


def _edit_file_tool_generator(
    custom_description: str | None = None,
    *,
    long_term_memory: bool,  # noqa: ARG001
    backend: "BACKEND_TYPES | None" = None,
) -> BaseTool:
    """Generate the edit_file tool.

    Args:
        custom_description: Optional custom description for the tool.
        long_term_memory: Unused; retained for call-site compatibility.
        backend: Optional backend instance or factory.

    Returns:
        Configured edit_file tool that performs string replacements via the resolved backend.
    """
    tool_description = custom_description or EDIT_FILE_TOOL_DESCRIPTION

    @tool(description=tool_description)
    def edit_file(
        file_path: str,
        old_string: str,
        new_string: str,
        runtime: ToolRuntime[None, FilesystemState],
        *,
        replace_all: bool = False,
    ) -> "Command | str":
        file_path = _validate_path(file_path)
        resolved_backend = _get_backend(backend, runtime)
        result = resolved_backend.edit(file_path, old_string, new_string, replace_all=replace_all)
        if result.error:
            return result.error
        full_msg = f"Successfully replaced {result.occurrences} instance(s) of the string in '{file_path}'"
        if result.files_update:
            return Command(
                update={
                    "files": result.files_update,
                    "messages": [ToolMessage(full_msg, tool_call_id=runtime.tool_call_id)],
                }
            )
        return full_msg

    return edit_file


def _glob_tool_generator(
    custom_description: str | None = None,
    *,
    long_term_memory: bool,  # noqa: ARG001
    backend: "BACKEND_TYPES | None" = None,
) -> BaseTool:
    """Generate the glob tool.

    Args:
        custom_description: Optional custom description for the tool.
        long_term_memory: Unused; retained for call-site compatibility.
        backend: Optional backend instance or factory.

    Returns:
        Configured glob tool that finds files matching a pattern via the resolved backend.
    """
    tool_description = custom_description or GLOB_TOOL_DESCRIPTION

    @tool(description=tool_description)
    def glob(
        pattern: str,
        runtime: ToolRuntime[None, FilesystemState],
        path: str = "/",
    ) -> str:
        validated_path = _validate_path(path)
        resolved_backend = _get_backend(backend, runtime)
        infos = resolved_backend.glob_info(pattern, validated_path)
        paths = [fi.get("path", "") for fi in infos]
        result = truncate_if_too_long(paths)
        return str(result)

    return glob


def _grep_tool_generator(
    custom_description: str | None = None,
    *,
    long_term_memory: bool,  # noqa: ARG001
    backend: "BACKEND_TYPES | None" = None,
) -> BaseTool:
    """Generate the grep tool.

    Args:
        custom_description: Optional custom description for the tool.
        long_term_memory: Unused; retained for call-site compatibility.
        backend: Optional backend instance or factory.

    Returns:
        Configured grep tool that searches file contents via the resolved backend.
    """
    from deepagents.backends.utils import format_grep_matches

    tool_description = custom_description or GREP_TOOL_DESCRIPTION

    @tool(description=tool_description)
    def grep(
        pattern: str,
        runtime: ToolRuntime[None, FilesystemState],
        path: str = "/",
        glob: str | None = None,
        output_mode: Literal["files_with_matches", "content", "count"] = "files_with_matches",
    ) -> str:
        validated_path = _validate_path(path)
        resolved_backend = _get_backend(backend, runtime)
        raw = resolved_backend.grep_raw(pattern, validated_path, glob)
        if isinstance(raw, str):
            # Error or "No matches found" string from backend
            return raw
        if not raw:
            return "No matches found"
        result = format_grep_matches(raw, output_mode)
        return truncate_if_too_long(result)  # type: ignore[return-value]

    return grep


def _execute_tool_generator(
    custom_description: str | None = None,
    *,
    long_term_memory: bool,  # noqa: ARG001
    backend: "BACKEND_TYPES | None" = None,
) -> BaseTool:
    """Generate the execute tool.

    The generated tool always checks at runtime whether the resolved backend
    supports execution. If it does not, it returns a friendly error message
    rather than raising an exception.

    Args:
        custom_description: Optional custom description for the tool.
        long_term_memory: Unused; retained for call-site compatibility.
        backend: Optional backend instance or factory.

    Returns:
        Configured execute tool.
    """
    tool_description = custom_description or EXECUTE_TOOL_DESCRIPTION

    @tool(description=tool_description)
    def execute(
        command: str,
        runtime: ToolRuntime[None, FilesystemState],
    ) -> str:
        resolved_backend = _get_backend(backend, runtime)
        if not _supports_execution(resolved_backend):
            return (
                "Error: Execution not available. The current backend does not support command execution. "
                "Please configure a SandboxBackendProtocol backend to enable the execute tool."
            )
        response = resolved_backend.execute(command)  # type: ignore[attr-defined]
        status = "succeeded" if response.exit_code == 0 else "failed"
        truncated_note = " (output truncated)" if response.truncated else ""
        return f"Command {status} with exit code {response.exit_code}{truncated_note}:\n{response.output}"

    return execute


TOOL_GENERATORS: dict[str, Any] = {
    "ls": _ls_tool_generator,
    "read_file": _read_file_tool_generator,
    "write_file": _write_file_tool_generator,
    "edit_file": _edit_file_tool_generator,
    "glob": _glob_tool_generator,
    "grep": _grep_tool_generator,
    "execute": _execute_tool_generator,
}


def _get_filesystem_tools(
    custom_tool_descriptions: dict[str, str] | None = None,
    *,
    long_term_memory: bool,
    backend: "BACKEND_TYPES | None" = None,
) -> list[BaseTool]:
    """Get all filesystem tools with the given configuration.

    Args:
        custom_tool_descriptions: Optional custom descriptions for tools.
        long_term_memory: Passed through to each tool generator (unused by
            backend-aware generators but kept for API stability).
        backend: Optional backend instance or factory propagated to each tool.

    Returns:
        List of configured filesystem tools (ls, read_file, write_file,
        edit_file, glob, grep, execute).
    """
    if custom_tool_descriptions is None:
        custom_tool_descriptions = {}
    tools = []
    for tool_name, tool_generator in TOOL_GENERATORS.items():
        generated = tool_generator(
            custom_tool_descriptions.get(tool_name),
            long_term_memory=long_term_memory,
            backend=backend,
        )
        tools.append(generated)
    return tools


TOO_LARGE_TOOL_MSG = """Tool result too large, the result of this tool call {tool_call_id} was saved in the filesystem at this path: {file_path}
You can read the result from the filesystem by using the read_file tool, but make sure to only read part of the result at a time.
You can do this by specifying an offset and limit in the read_file tool call.
For example, to read the first 100 lines, you can use the read_file tool with offset=0 and limit=100.

Here are the first 10 lines of the result:
{content_sample}
"""


class FilesystemMiddleware(AgentMiddleware):
    """Middleware for providing filesystem and optional execution tools to an agent.

    This middleware adds seven tools to the agent: ls, read_file, write_file,
    edit_file, glob, grep, and execute.

    All file operations are routed through a pluggable *backend*. If no
    backend is supplied, a ``StateBackend`` is used (files stored ephemerally
    in LangGraph state). Pass a ``BackendFactory`` (callable) or a
    ``BackendProtocol`` instance to customise storage.

    The ``execute`` tool is always registered. At runtime it checks whether
    the resolved backend implements ``SandboxBackendProtocol``. If it does
    not, a friendly error message is returned rather than raising an exception.
    The execute tool is *filtered out* of the model's tool list (via
    ``wrap_model_call``) when the backend does not support execution, so the
    model will never try to call it.

    Args:
        backend: Optional backend instance or callable factory
            ``(runtime) -> BackendProtocol``. Defaults to ``StateBackend``.
        system_prompt: Optional custom system prompt override.
        custom_tool_descriptions: Optional custom tool descriptions override.
        tool_token_limit_before_evict: Token limit before evicting a large
            tool result to the filesystem. ``None`` disables eviction.

    Raises:
        ValueError: (at tool runtime) If longterm memory is enabled but no
            store is available.

    Example:
        ```python
        from deepagents.middleware.filesystem import FilesystemMiddleware
        from deepagents.backends import StateBackend, CompositeBackend, StoreBackend
        from langchain.agents import create_agent

        # Default StateBackend
        agent = create_agent(middleware=[FilesystemMiddleware()])

        # Custom backend factory
        def make_backend(rt):
            return CompositeBackend(
                default=StateBackend(rt),
                routes={"/memories/": StoreBackend(rt)},
            )
        agent = create_agent(middleware=[FilesystemMiddleware(backend=make_backend)])
        ```
    """

    state_schema = FilesystemState

    def __init__(
        self,
        *,
        backend: "BACKEND_TYPES | None" = None,
        long_term_memory: bool = False,
        system_prompt: str | None = None,
        custom_tool_descriptions: dict[str, str] | None = None,
        tool_token_limit_before_evict: int | None = 20000,
    ) -> None:
        """Initialize the filesystem middleware.

        Args:
            backend: Optional backend instance or factory. When ``None``
                (default) a ``StateBackend`` is used at each tool call.
                Pass a callable ``(ToolRuntime) -> BackendProtocol`` to
                create backends lazily from each tool invocation's runtime.
            long_term_memory: Deprecated flag kept for API compatibility.
                Prefer supplying a composite backend with a StoreBackend route.
            system_prompt: Optional custom system prompt override.
            custom_tool_descriptions: Optional custom tool descriptions override.
            tool_token_limit_before_evict: Optional token limit before
                evicting a tool result to the filesystem.
        """
        # Normalise: if no backend supplied, produce a factory that creates StateBackend
        if backend is None:
            from deepagents.backends.state import StateBackend as _StateBackend

            self.backend: "BACKEND_TYPES" = lambda rt: _StateBackend(rt)
        else:
            self.backend = backend

        self.long_term_memory = long_term_memory
        self.tool_token_limit_before_evict = tool_token_limit_before_evict
        self._custom_system_prompt: str | None = system_prompt

        self.tools = _get_filesystem_tools(
            custom_tool_descriptions,
            long_term_memory=long_term_memory,
            backend=self.backend,
        )

    def before_agent(self, state: AgentState, runtime: Runtime[Any]) -> dict[str, Any] | None:  # noqa: ARG002
        """No-op pre-agent hook (retained for AgentMiddleware interface).

        Args:
            state: The state of the agent.
            runtime: The LangGraph runtime.

        Returns:
            None (no state modifications).
        """
        return None

    def _get_backend(self, runtime: Any) -> Any:
        """Resolve the middleware's backend using the given runtime.

        Args:
            runtime: Any runtime that can be passed to the backend factory.

        Returns:
            A concrete BackendProtocol instance.
        """
        return _get_backend(self.backend, runtime)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Update the system prompt and filter tools based on backend capabilities.

        Args:
            request: The model request being processed.
            handler: The handler function to call with the modified request.

        Returns:
            The model response from the handler.
        """
        # Check if execute tool is present and if backend supports it
        has_execute_tool = any(
            (tool.name if hasattr(tool, "name") else tool.get("name")) == "execute"
            for tool in request.tools
        )

        backend_supports_execution = False
        if has_execute_tool:
            # Resolve backend to check execution support
            resolved = self._get_backend(request.runtime)
            backend_supports_execution = _supports_execution(resolved)

            # If execute tool exists but backend doesn't support it, filter it out
            if not backend_supports_execution:
                filtered_tools = [
                    tool
                    for tool in request.tools
                    if (tool.name if hasattr(tool, "name") else tool.get("name")) != "execute"
                ]
                request = request.override(tools=filtered_tools)
                has_execute_tool = False

        # Use custom system prompt if provided, otherwise generate dynamically
        if self._custom_system_prompt is not None:
            system_prompt = self._custom_system_prompt
        else:
            prompt_parts = [FILESYSTEM_SYSTEM_PROMPT]
            if has_execute_tool and backend_supports_execution:
                prompt_parts.append(EXECUTION_SYSTEM_PROMPT)
            system_prompt = "\n\n".join(prompt_parts)

        if system_prompt:
            request = request.override(
                system_prompt=request.system_prompt + "\n\n" + system_prompt
                if request.system_prompt
                else system_prompt
            )

        return handler(request)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """(async) Update the system prompt and filter tools based on backend capabilities.

        Args:
            request: The model request being processed.
            handler: The handler function to call with the modified request.

        Returns:
            The model response from the handler.
        """
        has_execute_tool = any(
            (tool.name if hasattr(tool, "name") else tool.get("name")) == "execute"
            for tool in request.tools
        )

        backend_supports_execution = False
        if has_execute_tool:
            resolved = self._get_backend(request.runtime)
            backend_supports_execution = _supports_execution(resolved)

            if not backend_supports_execution:
                filtered_tools = [
                    tool
                    for tool in request.tools
                    if (tool.name if hasattr(tool, "name") else tool.get("name")) != "execute"
                ]
                request = request.override(tools=filtered_tools)
                has_execute_tool = False

        if self._custom_system_prompt is not None:
            system_prompt = self._custom_system_prompt
        else:
            prompt_parts = [FILESYSTEM_SYSTEM_PROMPT]
            if has_execute_tool and backend_supports_execution:
                prompt_parts.append(EXECUTION_SYSTEM_PROMPT)
            system_prompt = "\n\n".join(prompt_parts)

        if system_prompt:
            request = request.override(
                system_prompt=request.system_prompt + "\n\n" + system_prompt
                if request.system_prompt
                else system_prompt
            )

        return await handler(request)

    def _intercept_large_tool_result(
        self,
        tool_result: ToolMessage | Command,
        runtime: ToolRuntime | None = None,
    ) -> ToolMessage | Command:
        """Intercept large tool results and evict them to the filesystem.

        When the result exceeds ``tool_token_limit_before_evict`` tokens, the
        content is saved via the resolved backend. If the backend writes to
        state (``files_update`` is set), a ``Command`` is returned to update
        LangGraph state. If the backend is external (``files_update`` is
        ``None``), a ``ToolMessage`` referencing the saved path is returned
        instead.

        Args:
            tool_result: The tool result to potentially intercept.
            runtime: Optional ToolRuntime used to resolve the backend for
                routing the evicted content.

        Returns:
            The original result if small enough, or a replacement referencing
            the saved file path.
        """
        from deepagents.backends.utils import sanitize_tool_call_id

        def _evict(content: str, tool_call_id: str) -> tuple[str, ToolMessage, dict[str, Any] | None]:
            """Write *content* to the backend and return (file_path, replacement_msg, files_update_or_None)."""
            safe_id = sanitize_tool_call_id(tool_call_id)
            file_path = f"/large_tool_results/{safe_id}"
            file_data = _create_file_data(content)
            files_update: dict[str, Any] | None = {file_path: file_data}

            if runtime is not None:
                resolved_backend = _get_backend(self.backend, runtime)
                write_result = resolved_backend.write(file_path, content)
                if write_result.error is None:
                    # If write succeeded and backend is external (no files_update), use store path
                    if write_result.files_update is None:
                        files_update = None
                    else:
                        files_update = write_result.files_update

            replacement = ToolMessage(
                TOO_LARGE_TOOL_MSG.format(
                    tool_call_id=tool_call_id,
                    file_path=file_path,
                    content_sample=_format_content_with_line_numbers(
                        [line[:1000] for line in file_data["content"][:10]], format_style="tab", start_line=1
                    ),
                ),
                tool_call_id=tool_call_id,
            )
            return file_path, replacement, files_update

        def _is_too_large(content: str) -> bool:
            return bool(
                self.tool_token_limit_before_evict
                and len(content) > 4 * self.tool_token_limit_before_evict
            )

        if isinstance(tool_result, ToolMessage) and isinstance(tool_result.content, str):
            content = tool_result.content
            if _is_too_large(content):
                file_path, replacement, files_update = _evict(content, tool_result.tool_call_id)
                if files_update is None:
                    # External backend — no LangGraph state update needed
                    return replacement
                return Command(update={"messages": [replacement], "files": files_update})

        elif isinstance(tool_result, Command):
            update = tool_result.update
            if update is None:
                return tool_result
            message_updates = update.get("messages", [])
            file_updates: dict[str, Any] = dict(update.get("files", {}))

            edited_messages = []
            for message in message_updates:
                if (
                    self.tool_token_limit_before_evict
                    and isinstance(message, ToolMessage)
                    and isinstance(message.content, str)
                    and _is_too_large(message.content)
                ):
                    _file_path, replacement, evict_files_update = _evict(message.content, message.tool_call_id)
                    edited_messages.append(replacement)
                    if evict_files_update:
                        file_updates.update(evict_files_update)
                    continue
                edited_messages.append(message)
            return Command(update={**update, "messages": edited_messages, "files": file_updates})

        return tool_result

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """Check the size of the tool call result and evict to filesystem if too large.

        Args:
            request: The tool call request being processed.
            handler: The handler function to call with the modified request.

        Returns:
            The raw ToolMessage, or a replacement with the ToolResult in state/store.
        """
        if self.tool_token_limit_before_evict is None or request.tool_call["name"] in TOOL_GENERATORS:
            return handler(request)

        tool_result = handler(request)
        runtime = getattr(request, "runtime", None)
        return self._intercept_large_tool_result(tool_result, runtime)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        """(async) Check the size of the tool call result and evict to filesystem if too large.

        Args:
            request: The tool call request being processed.
            handler: The handler function to call with the modified request.

        Returns:
            The raw ToolMessage, or a replacement with the ToolResult in state/store.
        """
        if self.tool_token_limit_before_evict is None or request.tool_call["name"] in TOOL_GENERATORS:
            return await handler(request)

        tool_result = await handler(request)
        runtime = getattr(request, "runtime", None)
        return self._intercept_large_tool_result(tool_result, runtime)

