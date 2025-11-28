"""Unit tests for GrpcSandbox and BaseSandbox classes."""

from unittest.mock import MagicMock, patch

import pytest

from deepagents.backends.protocol import (
    EditResult,
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
    WriteResult,
)
from deepagents.backends.sandbox import BaseSandbox, GrpcSandbox


class TestGrpcSandbox:
    """Test suite for GrpcSandbox gRPC client."""

    @pytest.fixture
    def mock_pb2(self):
        """Create mock protobuf module."""
        mock = MagicMock()
        mock.ReadRequest = MagicMock()
        mock.WriteRequest = MagicMock()
        mock.EditRequest = MagicMock()
        mock.ListRequest = MagicMock()
        mock.GrepRequest = MagicMock()
        mock.GlobRequest = MagicMock()
        mock.ExecuteRequest = MagicMock()
        mock.UploadRequest = MagicMock()
        mock.DownloadRequest = MagicMock()
        mock.FileUpload = MagicMock()
        mock.Empty = MagicMock()
        return mock

    @pytest.fixture
    def mock_stub(self):
        """Create mock gRPC stub."""
        return MagicMock()

    @pytest.fixture
    def grpc_sandbox(self, mock_pb2, mock_stub):
        """Create a GrpcSandbox with mocked dependencies."""
        with patch("deepagents.backends.sandbox.grpc") as mock_grpc:
            with patch.object(
                GrpcSandbox, "__init__", lambda self, endpoint, sandbox_id=None: None
            ):
                sandbox = GrpcSandbox.__new__(GrpcSandbox)
                sandbox._rpc_endpoint = "localhost:50051"
                sandbox._channel = mock_grpc.insecure_channel.return_value
                sandbox._stub = mock_stub
                sandbox._sandbox_id = None
                sandbox._pb2 = mock_pb2
                return sandbox

    def test_init(self):
        """Test GrpcSandbox initialization."""
        with patch("deepagents.backends.sandbox.grpc") as mock_grpc:
            # Patch the import inside the __init__ method
            with patch.dict(
                "sys.modules",
                {
                    "deepagents.backends.sandbox_io_pb2": MagicMock(),
                    "deepagents.backends.sandbox_io_pb2_grpc": MagicMock(),
                },
            ):
                sandbox = GrpcSandbox("localhost:50051")
                mock_grpc.insecure_channel.assert_called_once_with("localhost:50051")

    def test_id_property_fetches_from_server(self, grpc_sandbox, mock_stub, mock_pb2):
        """Test id property fetches from server when not set."""
        mock_response = MagicMock()
        mock_response.id = "test-sandbox-id"
        mock_stub.GetId.return_value = mock_response

        result = grpc_sandbox.id

        assert result == "test-sandbox-id"
        mock_stub.GetId.assert_called_once()

    def test_id_property_returns_cached_value(self, grpc_sandbox, mock_stub):
        """Test id property returns cached value."""
        grpc_sandbox._sandbox_id = "cached-id"

        result = grpc_sandbox.id

        assert result == "cached-id"
        mock_stub.GetId.assert_not_called()

    def test_id_property_fallback_on_error(self, grpc_sandbox, mock_stub):
        """Test id property returns fallback on RPC error."""
        import grpc

        mock_stub.GetId.side_effect = grpc.RpcError()

        result = grpc_sandbox.id

        assert "grpc-sandbox-localhost:50051" in result

    def test_read_success(self, grpc_sandbox, mock_stub, mock_pb2):
        """Test read file via RPC."""
        mock_response = MagicMock()
        mock_response.output = "     1\thello world"
        mock_stub.ReadFile.return_value = mock_response

        result = grpc_sandbox.read("/test.txt")

        assert result == "     1\thello world"
        mock_pb2.ReadRequest.assert_called_once_with(
            file_path="/test.txt", offset=0, limit=2000
        )

    def test_read_with_offset_limit(self, grpc_sandbox, mock_stub, mock_pb2):
        """Test read file with offset and limit."""
        mock_response = MagicMock()
        mock_response.output = "    11\tline 11"
        mock_stub.ReadFile.return_value = mock_response

        result = grpc_sandbox.read("/test.txt", offset=10, limit=100)

        mock_pb2.ReadRequest.assert_called_once_with(
            file_path="/test.txt", offset=10, limit=100
        )

    def test_read_rpc_error(self, grpc_sandbox, mock_stub):
        """Test read handles RPC error."""
        import grpc

        error = grpc.RpcError()
        error.details = MagicMock(return_value="Connection failed")
        mock_stub.ReadFile.side_effect = error

        result = grpc_sandbox.read("/test.txt")

        assert "Error: RPC communication failed" in result

    def test_write_success(self, grpc_sandbox, mock_stub, mock_pb2):
        """Test write file via RPC."""
        mock_response = MagicMock()
        mock_response.error = ""
        mock_response.path = "/test.txt"
        mock_stub.WriteFile.return_value = mock_response

        result = grpc_sandbox.write("/test.txt", "content")

        assert isinstance(result, WriteResult)
        assert result.path == "/test.txt"
        assert result.error is None
        mock_pb2.WriteRequest.assert_called_once_with(
            file_path="/test.txt", content="content"
        )

    def test_write_error(self, grpc_sandbox, mock_stub, mock_pb2):
        """Test write returns error when file exists."""
        mock_response = MagicMock()
        mock_response.error = "File already exists"
        mock_response.path = ""
        mock_stub.WriteFile.return_value = mock_response

        result = grpc_sandbox.write("/test.txt", "content")

        assert isinstance(result, WriteResult)
        assert result.error == "File already exists"

    def test_edit_success(self, grpc_sandbox, mock_stub, mock_pb2):
        """Test edit file via RPC."""
        mock_response = MagicMock()
        mock_response.error = ""
        mock_response.path = "/test.txt"
        mock_response.occurrences = 2
        mock_stub.EditFile.return_value = mock_response

        result = grpc_sandbox.edit("/test.txt", "old", "new", replace_all=True)

        assert isinstance(result, EditResult)
        assert result.path == "/test.txt"
        assert result.occurrences == 2
        mock_pb2.EditRequest.assert_called_once_with(
            file_path="/test.txt",
            old_string="old",
            new_string="new",
            replace_all=True,
        )

    def test_edit_error(self, grpc_sandbox, mock_stub, mock_pb2):
        """Test edit returns error when string not found."""
        mock_response = MagicMock()
        mock_response.error = "String not found"
        mock_response.path = ""
        mock_response.occurrences = 0
        mock_stub.EditFile.return_value = mock_response

        result = grpc_sandbox.edit("/test.txt", "old", "new")

        assert isinstance(result, EditResult)
        assert result.error == "String not found"

    def test_ls_info_success(self, grpc_sandbox, mock_stub, mock_pb2):
        """Test list directory via RPC."""
        mock_item1 = MagicMock()
        mock_item1.path = "file1.txt"
        mock_item1.is_dir = False
        mock_item1.size = 100
        mock_item1.modified_at = "2024-01-01T00:00:00"

        mock_item2 = MagicMock()
        mock_item2.path = "subdir"
        mock_item2.is_dir = True
        mock_item2.size = 0
        mock_item2.modified_at = ""

        mock_stub.ListInfo.return_value = iter([mock_item1, mock_item2])

        result = grpc_sandbox.ls_info("/path")

        assert len(result) == 2
        assert result[0]["path"] == "file1.txt"
        assert result[0]["is_dir"] is False
        assert result[1]["path"] == "subdir"
        assert result[1]["is_dir"] is True

    def test_grep_raw_success(self, grpc_sandbox, mock_stub, mock_pb2):
        """Test grep via RPC."""
        mock_match = MagicMock()
        mock_match.path = "/test.txt"
        mock_match.line = 10
        mock_match.text = "matched line"

        mock_stub.GrepRaw.return_value = iter([mock_match])

        result = grpc_sandbox.grep_raw("pattern", path="/path")

        assert len(result) == 1
        assert result[0]["path"] == "/test.txt"
        assert result[0]["line"] == 10
        assert result[0]["text"] == "matched line"

    def test_grep_raw_rpc_error(self, grpc_sandbox, mock_stub):
        """Test grep handles RPC error."""
        import grpc

        error = grpc.RpcError()
        error.details = MagicMock(return_value="Connection failed")
        mock_stub.GrepRaw.side_effect = error

        result = grpc_sandbox.grep_raw("pattern")

        assert isinstance(result, str)
        assert "Error: RPC communication failed" in result

    def test_glob_info_success(self, grpc_sandbox, mock_stub, mock_pb2):
        """Test glob via RPC."""
        mock_item = MagicMock()
        mock_item.path = "test.py"
        mock_item.is_dir = False
        mock_item.size = 0
        mock_item.modified_at = ""

        mock_stub.GlobInfo.return_value = iter([mock_item])

        result = grpc_sandbox.glob_info("*.py", path="/path")

        assert len(result) == 1
        assert result[0]["path"] == "test.py"

    def test_execute_success(self, grpc_sandbox, mock_stub, mock_pb2):
        """Test execute command via RPC."""
        mock_response = MagicMock()
        mock_response.output = "command output"
        mock_response.exit_code = 0
        mock_response.truncated = False
        mock_stub.Execute.return_value = mock_response

        result = grpc_sandbox.execute("echo hello")

        assert isinstance(result, ExecuteResponse)
        assert result.output == "command output"
        assert result.exit_code == 0
        assert result.truncated is False

    def test_execute_rpc_error(self, grpc_sandbox, mock_stub):
        """Test execute handles RPC error."""
        import grpc

        error = grpc.RpcError()
        error.details = MagicMock(return_value="Connection failed")
        mock_stub.Execute.side_effect = error

        result = grpc_sandbox.execute("echo hello")

        assert isinstance(result, ExecuteResponse)
        assert result.exit_code == 1
        assert "Error: RPC communication failed" in result.output

    def test_upload_files_success(self, grpc_sandbox, mock_stub, mock_pb2):
        """Test upload files via RPC."""
        mock_result = MagicMock()
        mock_result.path = "/test.txt"
        mock_result.error = ""

        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_stub.UploadFiles.return_value = mock_response

        result = grpc_sandbox.upload_files([("/test.txt", b"content")])

        assert len(result) == 1
        assert isinstance(result[0], FileUploadResponse)
        assert result[0].path == "/test.txt"
        assert result[0].error is None

    def test_download_files_success(self, grpc_sandbox, mock_stub, mock_pb2):
        """Test download files via RPC."""
        mock_result = MagicMock()
        mock_result.path = "/test.txt"
        mock_result.content = b"file content"
        mock_result.error = ""

        mock_response = MagicMock()
        mock_response.results = [mock_result]
        mock_stub.DownloadFiles.return_value = mock_response

        result = grpc_sandbox.download_files(["/test.txt"])

        assert len(result) == 1
        assert isinstance(result[0], FileDownloadResponse)
        assert result[0].path == "/test.txt"
        assert result[0].content == b"file content"
        assert result[0].error is None

    def test_close(self, grpc_sandbox):
        """Test close cleans up channel."""
        mock_channel = MagicMock()
        grpc_sandbox._channel = mock_channel

        grpc_sandbox.close()

        mock_channel.close.assert_called_once()


class TestBaseSandbox:
    """Test suite for BaseSandbox abstract class."""

    def test_is_abstract(self):
        """Test BaseSandbox is abstract and cannot be instantiated."""
        with pytest.raises(TypeError):
            BaseSandbox()


class TestGraphConstants:
    """Test suite for graph.py constants and factory function."""

    def test_proactive_summary_threshold(self):
        """Test PROACTIVE_SUMMARY_THRESHOLD constant."""
        from deepagents.graph import PROACTIVE_SUMMARY_THRESHOLD

        assert PROACTIVE_SUMMARY_THRESHOLD == 45000

    def test_default_context_messages_to_keep(self):
        """Test DEFAULT_CONTEXT_MESSAGES_TO_KEEP constant."""
        from deepagents.graph import DEFAULT_CONTEXT_MESSAGES_TO_KEEP

        assert DEFAULT_CONTEXT_MESSAGES_TO_KEEP == 6

    def test_create_core_middleware_returns_list(self):
        """Test _create_core_middleware returns a list of middleware."""
        from unittest.mock import MagicMock

        from deepagents.graph import _create_core_middleware

        mock_model = MagicMock()
        trigger = ("tokens", 45000)
        keep = ("messages", 6)

        result = _create_core_middleware(mock_model, trigger, keep)

        assert isinstance(result, list)
        assert len(result) == 3  # SummarizationMiddleware, AnthropicPromptCachingMiddleware, PatchToolCallsMiddleware

    def test_create_core_middleware_includes_expected_types(self):
        """Test _create_core_middleware returns expected middleware types."""
        from unittest.mock import MagicMock

        from langchain.agents.middleware.summarization import SummarizationMiddleware
        from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware

        from deepagents.graph import _create_core_middleware
        from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware

        mock_model = MagicMock()
        trigger = ("tokens", 45000)
        keep = ("messages", 6)

        result = _create_core_middleware(mock_model, trigger, keep)

        # Check middleware types
        assert isinstance(result[0], SummarizationMiddleware)
        assert isinstance(result[1], AnthropicPromptCachingMiddleware)
        assert isinstance(result[2], PatchToolCallsMiddleware)
