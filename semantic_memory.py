"""
Semantic Memory Search — TF-IDF based semantic search for agent memory systems.

Provides:
- Index building from MEMORY.md files and memories.jsonl
- Semantic search by meaning (not just keyword matching)
- Auto-indexing with disk cache
- Lightweight (no external vector DB required)
"""

import os
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Tuple, Optional
import hashlib

logger = logging.getLogger("semantic_memory")

# Try to import sklearn — should be available
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    import numpy as np
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    logger.warning("scikit-learn not available; semantic search will use keyword fallback")


class SemanticMemoryIndex:
    """
    TF-IDF based semantic memory index.

    Indexes memories.jsonl, MEMORY.md files, and daily logs.
    Provides fast semantic search without external vector DB.
    """

    def __init__(self, data_dir: str = "./data", memory_dir: str = "/root/.claude/projects/-root/memory"):
        self.data_dir = data_dir
        self.memory_dir = memory_dir
        self.index_file = os.path.join(data_dir, "semantic_index.pkl")
        self.metadata_file = os.path.join(data_dir, "semantic_metadata.json")

        self.vectorizer = None
        self.matrix = None
        self.documents = []  # List of (content, source, importance, tags, id)
        self.index_hash = None

        if SKLEARN_AVAILABLE:
            self._load_or_build_index()

    def _get_index_hash(self) -> str:
        """Compute hash of all source files to detect if reindex is needed."""
        hasher = hashlib.md5()

        # Hash memories.jsonl
        mem_file = os.path.join(self.data_dir, "memories.jsonl")
        if os.path.exists(mem_file):
            with open(mem_file, "rb") as f:
                hasher.update(f.read())

        # Hash MEMORY.md files
        for root, dirs, files in os.walk(self.memory_dir):
            for file in sorted(files):
                if file.endswith(".md"):
                    fpath = os.path.join(root, file)
                    try:
                        with open(fpath, "rb") as f:
                            hasher.update(f.read())
                    except:
                        pass

        return hasher.hexdigest()

    def _load_or_build_index(self):
        """Load cached index if valid, else build fresh."""
        if not SKLEARN_AVAILABLE:
            return

        # Check if cached index is valid
        current_hash = self._get_index_hash()
        if os.path.exists(self.metadata_file):
            try:
                with open(self.metadata_file) as f:
                    meta = json.load(f)
                    if meta.get("index_hash") == current_hash:
                        self._load_cached_index()
                        logger.info(f"Loaded cached semantic index ({len(self.documents)} docs)")
                        return
            except:
                pass

        # Build fresh index
        logger.info("Building semantic memory index...")
        self._build_index()
        self._save_cached_index(current_hash)

    def _build_index(self):
        """Build TF-IDF index from all memory sources."""
        self.documents = []

        # Load from memories.jsonl
        self._index_jsonl()

        # Load from MEMORY.md files
        self._index_memory_md()

        # Load from daily logs if available
        self._index_daily_logs()

        if not self.documents:
            logger.warning("No documents found for indexing")
            return

        # Build vectorizer and matrix
        contents = [doc[0] for doc in self.documents]
        try:
            self.vectorizer = TfidfVectorizer(
                max_features=5000,
                stop_words="english",
                lowercase=True,
                ngram_range=(1, 2),
                min_df=1,
                max_df=0.95
            )
            self.matrix = self.vectorizer.fit_transform(contents)
            logger.info(f"Built TF-IDF index: {len(contents)} docs, {self.matrix.shape[1]} features")
        except Exception as e:
            logger.error(f"Error building index: {e}")
            self.vectorizer = None
            self.matrix = None

    def _index_jsonl(self):
        """Index memories.jsonl file."""
        mem_file = os.path.join(self.data_dir, "memories.jsonl")
        if not os.path.exists(mem_file):
            return

        try:
            with open(mem_file) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        content = record.get("content", "")
                        if content:
                            source = f"memory:{record.get('id', '?')}"
                            importance = record.get("importance", 5)
                            tags = record.get("tags", [])
                            mem_id = record.get("id", "")
                            self.documents.append((content, source, importance, tags, mem_id))
                    except:
                        pass
        except Exception as e:
            logger.error(f"Error indexing memories.jsonl: {e}")

    def _index_memory_md(self):
        """Index MEMORY.md topic files."""
        if not os.path.isdir(self.memory_dir):
            return

        try:
            for root, dirs, files in os.walk(self.memory_dir):
                for file in files:
                    if file.endswith(".md"):
                        fpath = os.path.join(root, file)
                        try:
                            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                                content = f.read()
                                if content:
                                    # Split by headings for finer granularity
                                    sections = self._split_markdown(content)
                                    for section in sections:
                                        if section.strip():
                                            source = f"memory_md:{file}"
                                            importance = 7  # Memory files are important
                                            tags = ["memory", file.replace(".md", "")]
                                            mem_id = hashlib.md5(f"{file}:{section}".encode()).hexdigest()[:8]
                                            self.documents.append((section, source, importance, tags, mem_id))
                        except Exception as e:
                            logger.debug(f"Error reading {fpath}: {e}")
        except Exception as e:
            logger.error(f"Error indexing memory MD: {e}")

    def _split_markdown(self, content: str, max_section_len: int = 500) -> List[str]:
        """Split markdown by headings, keep sections reasonable size."""
        sections = []
        current = []

        for line in content.split("\n"):
            if line.startswith("#") and current:
                section_text = "\n".join(current).strip()
                if section_text:
                    sections.append(section_text)
                current = [line]
            else:
                current.append(line)
                # Flush if section gets too long
                if len("\n".join(current)) > max_section_len:
                    section_text = "\n".join(current).strip()
                    if section_text:
                        sections.append(section_text)
                    current = []

        if current:
            section_text = "\n".join(current).strip()
            if section_text:
                sections.append(section_text)

        return sections

    def _index_daily_logs(self):
        """Index daily session logs if available."""
        logs_dir = os.path.join(self.data_dir, "session_logs")
        if not os.path.isdir(logs_dir):
            return

        try:
            for file in os.listdir(logs_dir):
                if file.endswith(".md"):
                    fpath = os.path.join(logs_dir, file)
                    try:
                        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read()
                            if content:
                                # Index entire log as one doc
                                source = f"daily_log:{file}"
                                importance = 5
                                tags = ["daily_log", file.replace(".md", "")]
                                mem_id = hashlib.md5(file.encode()).hexdigest()[:8]
                                self.documents.append((content, source, importance, tags, mem_id))
                    except:
                        pass
        except:
            pass

    def _save_cached_index(self, index_hash: str):
        """Save vectorizer and metadata to disk."""
        if not SKLEARN_AVAILABLE or not self.vectorizer:
            return

        try:
            import pickle
            with open(self.index_file, "wb") as f:
                pickle.dump({
                    "vectorizer": self.vectorizer,
                    "matrix": self.matrix.toarray() if hasattr(self.matrix, "toarray") else self.matrix,
                }, f)

            with open(self.metadata_file, "w") as f:
                json.dump({
                    "index_hash": index_hash,
                    "doc_count": len(self.documents),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "documents": [
                        {
                            "id": doc[4],
                            "source": doc[1],
                            "importance": doc[2],
                            "tags": doc[3],
                            "preview": doc[0][:100]
                        }
                        for doc in self.documents
                    ]
                }, f, indent=2)
            logger.info(f"Cached semantic index to {self.index_file}")
        except Exception as e:
            logger.error(f"Error caching index: {e}")

    def _load_cached_index(self):
        """Load vectorizer from disk."""
        if not SKLEARN_AVAILABLE or not os.path.exists(self.index_file):
            return False

        try:
            import pickle
            with open(self.index_file, "rb") as f:
                data = pickle.load(f)
                self.vectorizer = data.get("vectorizer")
                matrix_array = data.get("matrix")
                if matrix_array is not None:
                    from scipy.sparse import csr_matrix
                    self.matrix = csr_matrix(matrix_array)

            # Reload document metadata
            with open(self.metadata_file) as f:
                meta = json.load(f)
                # Rebuild documents list from metadata
                for doc_meta in meta.get("documents", []):
                    # Note: We only have preview, so use it as content for now
                    self.documents.append((
                        doc_meta.get("preview", ""),
                        doc_meta.get("source", ""),
                        doc_meta.get("importance", 5),
                        doc_meta.get("tags", []),
                        doc_meta.get("id", "")
                    ))
            return True
        except Exception as e:
            logger.error(f"Error loading cached index: {e}")
            return False

    def search(self, query: str, limit: int = 5, min_score: float = 0.1) -> List[Dict]:
        """
        Semantic search by meaning (cosine similarity).

        Args:
            query: Search query
            limit: Max results
            min_score: Minimum similarity score (0-1)

        Returns:
            List of dicts with 'content', 'source', 'importance', 'score', 'id'
        """
        if not SKLEARN_AVAILABLE or self.vectorizer is None or self.matrix is None or not self.documents:
            # Fallback to keyword search
            return self._keyword_search(query, limit)

        try:
            # Vectorize query
            query_vec = self.vectorizer.transform([query])

            # Compute similarity
            similarities = cosine_similarity(query_vec, self.matrix)[0]

            # Get top matches
            top_indices = np.argsort(similarities)[::-1][:limit * 2]  # Get extra to filter by score

            results = []
            for idx in top_indices:
                score = float(similarities[idx])
                if score < min_score:
                    continue

                doc = self.documents[idx]
                results.append({
                    "content": doc[0][:200],  # Preview
                    "source": doc[1],
                    "importance": doc[2],
                    "tags": doc[3],
                    "id": doc[4],
                    "score": score
                })

            return results[:limit]
        except Exception as e:
            logger.error(f"Error in semantic search: {e}")
            return self._keyword_search(query, limit)

    def _keyword_search(self, query: str, limit: int = 5) -> List[Dict]:
        """Fallback keyword search."""
        query_lower = query.lower()
        results = []

        for doc in self.documents:
            content, source, importance, tags, mem_id = doc
            content_lower = content.lower()
            tags_str = " ".join(tags).lower()

            # Simple scoring: exact match > tag match > substring match
            score = 0.0
            if query_lower == content_lower:
                score = 1.0
            elif query_lower in tags_str:
                score = 0.7
            elif query_lower in content_lower:
                score = 0.5
            else:
                continue

            results.append({
                "content": content[:200],
                "source": source,
                "importance": importance,
                "tags": tags,
                "id": mem_id,
                "score": score
            })

        # Sort by importance then score
        results.sort(key=lambda x: (x["importance"], x["score"]), reverse=True)
        return results[:limit]


# Global index instance
_index: Optional[SemanticMemoryIndex] = None


def get_semantic_index() -> SemanticMemoryIndex:
    """Get or create global semantic index."""
    global _index
    if _index is None:
        _index = SemanticMemoryIndex()
    return _index


def semantic_search(query: str, limit: int = 5) -> List[Dict]:
    """
    Perform semantic search on agent memories.

    Returns list of matches with content, source, importance, score, id.
    """
    index = get_semantic_index()
    return index.search(query, limit)


def rebuild_index():
    """Force rebuild of semantic index (e.g., after many new memories)."""
    global _index
    _index = None
    get_semantic_index()
    logger.info("Semantic index rebuilt")


if __name__ == "__main__":
    # Called from settings.json hooks or CLI to rebuild index
    import sys
    logging.basicConfig(level=logging.INFO)
    rebuild_index()
    print("Semantic memory index rebuild complete")
