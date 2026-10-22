"""Keep all automated integration checks away from user records and API keys."""
import os
from pathlib import Path
import tempfile

_test_data = Path(tempfile.mkdtemp(prefix='learning-copilot-tests-'))
os.environ['DATABASE_URL'] = 'sqlite:///' + (_test_data / 'app.db').as_posix()
os.environ['STORAGE_DIR'] = str(_test_data)
os.environ['CHROMA_PATH'] = str(_test_data / 'chroma')
os.environ['LLM_API_KEY'] = ''
