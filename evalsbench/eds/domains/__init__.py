"""
Domain-specific fixtures and tool sets for the EDS subpackage.

This package groups per-domain (MiniCorp, future benchmarks) episode
factories and tool surfaces. Each subpackage owns its own
``fixtures.py`` (a ``minicorp_fixture``-style constructor returning a
validated :class:`~evalsbench.eds.models.WorldFixture`) and ``tools.py``
(a list of :func:`@mock_tool <evalsbench.eds.tools.mock_tool>`-decorated
functions operating on the active :class:`~evalsbench.eds.world.WorldState`).

The accompanying ``tasks.py`` per domain is owned by a separate wave and
therefore is intentionally not declared here.
"""
