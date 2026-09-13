"""Load retired Q3 behavior from an immutable experiment fixture for tests only."""
import base64,hashlib,json,types
from pathlib import Path
root=Path(__file__).resolve().parent
fixture=json.loads((root/'results/validation/fusion_q3/current_sources.json').read_text(encoding='utf-8'))
item=fixture['成果/support/omni_search.py'];data=base64.b64decode(item['bytes_base64'])
if hashlib.sha256(data).hexdigest()!=item['sha256']:raise ValueError('Historical fixture digest mismatch')
module=types.ModuleType('historical_omni_fixture')
exec(compile(data,'<historical Q3 fixture>','exec'),module.__dict__)
FrozenOmniSearchSolver=module.OmniSearchSolver
