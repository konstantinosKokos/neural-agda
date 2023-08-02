from .agda.syntax import File, Declaration, Hole, Reference
from .internal.term_to_tree import AgdaTree, BinaryOps, UnaryOps, NullaryOps, term_to_tree
from .internal.tree import flatten, enumerate_nodes

TokenizedNode = tuple[int, int, int, int]
TokenizedAST = list[TokenizedNode]


def tokenize_node(content: BinaryOps | tuple[UnaryOps, int] | NullaryOps,
                  node_idx: int,
                  tree_idx: int) -> TokenizedNode:
    match content:
        case BinaryOps(op): return 1, op, node_idx, tree_idx
        case NullaryOps(op): return 2, op, node_idx, tree_idx
        case (UnaryOps(op), value): return 3 + op, value, node_idx, tree_idx
        case _: raise ValueError


def detokenize_node(node: tuple[int, int]) -> BinaryOps | tuple[UnaryOps, int] | NullaryOps:
    match node:
        case 1, value: return BinaryOps(value)
        case 2, value: return NullaryOps(value)
        case op, value: return UnaryOps(op - 3), value
        case _: raise ValueError


def tokenize_ast(ast: AgdaTree, tree_index: int) -> TokenizedAST:
    flat = flatten(enumerate_nodes(ast))
    return [(0, 0, 0, tree_index),
            *[tokenize_node(content, idx, tree_index) for content, idx in flat if content != NullaryOps.Abs]]


def detokenize_ast(nodes: TokenizedAST) -> AgdaTree:
    raise NotImplementedError


def tokenize_file(file: File[int]) -> tuple[list[tuple[TokenizedAST, TokenizedAST]],
                                            list[tuple[TokenizedAST, TokenizedAST, list[int]]]]:
    scope = [(tokenize_ast(term_to_tree(entry.type), i),
              tokenize_ast(term_to_tree(entry.definition), i)) for i, entry in enumerate(file.scope)]
    holes = [(tokenize_ast(term_to_tree(hole.type), -1),
              tokenize_ast(term_to_tree(hole.definition), -1),
              [premise.name for premise in hole.premises]) for hole in file.holes]
    return scope, holes


def detokenize_file(file: tuple[list[tuple[TokenizedAST, TokenizedAST]],
                                list[tuple[TokenizedAST, TokenizedAST, list[int]]]],
                    name: str) -> File[int]:
    tokenized_scope, tokenized_holes = file
    return File(scope=[Declaration(name=i, type=detokenize_ast(type_ast), definition=detokenize_ast(def_ast))
                       for i, (type_ast, def_ast) in tokenized_scope],
                holes=[Hole(type=detokenize_ast(type_ast),
                            definition=detokenize_ast(def_ast),
                            premises=[Reference(p) for p in premises])
                       for type_ast, def_ast, premises in tokenized_holes],
                name=name)
