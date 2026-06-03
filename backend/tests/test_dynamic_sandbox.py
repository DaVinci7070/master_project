import pytest
from app.skills.testing.docker_sandbox import DynamicSandboxService, SandboxResult


@pytest.fixture
def sandbox():
    """Create sandbox service instance."""
    return DynamicSandboxService()


@pytest.mark.asyncio
async def test_sandbox_available(sandbox):
    """Test that Docker is available."""
    assert sandbox.is_available(), "Docker must be running for sandbox tests"


@pytest.mark.asyncio
async def test_simple_execution(sandbox):
    """Test basic Python code execution."""
    result = await sandbox.execute(
        code='print("Hello, Sandbox!")'
    )

    assert result.success
    assert "Hello, Sandbox!" in result.stdout
    assert result.exit_code == 0


@pytest.mark.asyncio
async def test_pip_install(sandbox):
    """Test pip package installation."""
    result = await sandbox.execute(
        code="""
import requests
response = requests.get('https://httpbin.org/get')
print(f"Status: {response.status_code}")
""",
        pip_requirements=["requests"],
    )

    assert result.success, f"Failed: {result.error or result.stderr}"
    assert "Status: 200" in result.stdout


@pytest.mark.asyncio
async def test_system_package_install(sandbox):
    """Test system package installation (ffmpeg)."""
    result = await sandbox.execute(
        code="""
import subprocess
result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True)
print(f"ffmpeg installed: {result.returncode == 0}")
print(result.stdout[:100])
""",
        system_packages=["ffmpeg"],
    )

    assert result.success, f"Failed: {result.error or result.stderr}"
    assert "ffmpeg installed: True" in result.stdout


@pytest.mark.asyncio
async def test_input_files(sandbox):
    """Test file mounting."""
    test_content = b"Hello from input file!"

    result = await sandbox.execute(
        code="""
with open('/workspace/test.txt', 'r') as f:
    content = f.read()
print(f"Content: {content}")
""",
        input_files={"test.txt": test_content},
    )

    assert result.success, f"Failed: {result.error or result.stderr}"
    assert "Hello from input file!" in result.stdout


@pytest.mark.asyncio
async def test_output_files(sandbox):
    """Test output file collection."""
    result = await sandbox.execute(
        code="""
with open('/workspace/output.txt', 'w') as f:
    f.write('Generated output!')
print("File written")
""",
        output_file_paths=["output.txt"],
    )

    assert result.success, f"Failed: {result.error or result.stderr}"
    assert "output.txt" in result.output_files
    assert b"Generated output!" in result.output_files["output.txt"]


@pytest.mark.asyncio
async def test_execution_error(sandbox):
    """Test that execution errors are captured."""
    result = await sandbox.execute(
        code='raise ValueError("Test error")'
    )

    assert not result.success
    assert result.exit_code != 0
    assert "ValueError" in result.stderr or "Test error" in result.stderr


@pytest.mark.asyncio
async def test_import_error_missing_package(sandbox):
    """Test that missing package errors are captured."""
    result = await sandbox.execute(
        code='import nonexistent_package_xyz'
    )

    assert not result.success
    assert "ModuleNotFoundError" in result.stderr or "No module named" in result.stderr


@pytest.mark.asyncio
async def test_network_access(sandbox):
    """Test that network access works."""
    result = await sandbox.execute(
        code="""
import urllib.request
try:
    with urllib.request.urlopen('https://www.google.com', timeout=10) as response:
        print(f"Network OK: {response.status}")
except Exception as e:
    print(f"Network Error: {e}")
""",
    )

    assert result.success, f"Failed: {result.error or result.stderr}"
    assert "Network OK: 200" in result.stdout


@pytest.mark.asyncio
async def test_combined_pip_and_apt(sandbox):
    """Test installing both pip and apt packages together."""
    result = await sandbox.execute(
        code="""
import subprocess
import pydub
from pydub import AudioSegment

# Check ffmpeg
ffmpeg_check = subprocess.run(['which', 'ffmpeg'], capture_output=True, text=True)
print(f"ffmpeg: {ffmpeg_check.stdout.strip()}")
print(f"pydub imported: {pydub is not None}")
print("Combined install successful!")
""",
        pip_requirements=["pydub"],
        system_packages=["ffmpeg"],
    )

    assert result.success, f"Failed: {result.error or result.stderr}"
    assert "Combined install successful!" in result.stdout


@pytest.mark.asyncio
@pytest.mark.skip(reason="Requires GPU/large download - run manually")
async def test_whisper_transcription(sandbox):
    """Test audio transcription with faster-whisper."""
    result = await sandbox.execute(
        code="""
from faster_whisper import WhisperModel

# Load tiny model for testing
model = WhisperModel("tiny", device="cpu", compute_type="int8")
print("Whisper model loaded successfully!")

# Would transcribe audio here if we had a file
# segments, info = model.transcribe("/workspace/audio.opus")
""",
        pip_requirements=["faster-whisper"],
        system_packages=["ffmpeg"],
    )

    assert result.success, f"Failed: {result.error or result.stderr}"
    assert "Whisper model loaded successfully!" in result.stdout
