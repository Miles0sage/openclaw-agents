"""
Tree-sitter based code chunker for OpenClaw autonomous agents.

Parses Python files into semantic chunks (functions, classes, blocks)
so agents get relevant code snippets instead of entire files.
"""

import os
import re
import logging
from dataclasses import dataclass, field
from typing import Optional

import tree_sitter_python as tspython
from tree_sitter import Language, Parser

logger = logging.getLogger("openclaw.code_chunker")

PY_LANGUAGE = Language(tspython.language())


@dataclass
class Chunk:
    """A semantic code chunk extracted from a source file."""
    name: str
    file: str
    start_line: int
    end_line: int
    content: str
    chunk_type: str  # "function", "class", "method", "decorator_group", "block"
    docstring: str = ""
    parent_class: str = ""
    decorators: list[str] = field(default_factory=list)

    @property
    def line_count(self) -> int:
        return self.end_line - self.start_line + 1

    def __repr__(self):
        parent = f"{self.parent_class}." if self.parent_class else ""
        return f"Chunk({self.chunk_type} {parent}{self.name}, {self.file}:{self.start_line}-{self.end_line})"


class TreeSitterChunker:
    """Parse Python files into semantic chunks using tree-sitter."""

    def __init__(self, max_chunk_lines: int = 150):
        self.parser = Parser(PY_LANGUAGE)
        self.max_chunk_lines = max_chunk_lines

    def chunk_file(self, path: str) -> list[Chunk]:
        """Parse a Python file and return a list of semantic chunks."""
        if not os.path.exists(path):
            logger.warning(f"File not found: {path}")
            return []

        try:
            with open(path, "rb") as f:
                source = f.read()
        except Exception as e:
            logger.error(f"Error reading {path}: {e}")
            return []

        tree = self.parser.parse(source)
        source_lines = source.decode("utf-8", errors="replace").split("\n")
        chunks = []

        self._extract_chunks(tree.root_node, source_lines, path, chunks)
        return chunks

    def _extract_chunks(
        self,
        node,
        source_lines: list[str],
        file_path: str,
        chunks: list[Chunk],
        parent_class: str = "",
    ):
        """Recursively extract chunks from the AST."""
        for child in node.children:
            if child.type == "function_definition":
                chunk = self._make_function_chunk(
                    child, source_lines, file_path, parent_class
                )
                if chunk:
                    chunks.append(chunk)

            elif child.type == "class_definition":
                class_name = self._get_name(child)
                # Add the class header as a chunk (up to first method)
                header_chunk = self._make_class_header_chunk(
                    child, source_lines, file_path
                )
                if header_chunk:
                    chunks.append(header_chunk)

                # Recurse into class body for methods
                body = self._get_body(child)
                if body:
                    self._extract_chunks(
                        body, source_lines, file_path, chunks, parent_class=class_name
                    )

            elif child.type == "decorated_definition":
                # Handle @decorator + def/class
                inner = None
                for sub in child.children:
                    if sub.type in ("function_definition", "class_definition"):
                        inner = sub
                        break
                if inner and inner.type == "function_definition":
                    chunk = self._make_function_chunk(
                        inner,
                        source_lines,
                        file_path,
                        parent_class,
                        decorator_node=child,
                    )
                    if chunk:
                        chunks.append(chunk)
                elif inner and inner.type == "class_definition":
                    class_name = self._get_name(inner)
                    header_chunk = self._make_class_header_chunk(
                        inner, source_lines, file_path, decorator_node=child
                    )
                    if header_chunk:
                        chunks.append(header_chunk)
                    body = self._get_body(inner)
                    if body:
                        self._extract_chunks(
                            body, source_lines, file_path, chunks, parent_class=class_name
                        )

    def _make_function_chunk(
        self,
        node,
        source_lines: list[str],
        file_path: str,
        parent_class: str = "",
        decorator_node=None,
    ) -> Optional[Chunk]:
        """Create a Chunk from a function_definition node."""
        name = self._get_name(node)
        if not name:
            return None

        # Use decorator node for start line if present
        start_node = decorator_node if decorator_node else node
        start_line = start_node.start_point[0] + 1
        end_line = node.end_point[0] + 1

        content = "\n".join(source_lines[start_line - 1 : end_line])
        docstring = self._extract_docstring(node, source_lines)
        decorators = self._extract_decorators(decorator_node) if decorator_node else []

        chunk_type = "method" if parent_class else "function"

        return Chunk(
            name=name,
            file=file_path,
            start_line=start_line,
            end_line=end_line,
            content=content,
            chunk_type=chunk_type,
            docstring=docstring,
            parent_class=parent_class,
            decorators=decorators,
        )

    def _make_class_header_chunk(
        self,
        node,
        source_lines: list[str],
        file_path: str,
        decorator_node=None,
    ) -> Optional[Chunk]:
        """Create a chunk for the class definition header (up to first method)."""
        name = self._get_name(node)
        if not name:
            return None

        start_node = decorator_node if decorator_node else node
        start_line = start_node.start_point[0] + 1

        # Find where the first method starts
        body = self._get_body(node)
        end_line = node.end_point[0] + 1
        if body:
            for child in body.children:
                if child.type in ("function_definition", "decorated_definition"):
                    end_line = child.start_point[0]  # line before first method
                    break

        # At minimum include the class line + docstring
        if end_line <= start_line:
            end_line = min(start_line + 5, node.end_point[0] + 1)

        content = "\n".join(source_lines[start_line - 1 : end_line])
        docstring = self._extract_docstring(node, source_lines)
        decorators = self._extract_decorators(decorator_node) if decorator_node else []

        return Chunk(
            name=name,
            file=file_path,
            start_line=start_line,
            end_line=end_line,
            content=content,
            chunk_type="class",
            docstring=docstring,
            decorators=decorators,
        )

    def _get_name(self, node) -> str:
        """Extract the name from a function/class definition node."""
        for child in node.children:
            if child.type == "identifier":
                return child.text.decode("utf-8")
        return ""

    def _get_body(self, node):
        """Get the body block of a class/function."""
        for child in node.children:
            if child.type == "block":
                return child
        return None

    def _extract_docstring(self, node, source_lines: list[str]) -> str:
        """Extract docstring from function/class if present."""
        body = self._get_body(node)
        if not body or not body.children:
            return ""
        first_stmt = body.children[0]
        if first_stmt.type == "expression_statement":
            expr = first_stmt.children[0] if first_stmt.children else None
            if expr and expr.type == "string":
                raw = expr.text.decode("utf-8", errors="replace")
                # Strip triple quotes
                for q in ('"""', "'''"):
                    if raw.startswith(q) and raw.endswith(q):
                        return raw[3:-3].strip()
                return raw.strip("\"'").strip()
        return ""

    def _extract_decorators(self, decorated_node) -> list[str]:
        """Extract decorator names from a decorated_definition node."""
        decorators = []
        if not decorated_node:
            return decorators
        for child in decorated_node.children:
            if child.type == "decorator":
                dec_text = child.text.decode("utf-8").strip()
                decorators.append(dec_text)
        return decorators

    def search_chunks(
        self, chunks: list[Chunk], query: str, top_k: int = 5
    ) -> list[Chunk]:
        """Find chunks matching a query by name, docstring, or content keywords."""
        query_lower = query.lower()
        query_words = set(re.split(r"[\s_./]+", query_lower))

        scored = []
        for chunk in chunks:
            score = 0

            # Exact name match (highest signal)
            if chunk.name.lower() == query_lower:
                score += 100

            # Name contains query
            if query_lower in chunk.name.lower():
                score += 50

            # Query words in name
            name_words = set(re.split(r"[\s_]+", chunk.name.lower()))
            overlap = query_words & name_words
            score += len(overlap) * 20

            # Decorator match (e.g., searching for "router.get" matches @router.get)
            for dec in chunk.decorators:
                if query_lower in dec.lower():
                    score += 40

            # Docstring match
            if query_lower in chunk.docstring.lower():
                score += 30

            # Content keyword match (lower weight)
            content_lower = chunk.content.lower()
            for word in query_words:
                if len(word) > 2 and word in content_lower:
                    score += 5

            if score > 0:
                scored.append((score, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [chunk for _, chunk in scored[:top_k]]

    def get_context_for_task(
        self,
        file_paths: list[str],
        task_description: str,
        max_chunks: int = 5,
        max_total_lines: int = 300,
    ) -> str:
        """
        Build a context string for an agent working on a task.

        Parses the given files, finds the most relevant chunks for the task,
        and returns them formatted with file/line references.
        """
        all_chunks = []
        for path in file_paths:
            if path.endswith(".py") and os.path.exists(path):
                all_chunks.extend(self.chunk_file(path))

        if not all_chunks:
            return ""

        relevant = self.search_chunks(all_chunks, task_description, top_k=max_chunks)

        # Trim to max_total_lines
        result_chunks = []
        total_lines = 0
        for chunk in relevant:
            if total_lines + chunk.line_count > max_total_lines:
                # Include partial if we have room
                remaining = max_total_lines - total_lines
                if remaining > 10:
                    trimmed_content = "\n".join(chunk.content.split("\n")[:remaining])
                    result_chunks.append(
                        f"# {chunk.file}:{chunk.start_line}-{chunk.start_line + remaining - 1} "
                        f"({chunk.chunk_type} {chunk.parent_class + '.' if chunk.parent_class else ''}{chunk.name})\n"
                        f"{trimmed_content}\n# ... truncated"
                    )
                break
            result_chunks.append(
                f"# {chunk.file}:{chunk.start_line}-{chunk.end_line} "
                f"({chunk.chunk_type} {chunk.parent_class + '.' if chunk.parent_class else ''}{chunk.name})\n"
                f"{chunk.content}"
            )
            total_lines += chunk.line_count

        return "\n\n".join(result_chunks)


# Module-level singleton
_chunker: Optional[TreeSitterChunker] = None


def get_chunker() -> TreeSitterChunker:
    """Get or create the singleton chunker."""
    global _chunker
    if _chunker is None:
        _chunker = TreeSitterChunker()
    return _chunker


if __name__ == "__main__":
    # Self-test
    import sys

    chunker = TreeSitterChunker()

    test_file = sys.argv[1] if len(sys.argv) > 1 else "./gateway.py"
    print(f"Chunking {test_file}...")

    chunks = chunker.chunk_file(test_file)
    print(f"Found {len(chunks)} chunks:\n")

    for c in chunks[:20]:
        parent = f"{c.parent_class}." if c.parent_class else ""
        decs = f" {c.decorators}" if c.decorators else ""
        doc = f' "{c.docstring[:60]}..."' if len(c.docstring) > 60 else f' "{c.docstring}"' if c.docstring else ""
        print(f"  {c.chunk_type:10} {parent}{c.name:40} L{c.start_line}-{c.end_line} ({c.line_count} lines){decs}{doc}")

    if len(chunks) > 20:
        print(f"  ... and {len(chunks) - 20} more")

    # Test search
    if chunks:
        print(f"\nSearch for 'health':")
        results = chunker.search_chunks(chunks, "health")
        for r in results:
            print(f"  {r}")
