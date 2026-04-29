"""Dependency graph builder — topological sort and cycle detection."""

from __future__ import annotations

from collections import defaultdict, deque

from .schema import ModuleDefinition


class CyclicDependencyError(Exception):
    """Raised when module dependencies contain a cycle."""


def build_execution_order(modules: list[ModuleDefinition]) -> list[str]:
    """Return module IDs in topological order (Kahn's algorithm).

    Raises CyclicDependencyError if a cycle is detected.
    """
    ids = {m.module_id for m in modules}
    adj: dict[str, list[str]] = defaultdict(list)
    in_degree: dict[str, int] = {m.module_id: 0 for m in modules}

    for m in modules:
        for dep in m.dependencies:
            if dep not in ids:
                continue  # skip unknown deps (external)
            adj[dep].append(m.module_id)
            in_degree[m.module_id] += 1

    queue: deque[str] = deque(
        mid for mid, deg in in_degree.items() if deg == 0
    )
    order: list[str] = []

    while queue:
        node = queue.popleft()
        order.append(node)
        for neighbour in adj[node]:
            in_degree[neighbour] -= 1
            if in_degree[neighbour] == 0:
                queue.append(neighbour)

    if len(order) != len(ids):
        remaining = ids - set(order)
        raise CyclicDependencyError(
            f"Cyclic dependency detected among: {sorted(remaining)}"
        )

    return order


def validate_no_cycles(modules: list[ModuleDefinition]) -> list[str]:
    """Return list of error strings. Empty means no issues."""
    try:
        build_execution_order(modules)
        return []
    except CyclicDependencyError as exc:
        return [str(exc)]
