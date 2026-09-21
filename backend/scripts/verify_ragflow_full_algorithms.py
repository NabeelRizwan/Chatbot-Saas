"""Read-only AST equality gate for critical pinned algorithms, excluding imports."""
import ast
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
PIN = 'a024bea0cd93f39e6652a42bf84dd20c55bc560b'
PAIRS = {
    'rag/advanced_rag/agentic_rag_graph.py': ('advanced_rag/agentic_rag_graph.py',
        ['_expand_fanouts', '_fanout_search', 'build_agentic_graph', 'run_agentic_rag']),
    'rag/advanced_rag/harness/action_session.py': ('advanced_rag/harness/action_session.py',
        ['State', 'Variable', 'run_action_session']),
    'rag/advanced_rag/knowlege_compile/raptor.py': ('advanced_rag/knowlege_compile/raptor.py',
        ['RecursiveAbstractiveProcessing4TreeOrganizedRetrieval']),
    'rag/advanced_rag/harness/tools/navigation.py': ('advanced_rag/harness/tools/navigation.py',
        ['_navigate_tree_impl', '_navigate_structure_impl']),
    'rag/graphrag/search.py': ('graphrag/search.py', ['KGSearch']),
    'common/metadata_utils.py': ('metadata_utils.py', ['meta_filter', 'apply_meta_data_filter']),
}


class WithoutImportsOrDocstrings(ast.NodeTransformer):
    def visit_Import(self, node): return None
    def visit_ImportFrom(self, node): return None
    def visit_Expr(self, node):
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return None
        return self.generic_visit(node)


def selected(text, symbol):
    module = ast.parse(text)
    node = next(n for n in module.body if getattr(n, 'name', None) == symbol)
    return ast.dump(WithoutImportsOrDocstrings().visit(node), include_attributes=False)


def main():
    checked = []
    for source, (dest, symbols) in PAIRS.items():
        original = subprocess.check_output(['git', '-C', str(ROOT / '.codex_ragflow_upstream'),
                                            'show', PIN + ':' + source]).decode()
        local = (ROOT / 'backend/ragflow_derived/upstream' / dest).read_text(encoding='utf-8')
        for symbol in symbols:
            assert selected(original, symbol) == selected(local, symbol), (source, symbol)
            checked.append(source + ':' + symbol)
    print('Pinned algorithm AST parity: PASS; critical symbols =', len(checked))


if __name__ == '__main__':
    main()
