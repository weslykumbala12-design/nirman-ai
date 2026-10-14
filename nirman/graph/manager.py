"""
NIRMAN AI — Graph-Based Context Manager

Organises building photographs into typed cells connected by architectural
relationships. For any generation or editing request, only the relevant
subgraph is retrieved — reducing LLM token usage while preserving quality.

Token reduction is measured and logged for each selection.
"""
from __future__ import annotations
import uuid
import logging
from collections import deque
from datetime import datetime
from typing import Optional

import networkx as nx

from .models import (
    BuildingGraph, GraphCell, GraphEdge, PhotoEntry,
    CellType, EdgeType, ContextSelection,
)
from .classifier import PhotoClassifier

logger = logging.getLogger(__name__)

# Approximate token costs
_TOKENS_PER_IMAGE  = 500
_TOKENS_PER_CHAR   = 0.25   # ~4 chars per token


class GraphContextManager:
    """
    Manages building photo cells and typed edges using NetworkX.
    Selects minimal relevant subgraphs to reduce LLM context size.
    """

    def __init__(self) -> None:
        self._nx: dict[str, nx.DiGraph] = {}   # building_id → nx.DiGraph

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def create_building_graph(self, building_id: str) -> BuildingGraph:
        graph = BuildingGraph(building_id=building_id)
        self._nx[building_id] = nx.DiGraph()
        return graph

    def add_cell(self, graph: BuildingGraph, cell: GraphCell) -> None:
        graph.cells[cell.id] = cell
        self._get_nx(graph.building_id).add_node(
            cell.id, cell_type=cell.cell_type, data=cell
        )

    def add_edge(self, graph: BuildingGraph, edge: GraphEdge) -> None:
        graph.edges.append(edge)
        self._get_nx(graph.building_id).add_edge(
            edge.source_id, edge.target_id,
            edge_type=edge.edge_type, weight=edge.weight,
        )

    # ------------------------------------------------------------------
    # Auto-build from photo list
    # ------------------------------------------------------------------

    def auto_build_graph(
        self, building_id: str, photos: list[dict]
    ) -> BuildingGraph:
        """
        Build graph from a list of photo dicts:
            [{"file_path": str, "prompt": str, "hint": Optional[str]}]

        Photos of the same CellType are grouped into one cell.
        Typed edges are created automatically from type relationships.
        """
        clf   = PhotoClassifier()
        graph = self.create_building_graph(building_id)
        type_to_cell: dict[CellType, GraphCell] = {}

        for photo_dict in photos:
            fp    = photo_dict["file_path"]
            prompt = photo_dict.get("prompt", "")
            hint  = photo_dict.get("hint")

            ct, conf = clf.classify(fp, hint)

            if ct not in type_to_cell:
                cell_id = f"{building_id}_{ct.value}_{uuid.uuid4().hex[:6]}"
                cell = GraphCell(
                    id=cell_id,
                    cell_type=ct,
                    cell_prompt=f"Photos of {ct.value.replace('_', ' ')}",
                    confidence=conf,
                    floor_level=self._default_floor(ct),
                )
                type_to_cell[ct] = cell
                self.add_cell(graph, cell)

            cell = type_to_cell[ct]
            photo = PhotoEntry(
                id=f"photo_{uuid.uuid4().hex[:8]}",
                file_path=fp,
                prompt=prompt,
                cell_id=cell.id,
            )
            cell.photos.append(photo)

        self._auto_edges(graph, type_to_cell)
        logger.info(
            "Auto-built graph for '%s': %d cells, %d edges",
            building_id, len(graph.cells), len(graph.edges),
        )
        return graph

    def _default_floor(self, ct: CellType) -> Optional[int]:
        return {
            CellType.GROUND_FLOOR_INTERIOR: 0,
            CellType.STAIRCASE_LANDING:     0,
            CellType.UPPER_FLOOR_INTERIOR:  1,
        }.get(ct)

    def _auto_edges(
        self, graph: BuildingGraph, ctm: dict[CellType, GraphCell]
    ) -> None:
        gf = ctm.get(CellType.GROUND_FLOOR_INTERIOR)
        uf = ctm.get(CellType.UPPER_FLOOR_INTERIOR)
        st = ctm.get(CellType.STAIRCASE_LANDING)
        ex = ctm.get(CellType.EXTERIOR_FACADE)
        rf = ctm.get(CellType.ROOF_TERRACE)

        def edge(src: GraphCell, tgt: GraphCell, et: EdgeType) -> None:
            self.add_edge(graph, GraphEdge(source_id=src.id, target_id=tgt.id, edge_type=et))

        if gf and st:
            edge(gf, st, EdgeType.STAIRS_TO)
            edge(gf, st, EdgeType.SAME_FLOOR_AS)
        if st and uf:
            edge(st, uf, EdgeType.STAIRS_TO)
        elif gf and uf:
            edge(gf, uf, EdgeType.STAIRS_TO)
        if uf and rf:
            edge(uf, rf, EdgeType.STAIRS_TO)
        if ex:
            for tgt in [gf, uf]:
                if tgt:
                    edge(ex, tgt, EdgeType.CONTEXT_OF)

    # ------------------------------------------------------------------
    # Context selection
    # ------------------------------------------------------------------

    def select_context_for_request(
        self,
        graph: BuildingGraph,
        request: str,
        target_cell_ids: Optional[list[str]] = None,
    ) -> ContextSelection:
        """
        Select cells relevant to the request.
        Always includes EXTERIOR_FACADE cells for style reference (marked style_only).
        Logs token reduction vs. full-context baseline.
        """
        seed_ids = set(target_cell_ids) if target_cell_ids else self._keyword_seeds(graph, request)
        expanded  = self.get_subgraph(graph, list(seed_ids), hops=1)
        expanded_ids = {c.id for c in expanded}

        style_only: list[str] = []
        for cid, cell in graph.cells.items():
            if cell.cell_type == CellType.EXTERIOR_FACADE and cid not in expanded_ids:
                expanded.append(cell)
                expanded_ids.add(cid)
                style_only.append(cid)

        total_photos = sum(len(c.photos) for c in expanded)
        token_est    = self._estimate_tokens(expanded, request)

        # Log reduction
        full_tokens = self._estimate_tokens(list(graph.cells.values()), request)
        reduction   = self.compute_token_reduction(full_tokens, token_est)
        logger.info(
            "Context selection: %d/%d cells | tokens: %d/%d (%.1f%% reduction)",
            len(expanded), len(graph.cells),
            token_est, full_tokens, reduction["reduction_pct"],
        )

        return ContextSelection(
            selected_cells=expanded,
            total_photos=total_photos,
            total_tokens_estimated=token_est,
            selection_reason=(
                f"Matched '{request[:60]}' → {len(expanded)} cells "
                f"(saved {reduction['reduction_pct']:.1f}% tokens)"
            ),
            style_only_cell_ids=style_only,
        )

    def _keyword_seeds(self, graph: BuildingGraph, request: str) -> set[str]:
        kw_map: dict[str, list[CellType]] = {
            "kitchen":   [CellType.GROUND_FLOOR_INTERIOR],
            "living":    [CellType.GROUND_FLOOR_INTERIOR],
            "lobby":     [CellType.GROUND_FLOOR_INTERIOR],
            "ground":    [CellType.GROUND_FLOOR_INTERIOR],
            "entrance":  [CellType.GROUND_FLOOR_INTERIOR],
            "bedroom":   [CellType.UPPER_FLOOR_INTERIOR],
            "bathroom":  [CellType.UPPER_FLOOR_INTERIOR],
            "upper":     [CellType.UPPER_FLOOR_INTERIOR],
            "stairs":    [CellType.STAIRCASE_LANDING],
            "staircase": [CellType.STAIRCASE_LANDING],
            "landing":   [CellType.STAIRCASE_LANDING],
            "roof":      [CellType.ROOF_TERRACE],
            "terrace":   [CellType.ROOF_TERRACE],
            "exterior":  [CellType.EXTERIOR_FACADE],
            "facade":    [CellType.EXTERIOR_FACADE],
        }
        words  = request.lower().split()
        matched: set[str] = set()
        for w in words:
            if w in kw_map:
                for ct in kw_map[w]:
                    matched.update(cid for cid, c in graph.cells.items() if c.cell_type == ct)
            for cid, cell in graph.cells.items():
                if w in cell.cell_prompt.lower():
                    matched.add(cid)

        return matched or set(graph.cells.keys())   # fallback: all cells

    # ------------------------------------------------------------------
    # Subgraph BFS expansion
    # ------------------------------------------------------------------

    def get_subgraph(
        self, graph: BuildingGraph, cell_ids: list[str], hops: int = 1
    ) -> list[GraphCell]:
        """Return all cells within N hops of the seed cell IDs."""
        ng      = self._get_nx(graph.building_id)
        visited = set(cell_ids)
        queue   = deque((cid, 0) for cid in cell_ids)
        result  = list(cell_ids)

        while queue:
            cur, depth = queue.popleft()
            if depth >= hops:
                continue
            for nb in list(ng.successors(cur)) + list(ng.predecessors(cur)):
                if nb not in visited:
                    visited.add(nb)
                    result.append(nb)
                    queue.append((nb, depth + 1))

        return [graph.cells[cid] for cid in result if cid in graph.cells]

    # ------------------------------------------------------------------
    # Feedback edge
    # ------------------------------------------------------------------

    def add_feedback_edge(
        self, graph: BuildingGraph, source_cell_id: str, feedback: str
    ) -> None:
        edge = GraphEdge(
            source_id=source_cell_id,
            target_id=source_cell_id,
            edge_type=EdgeType.FEEDBACK_ON,
            metadata={"feedback": feedback, "timestamp": datetime.utcnow().isoformat()},
        )
        self.add_edge(graph, edge)

    # ------------------------------------------------------------------
    # Token reduction metric
    # ------------------------------------------------------------------

    def compute_token_reduction(self, full: int, selected: int) -> dict:
        if full == 0:
            return {"reduction_pct": 0.0, "full_count": 0, "selected_count": 0}
        pct = (1.0 - selected / full) * 100
        return {"reduction_pct": round(pct, 1), "full_count": full, "selected_count": selected}

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self, graph: BuildingGraph) -> dict:
        return graph.model_dump(mode="json")

    def from_dict(self, data: dict) -> BuildingGraph:
        graph = BuildingGraph.model_validate(data)
        ng    = nx.DiGraph()
        for cid, cell in graph.cells.items():
            ng.add_node(cid, cell_type=cell.cell_type)
        for edge in graph.edges:
            ng.add_edge(edge.source_id, edge.target_id, edge_type=edge.edge_type)
        self._nx[graph.building_id] = ng
        return graph

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_nx(self, building_id: str) -> nx.DiGraph:
        if building_id not in self._nx:
            self._nx[building_id] = nx.DiGraph()
        return self._nx[building_id]

    def _estimate_tokens(self, cells: list[GraphCell], request: str) -> int:
        tokens = len(request) * _TOKENS_PER_CHAR
        for cell in cells:
            tokens += len(cell.cell_prompt) * _TOKENS_PER_CHAR
            tokens += len(cell.photos) * _TOKENS_PER_IMAGE
        return int(tokens)
