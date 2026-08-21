"""
Recording a successful run and compiling it into graph pieces.

``recording`` accumulates nodes and edges as actions succeed;
``builder`` turns the accumulated state into a pure ``Recording``
(parameterised, sensitive literals promoted to inputs); ``segment``
splits a multi-app recording at app boundaries so each vendor keeps its
own graph.
"""
