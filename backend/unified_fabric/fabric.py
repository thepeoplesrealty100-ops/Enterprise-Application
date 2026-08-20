import json
from pathlib import Path
from typing import Any, Dict, List, Optional

class UnifiedFabric:
    """Helper to load manifest and query cheatsheets for the Unified Security Fabric."""
    def __init__(self, repo_root: Optional[Path] = None):
        self.repo_root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[2]
        self.manifest_path = self.repo_root / "gacyber_toolkit" / "unified_fabric_manifest.json"
        self.cheatsheet_path = self.repo_root / "gacyber_toolkit" / "cheatsheet_data.json"
        self._manifest = None

    def load_manifest(self) -> Dict[str, Any]:
        if self._manifest is None:
            if not self.manifest_path.exists():
                raise FileNotFoundError(f"Manifest not found: {self.manifest_path}")
            with open(self.manifest_path, "r", encoding="utf-8") as fh:
                self._manifest = json.load(fh)
        return self._manifest

    def list_modules(self) -> List[Dict[str, Any]]:
        m = self.load_manifest()
        return m.get("modules", [])

    def get_module(self, key: str) -> Optional[Dict[str, Any]]:
        for mod in self.list_modules():
            if mod.get("key") == key:
                return mod
        return None

    def load_cheatsheets(self) -> List[Dict[str, Any]]:
        if not self.cheatsheet_path.exists():
            return []
        with open(self.cheatsheet_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        # Expect top-level list or dict with 'entries'
        if isinstance(data, dict) and data.get("entries"):
            return data.get("entries")
        if isinstance(data, list):
            return data
        return []

    def search_cheatsheets(self, module_key: Optional[str] = None, q: Optional[str] = None) -> List[Dict[str, Any]]:
        entries = self.load_cheatsheets()
        results = []
        q_lower = q.lower() if q else None
        for e in entries:
            # Assume entries have 'id', 'title', 'module', 'tags', 'content'
            module_match = (module_key is None) or (e.get("module") == module_key) or (module_key in (e.get("tags") or []))
            text = " ".join(str(v) for v in [e.get("title",""), e.get("content",""), " ".join(e.get("tags",[]))]).lower()
            q_match = (q_lower is None) or (q_lower in text)
            if module_match and q_match:
                results.append(e)
        return results
