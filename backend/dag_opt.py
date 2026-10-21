# dag_opt.py - DAG-based optimization for expressions (Compiler Design, BCSE307L)
# Implements: DAG construction, value numbering, algebraic identities, 
# commutative/associative laws, common subexpression elimination

from collections import defaultdict
import tac

class DAGNode:
    """Node in the expression DAG"""
    __slots__ = ('op', 'left', 'right', 'value_num', 'names', 'const_val')
    
    def __init__(self, op, left=None, right=None, const_val=None):
        self.op = op
        self.left = left      # left child (DAGNode or None for leaf)
        self.right = right    # right child (DAGNode or None)
        self.value_num = None # assigned during value numbering
        self.names = []       # variable names that hold this value
        self.const_val = const_val  # for constant nodes
    
    def is_leaf(self):
        return self.left is None and self.right is None
    
    def __repr__(self):
        if self.is_leaf():
            return f"DAGNode({self.op}, val={self.const_val})"
        return f"DAGNode({self.op}, {self.left}, {self.right})"


class DAGBuilder:
    """Builds DAG for a basic block"""
    
    # Algebraic identities: (op, left_val, right_val) -> simplified
    IDENTITIES = {
        # Addition
        ('+', 0, None): lambda l, r: r,  # 0 + x = x
        ('+', None, 0): lambda l, r: l,  # x + 0 = x
        # Subtraction
        ('-', None, 0): lambda l, r: l,  # x - 0 = x
        ('-', None, None): lambda l, r: 0 if l is r else None,  # x - x = 0
        # Multiplication
        ('*', 1, None): lambda l, r: r,  # 1 * x = x
        ('*', None, 1): lambda l, r: l,  # x * 1 = x
        ('*', 0, None): lambda l, r: 0,  # 0 * x = 0
        ('*', None, 0): lambda l, r: 0,  # x * 0 = 0
        # Division
        ('/', None, 1): lambda l, r: l,  # x / 1 = x
        ('/', 0, None): lambda l, r: 0,  # 0 / x = 0
        # Bitwise
        ('&', -1, None): lambda l, r: r,  # -1 & x = x (all bits 1)
        ('|', 0, None): lambda l, r: r,   # 0 | x = x
        ('^', 0, None): lambda l, r: r,   # 0 ^ x = x
        ('^', None, None): lambda l, r: 0 if l is r else None,  # x ^ x = 0
        # Shift
        ('<<', 0, None): lambda l, r: 0,  # 0 << x = 0
        ('>>', 0, None): lambda l, r: 0,  # 0 >> x = 0
        ('<<', None, 0): lambda l, r: l,  # x << 0 = x
        ('>>', None, 0): lambda l, r: l,  # x >> 0 = x
        # Logical
        ('&&', 0, None): lambda l, r: 0,  # 0 && x = 0
        ('&&', 1, None): lambda l, r: r,  # 1 && x = x
        ('||', 1, None): lambda l, r: 1,  # 1 || x = 1
        ('||', 0, None): lambda l, r: r,  # 0 || x = x
    }
    
    # Commutative operators
    COMMUTATIVE = {'+', '*', '&', '|', '^', '==', '!='}
    
    # Associative operators
    ASSOCIATIVE = {'+', '*', '&', '|', '^', '&&', '||'}
    
    def __init__(self):
        self.nodes = []           # all nodes in DAG
        self.value_to_node = {}   # value number -> node
        self.expr_to_node = {}    # (op, left_vn, right_vn) -> node
        self.leaf_nodes = {}      # variable/constant -> node
        self.next_vn = 1
        self.changes = 0
    
    def get_leaf(self, operand):
        """Get or create leaf node for variable or constant"""
        if operand in self.leaf_nodes:
            return self.leaf_nodes[operand]
        
        if isinstance(operand, int):
            node = DAGNode('const', const_val=operand)
        else:
            node = DAGNode('var', const_val=operand)
            node.names.append(operand)
        
        self.leaf_nodes[operand] = node
        self.nodes.append(node)
        return node
    
    def find_or_create_node(self, op, left, right):
        """Find existing node or create new one (with value numbering)"""
        # Check algebraic identities first
        left_val = left.const_val if left.op in ('const', 'var') and left.const_val is not None else None
        right_val = right.const_val if right.op in ('const', 'var') and right.const_val is not None else None
        
        for (id_op, id_left, id_right), simplifier in self.IDENTITIES.items():
            if op == id_op:
                if (id_left is None or left_val == id_left) and (id_right is None or right_val == id_right):
                    result = simplifier(left_val, right_val)
                    if result is not None:
                        if isinstance(result, int):
                            return self.get_leaf(result)
                        elif result is left:
                            return left
                        elif result is right:
                            return right
        
        # Get value numbers for children
        left_vn = left.value_num or self._assign_vn(left)
        right_vn = right.value_num or self._assign_vn(right)
        
        # For commutative ops, sort children
        if op in self.COMMUTATIVE:
            key = (op, min(left_vn, right_vn), max(left_vn, right_vn))
        else:
            key = (op, left_vn, right_vn)
        
        if key in self.expr_to_node:
            existing = self.expr_to_node[key]
            self.changes += 1
            return existing
        
        # Create new node
        node = DAGNode(op, left, right)
        node.value_num = self.next_vn
        self.next_vn += 1
        self.expr_to_node[key] = node
        self.nodes.append(node)
        return node
    
    def _assign_vn(self, node):
        if node.value_num is None:
            node.value_num = self.next_vn
            self.next_vn += 1
        return node.value_num
    
    def apply_identity(self, node):
        """Apply algebraic identities to a node"""
        if node.is_leaf():
            return node
        
        # Recursively simplify children
        node.left = self.apply_identity(node.left)
        node.right = self.apply_identity(node.right)
        
        # Try to apply identities
        left_val = node.left.const_val if node.left.op in ('const', 'var') and node.left.const_val is not None else None
        right_val = node.right.const_val if node.right.op in ('const', 'var') and node.right.const_val is not None else None
        
        for (id_op, id_left, id_right), simplifier in self.IDENTITIES.items():
            if node.op == id_op:
                if (id_left is None or left_val == id_left) and (id_right is None or right_val == id_right):
                    result = simplifier(left_val, right_val)
                    if result is not None:
                        if isinstance(result, int):
                            return self.get_leaf(result)
                        elif result is node.left:
                            return node.left
                        elif result is node.right:
                            return node.right
        
        return node
    
    def build_from_block(self, instrs):
        """Build DAG from a basic block's instructions"""
        self.nodes = []
        self.value_to_node = {}
        self.expr_to_node = {}
        self.leaf_nodes = {}
        self.next_vn = 1
        self.changes = 0
        
        for ins in instrs:
            if ins.op in ('copy', 'neg', 'not', 'bnot'):
                # Unary/copy operations
                src_node = self.get_leaf(ins.arg1) if isinstance(ins.arg1, (int, str)) else None
                if src_node:
                    dst_var = ins.result
                    if ins.op == 'copy':
                        # Transfer value
                        src_node.names.append(dst_var)
                        self.leaf_nodes[dst_var] = src_node
                    elif ins.op == 'neg':
                        const_node = self.get_leaf(-src_node.const_val) if src_node.op == 'const' else None
                        if const_node:
                            const_node.names.append(dst_var)
                            self.leaf_nodes[dst_var] = const_node
                        else:
                            node = DAGNode('neg', src_node)
                            node.value_num = self.next_vn
                            self.next_vn += 1
                            node.names.append(dst_var)
                            self.nodes.append(node)
                            self.leaf_nodes[dst_var] = node
                    # ... similar for not, bnot
            elif ins.op in ('+', '-', '*', '/', '%', '&', '|', '^', '<<', '>>', 
                           '<', '>', '<=', '>=', '==', '!=', '&&', '||', 'shl'):
                # Binary operations
                left_node = self.get_leaf(ins.arg1) if isinstance(ins.arg1, (int, str)) else None
                right_node = self.get_leaf(ins.arg2) if isinstance(ins.arg2, (int, str)) else None
                if left_node and right_node:
                    result_node = self.find_or_create_node(ins.op, left_node, right_node)
                    result_node = self.apply_identity(result_node)
                    result_node.names.append(ins.result)
                    self.leaf_nodes[ins.result] = result_node
            # Other ops (calls, jumps, etc.) break the chain
            elif ins.op in ('call', 'goto', 'ifFalse', 'label', 'return', 'print', 'out_val', 'out_str'):
                self.leaf_nodes.clear()  # Conservative: clear all
        
        return self


def build_dag(block_instrs):
    """Build DAG for a basic block, return (builder, dag_nodes)"""
    builder = DAGBuilder()
    builder.build_from_block(block_instrs)
    return builder, builder.nodes


def dag_to_instructions(builder, original_instrs):
    """Convert DAG back to instructions with optimizations applied"""
    # Map destination variables to their defining instruction
    var_to_instr = {}
    for ins in original_instrs:
        if ins.result is not None:
            var_to_instr[ins.result] = ins
    
    # Generate optimized instructions from DAG
    new_instrs = []
    emitted = set()  # value numbers already emitted
    
    # Topological sort of DAG nodes
    def emit_node(node):
        if node.value_num in emitted or node.is_leaf():
            return
        
        # Emit children first
        if node.left:
            emit_node(node.left)
        if node.right:
            emit_node(node.right)
        
        # Emit this node
        if node.names:
            # Use first name as destination
            dst = node.names[0]
            # Find original instruction for type info
            orig = var_to_instr.get(dst)
            ty = orig.ty if orig and hasattr(orig, 'ty') else None
            
            if node.op in ('+', '-', '*', '/', '%', '&', '|', '^', '<<', '>>',
                           '<', '>', '<=', '>=', '==', '!=', '&&', '||', 'shl'):
                left_val = node.left.const_val if node.left and node.left.op in ('const', 'var') else node.left
                right_val = node.right.const_val if node.right and node.right.op in ('const', 'var') else node.right
                # Get variable names
                left_name = node.left.names[0] if node.left and node.left.names else (node.left.const_val if node.left and node.left.op == 'const' else None)
                right_name = node.right.names[0] if node.right and node.right.names else (node.right.const_val if node.right and node.right.op == 'const' else None)
                
                if left_name is not None and right_name is not None:
                    new_instrs.append(tac.Instr(node.op, left_name, right_name, dst, ty=ty))
                    emitted.add(node.value_num)
                    return
        
        # Fallback: if we couldn't emit, keep original
        for name in node.names:
            if name in var_to_instr:
                new_instrs.append(var_to_instr[name])
    
    # Emit all nodes with names
    for node in builder.nodes:
        if node.names and node.value_num not in emitted:
            emit_node(node)
    
    # Add non-expression instructions (control flow, calls, etc.) - preserve original order
    for ins in original_instrs:
        if ins.op not in ('copy', 'neg', 'not', 'bnot', '+', '-', '*', '/', '%', '&', '|', '^', '<<', '>>',
                           '<', '>', '<=', '>=', '==', '!=', '&&', '||', 'shl',
                           'if', 'ifFalse', 'goto', 'label', 'call', 'return', 'param',
                           'print', 'out_val', 'out_str', 'cast', 'read'):
            new_instrs.append(ins)
    
    return new_instrs


def dag_optimize(instrs):
    """Optimize a basic block using DAG"""
    from blocks import split_blocks, join_blocks
    import tac
    
    blocks = split_blocks(instrs)
    new_blocks = []
    total_changes = 0
    
    for b in blocks:
        builder, nodes = build_dag(b)
        total_changes += builder.changes
        optimized = dag_to_instructions(builder, b)
        new_blocks.append(optimized)
    
    return join_blocks(new_blocks), total_changes