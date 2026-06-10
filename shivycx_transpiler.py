'''
Transpiler Strategy Blueprint
ShivyCX-to-C Transpiler: Architectural Blueprint

Translating the ShivyCX compiler into C using a bespoke, AST-driven transpiler is highly feasible because compiler code relies heavily on predictable, structured patterns:
    • Classes represent fixed-schema tokens, symbols, AST nodes, and IL instructions.
    • Methods perform deterministic lookahead, token matches, and tree transformations.
    • Recursion handles expression parsing and tree walking.

By restricting our transpiler specifically to the idioms used in ShivyCX, we avoid the massive complexity of a general-purpose Python-to-C engine (like Cython, Nuitka, or PyPy) and can generate highly optimized C.

1. Key Optimization Strategies for ShivyCX
To make the resulting C compiler compile code at lightning speed, we should apply specific structural translations:

A. Memory Management: Arena Allocation
Compilers are short-lived CLI processes. Instead of implementing reference counting or importing a heavy garbage collector (like Boehm GC), use an Arena Allocator in the generated C code.
    • Mechanism: Every time a node, token, or symbol is created, allocate it from a global or context-passed pre-allocated memory chunk (arena).
    • Performance: Allocation is a single pointer increment (orders of magnitude faster than malloc).
    • Deallocation: No free() calls are needed during parsing or codegen. When the compiler exits, the entire arena is destroyed at once.

B. Type Hinting as Static C Declarations
We will enforce strict type hinting on the ShivyCX codebase. The transpiler will read these annotations directly to generate concrete C types:
    • def advance(self) -> Token: → Token* Parser_advance(Parser* self)
    • self.value: str → const char* value;
    • self.kind: int → int kind;

C. String Handling
Python's immutable strings with heavy allocation can be represented in C as:
    • For identifier tokens: Pointer-and-length views (typedef struct { const char* data; size_t len; } StringView;) or null-terminated strings (const char*) inside the Arena.
    • This avoids copy overhead during lexing and tokenization.

D. Dynamic Arrays and Collections
Python list objects (e.g., token streams, child AST nodes) should map to simple, cache-friendly dynamically-resized arrays in C:

C
typedef struct {
    ASTNode** data;
    size_t size;
    size_t capacity;
} ASTNodeList;

2. ShivyCX Python-to-C Mapping Rules

+----------------------------+-------------------------------------------+-------------------------------------------------+
| Python Construct           | C Implementation                          | Notes                                           |
+----------------------------+-------------------------------------------+-------------------------------------------------+
| class Node:                | typedef struct Node Node;                 | Class attributes map directly to struct         |
|                            | struct Node { ... };                      | members.                                        |
+----------------------------+-------------------------------------------+-------------------------------------------------+
| def __init__(self, x: int):| Node* Node_new(int x, Arena* arena)       | Allocates struct from the Arena and returns     |
|                            |                                           | pointer.                                        |
+----------------------------+-------------------------------------------+-------------------------------------------------+
| def method(self, y: int)   | bool Node_method(Node* self, int y)       | The self parameter is explicitly passed as a    |
| -> bool:                   |                                           | pointer.                                        |
+----------------------------+-------------------------------------------+-------------------------------------------------+
| if x == y:                 | if (x == y) { ... }                       | Direct translation.                             |
+----------------------------+-------------------------------------------+-------------------------------------------------+
| self.x = x                 | self->x = x;                              | Translated to pointer dereference.              |
+----------------------------+-------------------------------------------+-------------------------------------------------+

3. Recommended Phased Implementation Roadmap
    1. Step 1: Strict Annotations: Fully annotate the target ShivyCX modules with Python type hints.
    2. Step 2: Lexer Transpilation: Start by transpiling the lexer (since it has the simplest data structures: strings, characters, and integers). Verify performance.
    3. Step 3: Parser Transpilation: Transpile the AST nodes and recursive descent parser. Implement the Arena allocator to handle node generation.
    4. Step 4: IL and Code Generator: Transpile the code generation phase.
    5. Step 5: Bootstrap verification: Ensure the generated C-compiled ShivyCX compiles test C programs identically to the original Python version.


'''


import ast, sys
from typing import Set, Dict, List

class ShivyCXTranspiler(ast.NodeVisitor):
    def __init__(self):
        self.indent_level = 0
        self.c_code = []
        self.struct_declarations = []
        self.function_prototypes = []
        self.current_class: str = None
        self.declared_variables: Set[str] = set()
        
        # Type maps from Python hints to C types
        self.type_map = {
            'int': 'int',
            'float': 'double',
            'str': 'const char*',
            'bool': 'bool',
            'None': 'void',
        }

    def indent(self) -> str:
        return "    " * self.indent_level

    def write(self, code: str):
        self.c_code.append(f"{self.indent()}{code}")

    def map_type(self, node_annotation) -> str:
        """Translates a Python type annotation AST node into a C type string."""
        if isinstance(node_annotation, ast.Name):
            type_name = node_annotation.id
            if type_name in self.type_map:
                return self.type_map[type_name]
            # Custom class types map to pointers to those structs
            return f"{type_name}*"
        elif isinstance(node_annotation, ast.Subscript):
            # Example: List[Token] -> TokenList* or generic Vector representation
            value = self.map_type(node_annotation.value)
            slice_type = self.map_type(node_annotation.slice)
            return f"{slice_type}List*"
        elif isinstance(node_annotation, ast.Constant) and node_annotation.value is None:
            return "void"
        return "void*"

    def visit_Module(self, node: ast.Module):
        # We process the source code in two phases to build prototypes first
        self.write("/* Automatically generated by ShivyCX Transpiler */\n")
        self.write("#include <stdio.h>")
        self.write("#include <stdlib.h>")
        self.write("#include <stdbool.h>")
        self.write("#include <string.h>\n")
        
        # Walk definitions
        for body_item in node.body:
            self.visit(body_item)

    def visit_ClassDef(self, node: ast.ClassDef):
        class_name = node.name
        self.current_class = class_name
        self.declared_variables = set()

        # Step 1: Collect structural attributes from annotated assignments in __init__
        attributes: List[tuple] = []
        methods: List[ast.FunctionDef] = []

        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                if item.name == "__init__":
                    # Look inside __init__ for instance variable assignments (self.attr = val)
                    for stmt in item.body:
                        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Attribute):
                            attr_name = stmt.target.attr
                            c_type = self.map_type(stmt.annotation)
                            attributes.append((c_type, attr_name))
                else:
                    methods.append(item)

        # Generate Struct definition
        self.write(f"/* Class Structure for {class_name} */")
        self.write(f"typedef struct {class_name} {class_name};")
        self.write(f"struct {class_name} {{")
        self.indent_level += 1
        for c_type, attr_name in attributes:
            self.write(f"{c_type} {attr_name};")
        self.indent_level -= 1
        self.write("};\n")

        # Process the constructor (__init__) as a custom _new allocator function
        init_method = next((m for m in node.body if isinstance(m, ast.FunctionDef) and m.name == "__init__"), None)
        if init_method:
            self.generate_constructor(class_name, init_method, attributes)

        # Step 2: Generate class methods
        for method in methods:
            self.visit(method)

        self.current_class = None

    def generate_constructor(self, class_name: str, init_node: ast.FunctionDef, attributes: List[tuple]):
        """Generates a C memory allocator and constructor from Python's __init__."""
        # Collect parameters (skipping 'self')
        params = []
        for arg in init_node.args.args:
            if arg.arg == 'self':
                continue
            c_type = self.map_type(arg.annotation)
            params.append(f"{c_type} {arg.arg}")
        
        param_list = ", ".join(params)
        self.write(f"/* Constructor for {class_name} */")
        self.write(f"{class_name}* {class_name}_new({param_list}) {{")
        self.indent_level += 1
        
        # Simple allocator simulation (We could replace this with Arena Allocators)
        self.write(f"{class_name}* self = ({class_name}*)malloc(sizeof({class_name}));")
        
        # Translate statements inside __init__
        for stmt in init_node.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Attribute):
                # Translate self.x: type = value
                if stmt.value:
                    val_str = self.to_c_expr(stmt.value)
                    self.write(f"self->{stmt.target.attr} = {val_str};")
            elif isinstance(stmt, ast.Assign) and isinstance(stmt.targets[0], ast.Attribute):
                # Translate self.x = value
                val_str = self.to_c_expr(stmt.value)
                self.write(f"self->{stmt.targets[0].attr} = {val_str};")
            else:
                self.visit(stmt)

        self.write("return self;")
        self.indent_level -= 1
        self.write("}\n")

    def visit_FunctionDef(self, node: ast.FunctionDef):
        # Determine function name and parameters
        func_name = node.name
        if self.current_class:
            func_name = f"{self.current_class}_{func_name}"

        params = []
        for arg in node.args.args:
            if arg.arg == 'self':
                params.append(f"{self.current_class}* self")
            else:
                c_type = self.map_type(arg.annotation)
                params.append(f"{c_type} {arg.arg}")

        param_list = ", ".join(params)
        return_type = self.map_type(node.returns) if node.returns else "void"

        self.write(f"{return_type} {func_name}({param_list}) {{")
        self.indent_level += 1

        # Body Translation
        for stmt in node.body:
            self.visit(stmt)

        self.indent_level -= 1
        self.write("}\n")

    def visit_AnnAssign(self, node: ast.AnnAssign):
        # Statically typed variable instantiation: e.g. "x: int = 5"
        if isinstance(node.target, ast.Name):
            var_name = node.target.id
            c_type = self.map_type(node.annotation)
            if var_name not in self.declared_variables:
                self.declared_variables.add(var_name)
                if node.value:
                    val_str = self.to_c_expr(node.value)
                    self.write(f"{c_type} {var_name} = {val_str};")
                else:
                    self.write(f"{c_type} {var_name};")
            else:
                if node.value:
                    val_str = self.to_c_expr(node.value)
                    self.write(f"{var_name} = {val_str};")

    def visit_Assign(self, node: ast.Assign):
        # Non-annotated variable assignments or attribute sets
        val_str = self.to_c_expr(node.value)
        for target in node.targets:
            if isinstance(target, ast.Name):
                var_name = target.id
                # If we haven't declared it, auto-infer "int" for prototype simplicity
                if var_name not in self.declared_variables:
                    self.declared_variables.add(var_name)
                    self.write(f"int {var_name} = {val_str};")
                else:
                    self.write(f"{var_name} = {val_str};")
            elif isinstance(target, ast.Attribute):
                # e.g., self.x = 5 -> self->x = 5;
                obj = self.to_c_expr(target.value)
                self.write(f"{obj}->{target.attr} = {val_str};")

    def visit_If(self, node: ast.If):
        cond = self.to_c_expr(node.test)
        self.write(f"if ({cond}) {{")
        self.indent_level += 1
        for stmt in node.body:
            self.visit(stmt)
        self.indent_level -= 1
        
        if node.orelse:
            self.write("} else {")
            self.indent_level += 1
            for stmt in node.orelse:
                self.visit(stmt)
            self.indent_level -= 1
            
        self.write("}")

    def visit_Return(self, node: ast.Return):
        if node.value:
            val_str = self.to_c_expr(node.value)
            self.write(f"return {val_str};")
        else:
            self.write("return;")

    def visit_Expr(self, node: ast.Expr):
        expr_str = self.to_c_expr(node.value)
        self.write(f"{expr_str};")

    # --- EXPRESSION TRANSLATION ---
    def to_c_expr(self, node) -> str:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, str):
                return f'"{node.value}"'
            elif isinstance(node.value, bool):
                return "true" if node.value else "false"
            elif node.value is None:
                return "NULL"
            return str(node.value)
        
        elif isinstance(node, ast.Name):
            return node.id
        
        elif isinstance(node, ast.Attribute):
            # Maps self.value to self->value
            obj = self.to_c_expr(node.value)
            op = "->" if obj == "self" else "."
            return f"{obj}{op}{node.attr}"
        
        elif isinstance(node, ast.BinOp):
            left = self.to_c_expr(node.left)
            right = self.to_c_expr(node.right)
            op_map = {
                ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/",
                ast.Mod: "%", ast.LShift: "<<", ast.RShift: ">>"
            }
            op_str = op_map.get(type(node.op), "?")
            return f"({left} {op_str} {right})"
        
        elif isinstance(node, ast.Compare):
            left = self.to_c_expr(node.left)
            # Support simple binary comparisons for the prototype
            op_map = {
                ast.Eq: "==", ast.NotEq: "!=", ast.Lt: "<",
                ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">="
            }
            op_str = op_map.get(type(node.ops[0]), "==")
            right = self.to_c_expr(node.comparators[0])
            return f"({left} {op_str} {right})"
        
        elif isinstance(node, ast.Call):
            func_name = self.to_c_expr(node.func)
            args = [self.to_c_expr(arg) for arg in node.args]
            
            # Map object-method calls to C-function layout: object.method(args) -> Class_method(object, args)
            if isinstance(node.func, ast.Attribute):
                # E.g., token.match(val)
                obj_name = self.to_c_expr(node.func.value)
                method_name = node.func.attr
                # We dynamically infer the Class-based function prefix if known or capitalized
                class_prefix = "Token" # Prototype assumption, can be built out using scopes
                return f"{class_prefix}_{method_name}({obj_name}, {', '.join(args)})"
                
            return f"{func_name}({', '.join(args)})"
            
        return f"/* Unknown translation: {ast.dump(node)} */"

# --- PROTOTYPE EXAMPLE VERIFICATION ---
if __name__ == "__main__":
    # Test script representing a typical compiler module structure in Python
    sample_python_code = """
class Token:
    def __init__(self, kind: int, value: str):
        self.kind: int = kind
        self.value: str = value

    def is_match(self, target_kind: int) -> bool:
        if self.kind == target_kind:
            return True
        return False

def run_lexing_test() -> int:
    t: Token = Token(101, "my_identifier")
    matched: bool = t.is_match(101)
    if matched:
        return 0
    return 1
"""

    tree = ast.parse(sample_python_code)
    transpiler = ShivyCXTranspiler()
    transpiler.visit(tree)
    
    # Print generated C Code
    print("\n".join(transpiler.c_code))